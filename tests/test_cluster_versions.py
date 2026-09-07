"""Cluster fixtures must run the requested server version, not a binary's default."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cloudcoil._testing import clusters, plugin


@pytest.fixture(autouse=True)
def isolated_cluster_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDCOIL_K8S_IMAGE", raising=False)
    monkeypatch.delenv("CLUSTER_PROVIDER", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(clusters.BaseCluster, "_download_binary", lambda self, url, path: str(path))


@pytest.mark.parametrize("provider", [clusters.KindCluster, clusters.K3DCluster])
@pytest.mark.parametrize("requested_version", [None, "v1.29.0", "v1.37.0"])
@pytest.mark.parametrize("image", [None, "example.test/custom-node@sha256:abc"])
def test_create_command_selects_requested_image(monkeypatch, provider, requested_version, image):
    run = Mock()
    if provider is clusters.KindCluster:
        run.return_value = SimpleNamespace(stdout=b"")
    else:
        run.side_effect = [subprocess.CalledProcessError(1, "cluster get"), None]
    monkeypatch.setattr(clusters.subprocess, "run", run)
    cluster = provider("version-test", k8s_version=requested_version, k8s_image=image)
    try:
        cluster.create_cluster()
        version = requested_version or (
            clusters.DEFAULT_K8S_VERSION
            if provider is clusters.KindCluster
            else clusters.DEFAULT_K3S_VERSION
        )
        default_image = (
            f"kindest/node:{version}"
            if provider is clusters.KindCluster
            else f"rancher/k3s:{version}-k3s1"
        )
        command = run.call_args_list[1].args[0]
        assert f"--image={image or default_image}" in command
        assert len([arg for arg in command if arg.startswith("--image=")]) == 1
        assert cluster.k8s_version == version
    finally:
        if provider is clusters.KindCluster:
            Path(cluster.get_kubeconfig()).unlink(missing_ok=True)


@pytest.mark.parametrize("provider", ["kind", "k3d"])
@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, None),
        ({"version": "v1.29.0"}, "v1.29.0"),
        ({"k8s_version": "v1.32.1"}, "v1.32.1"),
        ({"version": "v1.29.0", "k8s_version": "v1.32.1"}, "v1.32.1"),
        ({"version": "v1.29.0", "k8s_version": None}, None),
    ],
)
def test_fixture_forwards_version_alias(monkeypatch, provider, settings, expected):
    constructor = Mock()
    constructor.return_value.get_kubeconfig.return_value = "/tmp/config"
    monkeypatch.setattr(plugin, "KindCluster" if provider == "kind" else "K3DCluster", constructor)
    request = SimpleNamespace(
        keywords={
            "configure_test_cluster": SimpleNamespace(
                kwargs={"cluster_name": "version-test", "provider": provider, **settings}
            )
        }
    )
    fixture = plugin.test_cluster.__wrapped__(request)
    assert next(fixture) == "/tmp/config"
    constructor.assert_called_once_with("version-test", True, None, expected, None)
    constructor.return_value.create_cluster.assert_called_once_with()
    with pytest.raises(StopIteration):
        next(fixture)
    constructor.return_value.remove_cluster.assert_called_once_with()


@pytest.mark.parametrize("provider", ["kind", "k3d"])
@pytest.mark.parametrize("marker_image", [None, "example.test/explicit:v1"])
def test_fixture_image_overrides_version_and_environment(monkeypatch, provider, marker_image):
    monkeypatch.setenv("CLUSTER_PROVIDER", provider)
    monkeypatch.setenv("CLOUDCOIL_K8S_IMAGE", "example.test/matrix:v2")
    constructor = Mock()
    monkeypatch.setattr(plugin, "KindCluster" if provider == "kind" else "K3DCluster", constructor)
    request = SimpleNamespace(
        keywords={
            "configure_test_cluster": SimpleNamespace(
                kwargs={
                    "cluster_name": "version-test",
                    "provider": provider,
                    "version": "v1.29.0",
                    "k8s_image": marker_image,
                    "remove": False,
                }
            )
        }
    )
    list(plugin.test_cluster.__wrapped__(request))
    constructor.assert_called_once_with(
        "version-test", False, None, "v1.29.0", marker_image or "example.test/matrix:v2"
    )
    constructor.return_value.remove_cluster.assert_not_called()


@pytest.mark.parametrize("environment_provider", [None, "kind", "k3d"])
def test_unmarked_fixture_uses_environment_provider_and_image(monkeypatch, environment_provider):
    if environment_provider is not None:
        monkeypatch.setenv("CLUSTER_PROVIDER", environment_provider)
    monkeypatch.setenv("CLOUDCOIL_K8S_IMAGE", "example.test/matrix:v2")
    kind, k3d = Mock(), Mock()
    monkeypatch.setattr(plugin, "KindCluster", kind)
    monkeypatch.setattr(plugin, "K3DCluster", k3d)

    list(plugin.test_cluster.__wrapped__(SimpleNamespace(keywords={})))

    constructor, unused = (k3d, kind) if environment_provider == "k3d" else (kind, k3d)
    constructor.assert_called_once()
    assert constructor.call_args.args[1:] == (True, None, None, "example.test/matrix:v2")
    constructor.return_value.create_cluster.assert_called_once_with()
    constructor.return_value.remove_cluster.assert_called_once_with()
    unused.assert_not_called()


@pytest.mark.parametrize("environment_provider", ["kind", "k3d"])
@pytest.mark.parametrize("marker_image", [None, "example.test/explicit:v1"])
def test_marker_provider_override_does_not_inherit_incompatible_image(
    monkeypatch, environment_provider, marker_image
):
    monkeypatch.setenv("CLUSTER_PROVIDER", environment_provider)
    monkeypatch.setenv("CLOUDCOIL_K8S_IMAGE", "example.test/other-provider:v2")
    kind, k3d = Mock(), Mock()
    monkeypatch.setattr(plugin, "KindCluster", kind)
    monkeypatch.setattr(plugin, "K3DCluster", k3d)
    provider = "k3d" if environment_provider == "kind" else "kind"
    request = SimpleNamespace(
        keywords={
            "configure_test_cluster": SimpleNamespace(
                kwargs={
                    "cluster_name": "version-test",
                    "provider": provider,
                    "k8s_image": marker_image,
                }
            )
        }
    )

    list(plugin.test_cluster.__wrapped__(request))

    constructor, unused = (k3d, kind) if provider == "k3d" else (kind, k3d)
    constructor.assert_called_once_with("version-test", True, None, None, marker_image)
    unused.assert_not_called()
