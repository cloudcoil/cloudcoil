import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

DEFAULT_K3D_VERSION = "v5.7.5"
DEFAULT_K8S_VERSION = "v1.31.4"
DEFAULT_KIND_VERSION = "v0.20.0"


@runtime_checkable
class K8sClusterProvider(Protocol):
    def create_cluster(self) -> None: ...
    def get_kubeconfig(self) -> str: ...
    def remove_cluster(self) -> None: ...


class BaseCluster:
    def __init__(self, cluster_name: str, remove: bool):
        self.cluster_name = cluster_name
        self.remove = remove

    def _compute_system_machine(self) -> tuple[str, str]:
        system = platform.system().lower()
        machine = platform.machine().lower()
        if machine == "x86_64":
            machine = "amd64"
        elif machine == "aarch64":
            machine = "arm64"
        return system, machine

    def _download_binary(self, url: str, binary_path: Path) -> str:
        if not binary_path.exists():
            binary_path.parent.mkdir(parents=True, exist_ok=True)
            response = httpx.get(url, follow_redirects=True)
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(response.content)
                tmp_path = Path(tmp_file.name)
            tmp_path.chmod(0o755)
            try:
                tmp_path.rename(binary_path)
            except OSError:
                if not binary_path.exists():
                    shutil.move(str(tmp_path), str(binary_path))
                else:
                    tmp_path.unlink()
        return str(binary_path)


class K3DCluster(BaseCluster):
    def __init__(
        self,
        cluster_name: str,
        remove: bool = True,
        k3d_version: str | None = DEFAULT_K3D_VERSION,
        k8s_version: str | None = DEFAULT_K8S_VERSION,
        k8s_image: str | None = None,
    ):
        super().__init__(cluster_name, remove)
        self.k3d_version = k3d_version or DEFAULT_K3D_VERSION
        self.k8s_version = k8s_version or DEFAULT_K8S_VERSION
        self.k8s_image = k8s_image or f"rancher/k3s:{self.k8s_version}-k3s1"
        self.binary_path = Path.home() / ".cache" / "cloudcoil" / "k3d" / self.k3d_version / "k3d"
        system, machine = self._compute_system_machine()
        url = f"https://github.com/k3d-io/k3d/releases/download/{self.k3d_version}/k3d-{system}-{machine}"
        self.binary = self._download_binary(url, self.binary_path)

    def create_cluster(self) -> None:
        try:
            subprocess.run(
                [self.binary, "cluster", "get", self.cluster_name],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            command = [
                self.binary,
                "cluster",
                "create",
                self.cluster_name,
                "--wait",
                "--kubeconfig-update-default=false",
                f"--image={self.k8s_image}",
            ]
            subprocess.run(command, check=True)

    def get_kubeconfig(self) -> str:
        kubeconfig_file = tempfile.NamedTemporaryFile(delete=False)
        subprocess.run(
            [self.binary, "kubeconfig", "get", self.cluster_name],
            check=True,
            stdout=kubeconfig_file,
        )
        kubeconfig_file.close()
        return kubeconfig_file.name

    def remove_cluster(self) -> None:
        subprocess.run([self.binary, "cluster", "delete", self.cluster_name], check=True)


class KindCluster(BaseCluster):
    def __init__(
        self,
        cluster_name: str,
        remove: bool = True,
        kind_version: str | None = None,
        k8s_version: str | None = None,
        k8s_image: str | None = None,
    ):
        super().__init__(cluster_name, remove)
        self.kind_version = kind_version or DEFAULT_KIND_VERSION
        self.k8s_version = k8s_version or DEFAULT_K8S_VERSION
        self.k8s_image = k8s_image
        self.binary_path = (
            Path.home() / ".cache" / "cloudcoil" / "kind" / self.kind_version / "kind"
        )
        system, machine = self._compute_system_machine()
        url = f"https://kind.sigs.k8s.io/dl/{self.kind_version}/kind-{system}-{machine}"
        self.binary = self._download_binary(url, self.binary_path)
        self._kubeconfig = tempfile.NamedTemporaryFile(delete=False).name

    def create_cluster(self) -> None:
        clusters = (
            subprocess.run(
                [self.binary, "get", "clusters"],
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .split("\n")
        )
        if self.cluster_name not in clusters:
            command = [
                self.binary,
                "create",
                "cluster",
                f"--name={self.cluster_name}",
                f"--kubeconfig={self._kubeconfig}",
                "--wait=5m",
            ]
            if self.k8s_image:
                command.append(f"--image={self.k8s_image}")
            subprocess.run(command, check=True)
        else:
            subprocess.run(
                [
                    self.binary,
                    "export",
                    "kubeconfig",
                    f"--name={self.cluster_name}",
                    f"--kubeconfig={self._kubeconfig}",
                ],
                check=True,
            )

    def get_kubeconfig(self) -> str:
        return self._kubeconfig

    def remove_cluster(self) -> None:
        subprocess.run(
            [self.binary, "delete", "cluster", f"--name={self.cluster_name}"], check=True
        )
        try:
            Path(self._kubeconfig).unlink()
        except FileNotFoundError:
            pass
