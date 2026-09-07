"""Regression tests for model update and publication decisions, without network writes."""

import importlib.util
import json
import tarfile
import tomllib
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "cookiecutter/models-{{ cookiecutter.model_name }}"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load release helper from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


updates = load_module("update_model_versions", ROOT / "tools/update_model_versions.py")
releases = load_module("release_models", TEMPLATE / "tools/release_models.py")


def test_only_final_releases_with_the_correct_prefix():
    assert updates.release_versions(
        [
            {"tag_name": "v1.2.9"},
            {"tag_name": "v1.2.10"},
            {"tag_name": "v2.0.0", "prerelease": True},
            {"tag_name": "v3.0.0", "draft": True},
            {"tag_name": "v4.0.0-rc.1"},
            {"tag_name": "chart-v5.0.0"},
        ],
        "v",
    ) == ["1.2.9", "1.2.10"]


def test_kubernetes_keeps_explicit_supported_minors_and_does_not_downgrade():
    assert updates.choose_versions(
        ["1.34.11", "1.35.8", "1.36.4", "1.37.0"],
        ["1.34.12", "1.35.2", "1.36.5", "1.37.1", "1.38.0"],
        "maintained-minors",
    ) == ["1.34.12", "1.35.8", "1.36.5", "1.37.1"]


def test_same_minor_core_updates_change_both_requirements():
    source = '"cloudcoil>=0.7.1,<0.8"\n"cloudcoil[codegen,test]>=0.7.1,<0.8"'
    updated, old, new = updates.update_core_requirement(source, ["0.7.2", "0.8.0", "0.7.3rc1"])
    assert (old, new) == ("0.7.1", "0.7.2")
    assert updated.count(">=0.7.2,<0.8") == 2


@pytest.mark.parametrize("name", sorted(json.loads((ROOT / "models/upstreams.json").read_text())))
def test_source_url_update_covers_each_integration(name):
    source = (ROOT / "models" / name / "cookiecutter.yaml").read_text()
    updated = updates.update_config(source, ["99.98.97"])
    context = yaml.safe_load(updated)["default_context"]
    assert context["versions"] == "'99.98.97'"
    assert all(
        "99.98.97" in url for url in context["crd_urls"].split(",") if url.startswith("https://")
    )
    if name == "keda":
        assert "/v99.98.97/keda-99.98.97-crds.yaml" in context["crd_urls"]
    if name == "kubernetes":
        assert "end of life" in updated


def test_packaging_revisions_use_numeric_order_and_exact_upstream():
    assert (
        releases.next_version("1.2.3", ["1.2.3.9", "1.2.3.10", "1.2.30.99", "1.2.3.11rc1"])
        == "1.2.3.11"
    )
    assert releases.next_version("2.0.0", []) == "2.0.0.0"


def test_bump_only_changes_project_version():
    text = '[project]\nname = "model"\nversion = "0.0.0"\n[tool.mypy]\npython_version = "3.14"\n[tool.other]\nversion = "keep"\n'
    result = tomllib.loads(releases.set_project_version(text, "1.2.3.4"))
    assert result["project"]["version"] == "1.2.3.4"
    assert result["tool"] == {"mypy": {"python_version": "3.14"}, "other": {"version": "keep"}}


@pytest.mark.parametrize("version", ["1.2", "1.2.3.4", "1.2.3rc1", "1.2.3;echo bad", "01.2.3"])
def test_invalid_upstream_version_rejected(version):
    with pytest.raises(ValueError):
        releases.version_key(version)


@pytest.fixture
def package(tmp_path):
    (tmp_path / "pyproject.toml").write_text("""[project]
name = "cloudcoil.models.sample"
version = "1.2.3.0"
dependencies = ["cloudcoil>=0.7.1,<0.8"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
only-include = ["cloudcoil"]
""")
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "cloudcoil"\nversion = "0.7.1"\n')
    nested = tmp_path / "cloudcoil/models/sample/build"
    nested.mkdir(parents=True)
    (nested / "v1.py").write_text("VALUE = 1\n")
    (nested.parent / "_lookup.py").write_text("LOOKUP = {}\n")
    (nested.parent / "py.typed").touch()
    return tmp_path


