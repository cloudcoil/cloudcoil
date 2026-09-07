"""Discover upstream releases and update model source configs in a reviewable PR."""

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def version_key(value):
    if not VERSION.fullmatch(value):
        raise ValueError(f"Expected an upstream major.minor.patch version: {value!r}")
    return tuple(map(int, value.split(".")))


def release_versions(releases, prefix):
    result = set()
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release["tag_name"]
        if not tag.startswith(prefix):
            continue
        version = tag[len(prefix) :]
        if VERSION.fullmatch(version):
            result.add(version)
    return sorted(result, key=version_key)


def choose_versions(current, available, policy):
    """Keep explicit Kubernetes minor support; other projects follow latest upstream."""
    if policy == "maintained-minors":
        return [
            max(
                [old, *(v for v in available if version_key(v)[:2] == version_key(old)[:2])],
                key=version_key,
            )
            for old in current
        ]
    if policy != "latest":
        raise ValueError(f"Unknown update policy: {policy}")
    return [max([*current, *available], key=version_key)]


def update_config(text, versions):
    context = yaml.safe_load(text)["default_context"]
    current = ast.literal_eval("[" + context["versions"] + "]")
    for value in [*current, *versions]:
        version_key(value)
    old = max(current, key=version_key)
    new = max(versions, key=version_key)
    # Only change URL values and the version matrix, preserving comments and formatting.
    # Replace every occurrence, including versioned asset names such as keda-X.Y.Z-crds.
    urls = context["crd_urls"]
    changed_urls = re.sub(rf"(?<!\d){re.escape(old)}(?!\d)", new, urls)
    if old != new and urls == changed_urls:
        raise ValueError(f"No version {old} found in input URLs")
    text, count = re.subn(r"(?m)^  crd_urls: .*?$", lambda _: f"  crd_urls: {changed_urls}", text)
    if count != 1:
        raise ValueError("Expected one crd_urls entry")
    value = ", ".join(repr(v) for v in versions)
    text, count = re.subn(r"(?m)^  versions: .*?$", lambda _: f'  versions: "{value}"', text)
    if count != 1:
        raise ValueError("Expected one versions entry")
    return text


def github_releases(repo):
    output = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"],
        text=True,
    )
    return [release for page in json.loads(output) for release in page]


def update_core_requirement(template, versions):
    current = re.search(r"cloudcoil>=(\d+\.\d+\.\d+),<([\d.]+)", template)
    if not current:
        raise ValueError("Missing shared Cloudcoil requirement")
    old, _upper = current.groups()
    # Minor changes may break models and require an intentional migration.
    candidates = [
        v for v in versions if VERSION.fullmatch(v) and version_key(v)[:2] == version_key(old)[:2]
    ]
    latest = max([old, *candidates], key=version_key)
    return (
        re.sub(
            rf"(cloudcoil(?:\[[^\]]+\])?>=){re.escape(old)}(?=,<)",
            lambda match: match[1] + latest,
            template,
        ),
        old,
        latest,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Report available changes without writing"
    )
    args = parser.parse_args()
    registry = json.loads((ROOT / "models/upstreams.json").read_text())
    changes = []
    pending = {}
    for name, source in registry.items():
        path = ROOT / "models" / name / "cookiecutter.yaml"
        text = path.read_text()
        current = ast.literal_eval("[" + yaml.safe_load(text)["default_context"]["versions"] + "]")
        available = release_versions(github_releases(source["repository"]), source["tag_prefix"])
        if not available:
            raise ValueError(f"No upstream releases matched for {name}")
        versions = choose_versions(current, available, source.get("policy", "latest"))
        updated = update_config(text, versions)
        if updated != text:
            pending[path] = updated
            changes.append(f"- {name}: {', '.join(current)} → {', '.join(versions)}")
    with urlopen("https://pypi.org/pypi/cloudcoil/json", timeout=60) as response:
        releases = json.load(response)["releases"]
    published = [
        v for v, files in releases.items() if files and not all(f.get("yanked") for f in files)
    ]
    path = ROOT / "cookiecutter/models-{{ cookiecutter.model_name }}/pyproject.toml"
    updated, old, latest = update_core_requirement(path.read_text(), published)
    if old != latest:
        pending[path] = updated
        changes.append(f"- Cloudcoil minimum: {old} → {latest} (same minor)")
    # Discovery must succeed for every project before changing any files.
    if not args.check:
        for path, content in pending.items():
            path.write_text(content)
    print("\n".join(changes) or "All model versions and Cloudcoil requirements are current.")


if __name__ == "__main__":
    main()
