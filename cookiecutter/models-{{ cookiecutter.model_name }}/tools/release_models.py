"""Generate validated model releases; publishing is an explicit workflow option."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
PROVENANCE = ".cloudcoil-release.json"


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def version_key(value):
    if not SEMVER.fullmatch(value):
        raise ValueError(f"Invalid upstream version: {value!r}")
    return tuple(map(int, value.split(".")))


def packaging_revision(tag, upstream):
    match = re.fullmatch(re.escape(upstream) + r"\.(0|[1-9]\d*)", tag)
    return int(match[1]) if match else None


def next_version(upstream, reserved):
    revisions = [packaging_revision(tag, upstream) for tag in reserved]
    return f"{upstream}.{max((v for v in revisions if v is not None), default=-1) + 1}"


def set_project_version(text, version):
    # Restrict edits to [project]; never touch python_version, target-version, or tools.
    match = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    if not match:
        raise ValueError("Missing project table")
    body, count = re.subn(r'^version\s*=\s*"[^"]*"', f'version = "{version}"', match[1], flags=re.M)
    if count != 1:
        raise ValueError("Expected one literal project version")
    return text[: match.start(1)] + body + text[match.end(1) :]


def prepare(root, upstream):
    manifest = json.loads((root / "model-release.json").read_text())
    versions = ast.literal_eval("[" + manifest["versions"] + "]")
    for version in [upstream, *versions]:
        version_key(version)
    if upstream not in versions:
        raise ValueError(f"Unsupported upstream version {upstream}")
    current = max(versions, key=version_key)
    path = root / "pyproject.toml"
    text = path.read_text()
    config = tomllib.loads(text)
    inputs = config["tool"]["cloudcoil"]["codegen"]["models"][0]["input"]
    for url in inputs:
        if url.startswith("https://"):
            updated = re.sub(rf"(?<!\d){re.escape(current)}(?!\d)", upstream, url)
            if current != upstream and updated == url:
                raise ValueError(f"Cannot version input URL: {url}")
            text = text.replace(json.dumps(url), json.dumps(updated))
    path.write_text(set_project_version(text, upstream + ".0"))


def generated_files(root):
    files = sorted(
        p for p in (root / "cloudcoil").rglob("*") if p.is_file() and p.suffix in {".py", ".typed"}
    )
    lookups = [p for p in files if p.name == "_lookup.py"]
    if not lookups:
        raise ValueError("Missing generated resource lookup; generate models first")
    for lookup in lookups:
        tree = ast.parse(lookup.read_text())
        registries = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_MODELS" for target in node.targets
            )
        ]
        if len(registries) != 1 or not isinstance(registries[0], dict) or not registries[0]:
            raise ValueError(f"Empty generated resource lookup: {lookup.relative_to(root)}")
        for module, _ in registries[0].values():
            path = root.joinpath(*module.split(".")).with_suffix(".py")
            if path not in files or not path.read_text().strip():
                raise ValueError(f"Missing or empty generated model module: {module}")
    return files


def fingerprint(root):
    config = tomllib.loads((root / "pyproject.toml").read_text())
    project = dict(config["project"])
    project.pop("version")
    # Include runtime metadata and build configuration, not tooling-only lockfile churn.
    payload = {
        "project": project,
        "build-system": config["build-system"],
        "hatch": config["tool"]["hatch"],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode())
    files = generated_files(root)
    for path in files:
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def pypi_versions(package):
    name = re.sub(r"[-_.]+", "-", package).lower()
    try:
        with urlopen(f"https://pypi.org/pypi/{name}/json", timeout=60) as response:
            return set(json.load(response)["releases"])
    except HTTPError as error:
        if error.code == 404:
            return set()
        raise


def verify_artifacts(root, version):
    config = tomllib.loads((root / "pyproject.toml").read_text())
    wheels = list((root / "dist").glob("*.whl"))
    sdists = list((root / "dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one source distribution")
    expected = {str(p.relative_to(root)): p.read_bytes() for p in generated_files(root)}
    with zipfile.ZipFile(wheels[0]) as archive:
        if not expected.keys() <= set(archive.namelist()):
            raise ValueError("Wheel omits generated model files")
        if any(archive.read(name) != content for name, content in expected.items()):
            raise ValueError("Wheel model contents differ from generated source")
        metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Expected one wheel metadata file")
        info = BytesParser().parsebytes(archive.read(metadata[0]))
    with tarfile.open(sdists[0]) as archive:
        members = {m.name.split("/", 1)[-1]: m for m in archive.getmembers() if m.isfile()}
        paths = set(members)
        if not expected.keys() <= paths:
            raise ValueError("Source distribution omits generated model files")
        for name, content in expected.items():
            extracted = archive.extractfile(members[name])
            if extracted is None or extracted.read() != content:
                raise ValueError("Source distribution model contents differ from generated source")

    def normalize(value):
        return re.sub(r"[-_.]+", "-", value).lower()

    if (
        normalize(info["Name"]) != normalize(config["project"]["name"])
        or info["Version"] != version
    ):
        raise ValueError("Built package identity does not match the release")
    from packaging.requirements import Requirement

    dependencies = {
        Requirement(dep).name: Requirement(dep) for dep in info.get_all("Requires-Dist", [])
    }
    declared = next(
        Requirement(dep)
        for dep in config["project"]["dependencies"]
        if Requirement(dep).name == "cloudcoil"
    )
    if "cloudcoil" not in dependencies or dependencies["cloudcoil"].specifier != declared.specifier:
        raise ValueError("Wheel Cloudcoil requirement differs from pyproject.toml")
    lock = tomllib.loads((root / "uv.lock").read_text())
    locked = next(p["version"] for p in lock["package"] if p["name"] == "cloudcoil")
    if locked not in declared.specifier:
        raise ValueError("Locked Cloudcoil does not satisfy the package requirement")


def release_list(repo):
    pages = json.loads(
        run("gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100")
    )
    return [item for page in pages for item in page]


def read_provenance(checkout, tag):
    result = subprocess.run(
        ["git", "show", f"refs/tags/{tag}:{PROVENANCE}"],
        cwd=checkout,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        return {}
    return json.loads(result.stdout)


def finish(root, upstream, publish=False, dry_run=False):
    version_key(upstream)
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"cloudcoil/models-[a-z0-9-]+", repo):
        raise ValueError("Release automation is restricted to Cloudcoil model repositories")
    main_sha = run("git", "rev-parse", "HEAD", cwd=root)
    remote = f"https://github.com/{repo}.git"
    branch = "release-" + ".".join(upstream.split(".")[:2])
    content_hash = fingerprint(root)
    releases = release_list(repo)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    published = pypi_versions(project["name"])
    with tempfile.TemporaryDirectory() as directory:
        checkout = Path(directory)
        run("git", "clone", "--quiet", remote, str(checkout))
        tags = set(run("git", "tag", "--list", cwd=checkout).splitlines())
        published_releases = [
            r
            for r in releases
            if not r["draft"] and packaging_revision(r["tag_name"], upstream) is not None
        ]
        if published_releases:
            last = max(
                published_releases, key=lambda r: packaging_revision(r["tag_name"], upstream)
            )
            if read_provenance(checkout, last["tag_name"]).get("fingerprint") == content_hash:
                print(
                    f"Unchanged: {last['tag_name']} already released. Rerun its PyPI job if publication failed."
                )
                return
        version = next_version(
            upstream, tags | published | {r["tag_name"] for r in published_releases}
        )
        drafts = [r for r in releases if r["draft"] and r["tag_name"] == version]
        if len(drafts) > 1:
            raise ValueError("Multiple drafts reserve the same release version")
        path = root / "pyproject.toml"
        path.write_text(set_project_version(path.read_text(), version))
        run("uv", "lock", cwd=root)
        # A clean isolated output directory prevents old wheels entering a new release.
        with tempfile.TemporaryDirectory() as artifacts:
            run("uv", "build", "--out-dir", artifacts, cwd=root)
            (root / "dist").mkdir(exist_ok=True)
            if any((root / "dist").iterdir()):
                raise ValueError("dist must be empty before building a release")
            for artifact in Path(artifacts).iterdir():
                shutil.copy2(artifact, root / "dist" / artifact.name)
        verify_artifacts(root, version)
        if dry_run:
            print(
                f"Validated {version} ({content_hash}); no repository changes or release publication."
            )
            return
        if run("git", "ls-remote", remote, "refs/heads/main").split()[0] != main_sha:
            raise ValueError("Main advanced during generation; rerun from current main")
        exists = (
            subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                cwd=checkout,
            ).returncode
            == 0
        )
        if exists:
            run("git", "checkout", "-B", branch, f"origin/{branch}", cwd=checkout)
        else:
            run("git", "checkout", "-b", branch, cwd=checkout)
        run("git", "rm", "-r", "--ignore-unmatch", ".", cwd=checkout)
        files = run(
            "git", "ls-files", "--cached", "--others", "--exclude-standard", cwd=root
        ).splitlines()
        # Fail if ignore rules hide generated namespaces (for example nested build/).
        generated = {
            str(p.relative_to(root))
            for p in (root / "cloudcoil").rglob("*")
            if p.is_file() and p.suffix in {".py", ".typed"}
        }
        if not generated <= set(files):
            raise ValueError("Git ignore rules hide generated model files")
        for filename in files:
            source = root / filename
            if not source.is_file() or filename.startswith("dist/"):
                continue
            dest = checkout / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        (checkout / PROVENANCE).write_text(
            json.dumps(
                {
                    "upstream": upstream,
                    "version": version,
                    "source_sha": main_sha,
                    "fingerprint": content_hash,
                },
                indent=2,
            )
            + "\n"
        )
        run("git", "config", "user.name", "github-actions[bot]", cwd=checkout)
        run(
            "git",
            "config",
            "user.email",
            "github-actions[bot]@users.noreply.github.com",
            cwd=checkout,
        )
        run("git", "add", "-A", cwd=checkout)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=checkout)
        if diff.returncode == 1:
            run("git", "commit", "--signoff", "-m", f"Generate {version}", cwd=checkout)
        elif diff.returncode != 0:
            raise ValueError("Cannot inspect the staged release changes")
        sha = run("git", "rev-parse", "HEAD", cwd=checkout)
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=checkout)
        notes = f"Models for upstream {upstream}.\n\nSource: {main_sha}\nValidated commit: {sha}\nModel fingerprint: {content_hash}"
        if drafts:
            run(
                "gh",
                "release",
                "edit",
                version,
                "--repo",
                repo,
                "--draft=true",
                "--target",
                sha,
                "--title",
                version,
                "--notes",
                notes,
            )
        else:
            run(
                "gh",
                "release",
                "create",
                version,
                "--repo",
                repo,
                "--draft",
                "--target",
                sha,
                "--title",
                version,
                "--notes",
                notes,
            )
        if publish:
            if run("git", "ls-remote", remote, "refs/heads/main").split()[0] != main_sha:
                raise ValueError("Main advanced before publication; release remains a draft")
            if run("git", "ls-remote", remote, f"refs/heads/{branch}").split()[0] != sha:
                raise ValueError("Release branch advanced before publication")
            draft = json.loads(run("gh", "api", f"repos/{repo}/releases/tags/{version}"))
            if (
                not draft["draft"]
                or draft["target_commitish"] != sha
                or draft["tag_name"] != version
            ):
                raise ValueError("Draft changed before publication; refusing to publish")
            run("gh", "release", "edit", version, "--repo", repo, "--draft=false")
        print(f"{'Published' if publish else 'Prepared draft'} {version} at {sha}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "finish", "verify"])
    parser.add_argument("--upstream")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    if args.command == "verify":
        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        verify_artifacts(root, version)
        return
    if not args.upstream:
        parser.error("--upstream is required for prepare and finish")
    if args.command == "prepare":
        prepare(root, args.upstream)
    else:
        finish(root, args.upstream, args.publish, args.dry_run)


if __name__ == "__main__":
    main()