def test_fingerprint_ignores_packaging_bumps_but_detects_runtime_changes(package):
    before = releases.fingerprint(package)
    path = package / "pyproject.toml"
    path.write_text(releases.set_project_version(path.read_text(), "1.2.3.12"))
    (package / "uv.lock").write_text("# tooling-only lock change\n")
    assert releases.fingerprint(package) == before
    path.write_text(path.read_text().replace(">=0.7.1", ">=0.7.2"))
    assert releases.fingerprint(package) != before
    before = releases.fingerprint(package)
    (package / "cloudcoil/models/sample/build/v1.py").write_text("VALUE = 2\n")
    assert releases.fingerprint(package) != before


def make_artifacts(package, omit=None, version="1.2.3.0"):
    (package / "dist").mkdir(exist_ok=True)
    files = [p for p in (package / "cloudcoil").rglob("*") if p.is_file()]
    with zipfile.ZipFile(package / "dist/sample.whl", "w") as wheel:
        for path in files:
            if str(path.relative_to(package)) != omit:
                wheel.write(path, str(path.relative_to(package)))
        wheel.writestr(
            "sample.dist-info/METADATA",
            f"Name: cloudcoil-models-sample\nVersion: {version}\nRequires-Dist: cloudcoil<0.8,>=0.7.1\n",
        )
    with tarfile.open(package / "dist/sample.tar.gz", "w:gz") as sdist:
        for path in files:
            info = tarfile.TarInfo("sample/" + str(path.relative_to(package)))
            info.size = path.stat().st_size
            sdist.addfile(info, BytesIO(path.read_bytes()))


def test_artifact_checks_accept_matching_wheel_and_sdist(package):
    make_artifacts(package)
    releases.verify_artifacts(package, "1.2.3.0")


def test_artifact_checks_catch_kpack_nested_build_regression(package):
    make_artifacts(package, omit="cloudcoil/models/sample/build/v1.py")
    with pytest.raises(ValueError, match="omits generated"):
        releases.verify_artifacts(package, "1.2.3.0")


def test_artifact_checks_reject_wrong_version(package):
    make_artifacts(package, version="0.0.0")
    with pytest.raises(ValueError, match="identity"):
        releases.verify_artifacts(package, "1.2.3.0")


def test_prepare_keeps_local_schemas_and_versions_keda_asset_names(tmp_path):
    (tmp_path / "model-release.json").write_text(json.dumps({"versions": "'2.19.0', '2.20.2'"}))
    (tmp_path / "pyproject.toml").write_text("""[project]
version = "0.0.0"
[[tool.cloudcoil.codegen.models]]
input = ["https://github.com/kedacore/keda/releases/download/v2.20.2/keda-2.20.2-crds.yaml", "schemas/local.json"]
""")
    releases.prepare(tmp_path, "2.19.0")
    config = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert config["project"]["version"] == "2.19.0.0"
    assert config["tool"]["cloudcoil"]["codegen"]["models"][0]["input"] == [
        "https://github.com/kedacore/keda/releases/download/v2.19.0/keda-2.19.0-crds.yaml",
        "schemas/local.json",
    ]
    with pytest.raises(ValueError, match="Unsupported"):
        releases.prepare(tmp_path, "2.18.0")


@pytest.fixture
def release_environment(package, monkeypatch):
    """Exercise staging against a fake remote, with real local artifacts and metadata."""
    import shutil
    import subprocess

    calls = []
    state = {
        "main": "a" * 40,
        "releases": [],
        "tags": "",
        "published": set(),
        "previous": {},
        "diff": 1,
        "draft_sha": "b" * 40,
    }
    monkeypatch.setenv("GITHUB_REPOSITORY", "cloudcoil/models-sample")
    monkeypatch.setattr(releases, "release_list", lambda repo: state["releases"])
    monkeypatch.setattr(releases, "pypi_versions", lambda name: state["published"])
    monkeypatch.setattr(releases, "read_provenance", lambda root, tag: state["previous"])
    monkeypatch.setattr(
        releases.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, state["diff"] if args[0][1] == "diff" else 1
        ),
    )

    def run(*args, cwd=None):
        calls.append(args)
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return "a" * 40 if cwd == package else "b" * 40
        if args[:2] == ("git", "ls-remote"):
            sha = state["main"] if args[-1] == "refs/heads/main" else "b" * 40
            return sha + "\t" + args[-1]
        if args[:3] == ("git", "tag", "--list"):
            return state["tags"]
        if args[:2] == ("uv", "build"):
            version = tomllib.loads((package / "pyproject.toml").read_text())["project"]["version"]
            make_artifacts(package, version=version)
            for artifact in (package / "dist").iterdir():
                shutil.move(artifact, Path(args[-1]) / artifact.name)
            (package / "dist").rmdir()
        if args[:2] == ("git", "ls-files"):
            return "\n".join(
                str(p.relative_to(package))
                for p in package.rglob("*")
                if p.is_file() and "dist" not in p.parts
            )
        if args[:2] == ("gh", "api"):
            return json.dumps(
                {
                    "draft": True,
                    "tag_name": args[-1].split("/")[-1],
                    "target_commitish": state["draft_sha"],
                }
            )
        return ""

    monkeypatch.setattr(releases, "run", run)
    return state, calls


