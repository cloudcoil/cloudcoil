import random
import string
import tempfile

try:
    import pytest
except ImportError:
    raise ImportError("Please install pytest to enable the testing fixtures")
import platform
import subprocess
from pathlib import Path

import httpx

from cloudcoil.client import ClientSet

DEFAULT_K3D_VERSION = "v5.7.5"
DEFAULT_K8S_VERSION = "v1.31.4"


@pytest.fixture
def test_cluster(request):
    if "configure_test_cluster" in request.keywords:
        paramaters = dict(request.keywords["configure_test_cluster"].kwargs)

    k3d_version = paramaters.get("k3d_version", DEFAULT_K3D_VERSION)
    k8s_version = paramaters.get("k8s_version", DEFAULT_K8S_VERSION)
    k8s_image = paramaters.get("k8s_image", f"rancher/k3s:{k8s_version}-k3s1")
    remove = paramaters.get("remove", True)
    cluster_name = paramaters.get(
        "cluster_name", f"test-cluster-{random.choices(string.ascii_lowercase, k=5)}"
    )
    k3d_binary_path = Path.home() / ".cache" / "cloudcoil" / "k3d" / k3d_version / "k3d"
    if not k3d_binary_path.exists():
        k3d_binary_path.parent.mkdir(parents=True, exist_ok=True)
        system = platform.system().lower()
        machine = platform.machine().lower()
        if machine == "x86_64":
            machine = "amd64"
        elif machine == "aarch64":
            machine = "arm64"

        url = (
            f"https://github.com/k3d-io/k3d/releases/download/{k3d_version}/k3d-{system}-{machine}"
        )
        response = httpx.get(url, follow_redirects=True)
        response.raise_for_status()
        k3d_binary_path.write_bytes(response.content)
        k3d_binary_path.chmod(0o755)
    k3d_binary = str(k3d_binary_path)
    # Create the cluster
    # check if the cluster already exists
    try:
        subprocess.run(
            [k3d_binary, "cluster", "get", cluster_name], check=True, capture_output=True
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            [
                k3d_binary,
                "cluster",
                "create",
                cluster_name,
                f"--image={k8s_image}",
                "--wait",
                "--kubeconfig-update-default=false",
            ],
            check=True,
        )
    # fetch the kubeconfig to a temporary path and yield the path
    with tempfile.NamedTemporaryFile() as kubeconfig_file:
        subprocess.run(
            [k3d_binary, "kubeconfig", "get", cluster_name], check=True, stdout=kubeconfig_file
        )
        yield kubeconfig_file.name
    if remove:
        subprocess.run([k3d_binary, "cluster", "delete", cluster_name], check=True)


@pytest.fixture
def test_clientset(test_cluster):
    yield ClientSet(kubeconfig=test_cluster)