def test_dry_run_builds_without_writes(package, release_environment):
    state, calls = release_environment
    state["published"] = {"1.2.3.9", "1.2.3.10"}
    releases.finish(package, "1.2.3", publish=True, dry_run=True)
    assert (package / "dist/sample.whl").exists()
    assert (
        tomllib.loads((package / "pyproject.toml").read_text())["project"]["version"] == "1.2.3.11"
    )
    assert not any(c[:2] == ("git", "push") or c[:2] == ("gh", "release") for c in calls)


def test_unchanged_release_does_not_allocate_or_build(package, release_environment):
    state, calls = release_environment
    state["releases"] = [{"tag_name": "1.2.3.0", "draft": False}]
    state["previous"] = {"fingerprint": releases.fingerprint(package)}
    releases.finish(package, "1.2.3", publish=True)
    assert not any(c[:2] in [("uv", "build"), ("git", "push"), ("gh", "release")] for c in calls)


def test_advanced_main_never_pushes_or_publishes(package, release_environment):
    state, calls = release_environment
    state["main"] = "c" * 40
    with pytest.raises(ValueError, match="Main advanced"):
        releases.finish(package, "1.2.3", publish=True)
    assert not any(c[:2] in [("git", "push"), ("gh", "release")] for c in calls)


def test_existing_draft_is_reused_and_pinned_to_validated_commit(package, release_environment):
    state, calls = release_environment
    state["releases"] = [{"tag_name": "1.2.3.0", "draft": True}]
    releases.finish(package, "1.2.3")
    edits = [c for c in calls if c[:3] == ("gh", "release", "edit")]
    assert len(edits) == 1
    assert edits[0][3] == "1.2.3.0"
    assert edits[0][edits[0].index("--target") + 1] == "b" * 40
    assert "--draft=true" in edits[0]
    assert not any("--force" in c for c in calls)


def test_retry_of_identical_draft_can_publish_without_an_empty_commit(package, release_environment):
    state, calls = release_environment
    state["diff"] = 0
    state["releases"] = [{"tag_name": "1.2.3.0", "draft": True}]
    releases.finish(package, "1.2.3", publish=True)
    assert not any(c[:2] == ("git", "commit") for c in calls)
    assert any("--draft=false" in c for c in calls)


def test_draft_target_change_stops_publication(package, release_environment):
    state, calls = release_environment
    state["draft_sha"] = "d" * 40
    with pytest.raises(ValueError, match="Draft changed"):
        releases.finish(package, "1.2.3", publish=True)
    assert not any("--draft=false" in c for c in calls)


def test_ignored_type_marker_stops_staging(package, release_environment, monkeypatch):
    _, calls = release_environment
    original = releases.run

    def omit_type_marker(*args, cwd=None):
        result = original(*args, cwd=cwd)
        if args[:2] == ("git", "ls-files"):
            return "\n".join(path for path in result.splitlines() if not path.endswith("py.typed"))
        return result

    monkeypatch.setattr(releases, "run", omit_type_marker)
    with pytest.raises(ValueError, match="Git ignore rules hide generated"):
        releases.finish(package, "1.2.3", publish=True)
    assert not any(c[:2] in [("git", "push"), ("gh", "release")] for c in calls)
