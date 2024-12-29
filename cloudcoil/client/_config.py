import base64
import os
import platform
import ssl
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal, Type, TypeVar, overload

import httpx
import yaml

from cloudcoil._version import __version__
from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.client._context import context
from cloudcoil.client._resource import GVK, Resource

T = TypeVar("T", bound=Resource)

DEFAULT_KUBECONFIG = Path.home() / ".kube" / "config"
INCLUSTER_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
INCLUSTER_CERT_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
INCLUSTER_NAMESPACE_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


class Config:
    def __init__(
        self,
        kubeconfig: Path | str | None = None,
        server: str | None = None,
        namespace: str | None = None,
        token: str | None = None,
        auth: Callable[[httpx.Request], httpx.Request] | None = None,
        cafile: Path | None = None,
        certfile: Path | None = None,
        keyfile: Path | None = None,
        context: str | None = None,
    ) -> None:
        self.server = None
        self.namespace = "default"
        self.auth = None
        self.cafile = None
        self.certfile = None
        self.keyfile = None
        self.token = None
        tempdir = tempfile.TemporaryDirectory()
        kubeconfig = kubeconfig or os.environ.get("KUBECONFIG")
        if kubeconfig:
            kubeconfig = Path(kubeconfig)
            if not kubeconfig.is_file():
                raise ValueError(f"Kubeconfig {kubeconfig} is not a file")
        else:
            kubeconfig = DEFAULT_KUBECONFIG
        if kubeconfig.is_file():
            kubeconfig_data = yaml.safe_load(kubeconfig.read_text())
            if "clusters" not in kubeconfig_data:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have clusters")
            if "contexts" not in kubeconfig_data:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have contexts")
            if "users" not in kubeconfig_data:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have users")
            if not context and "current-context" not in kubeconfig_data:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have current-context")
            current_context = context or kubeconfig_data["current-context"]
            for data in kubeconfig_data["contexts"]:
                if data["name"] == current_context:
                    break
            else:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have context {current_context}")
            context_data = data["context"]
            for data in kubeconfig_data["clusters"]:
                if data["name"] == context_data["cluster"]:
                    break
            else:
                raise ValueError(
                    f"Kubeconfig {kubeconfig} does not have cluster {context_data['cluster']}"
                )
            cluster_data = data["cluster"]
            for data in kubeconfig_data["users"]:
                if data["name"] == context_data["user"]:
                    break
            else:
                raise ValueError(
                    f"Kubeconfig {kubeconfig} does not have user {context_data['user']}"
                )
            user_data = data["user"]
            self.server = cluster_data["server"]
            if "certificate-authority" in cluster_data:
                self.cafile = cluster_data["certificate-authority"]
            if "certificate-authority-data" in cluster_data:
                # Write certificate to disk at a temporary location and use it
                cafile = Path(tempdir.name) / "ca.crt"
                cafile.write_bytes(base64.b64decode(cluster_data["certificate-authority-data"]))
                self.cafile = cafile

            if "namespace" in context_data:
                self.namespace = context_data["namespace"]
            if "token" in user_data:
                self.token = user_data["token"]
            elif "client-certificate" in user_data and "client-key" in user_data:
                self.certfile = user_data["client-certificate"]
                self.keyfile = user_data["client-key"]
            elif "client-certificate-data" in user_data and "client-key-data" in user_data:
                # Write client certificate and key to disk at a temporary location
                # and use them
                client_cert = Path(tempdir.name) / "client.crt"
                client_cert.write_bytes(base64.b64decode(user_data["client-certificate-data"]))
                client_key = Path(tempdir.name) / "client.key"
                client_key.write_bytes(base64.b64decode(user_data["client-key-data"]))
                self.certfile = client_cert
                self.keyfile = client_key
        elif INCLUSTER_TOKEN_PATH.is_file():
            self.server = "https://kubernetes.default.svc"
            self.namespace = INCLUSTER_NAMESPACE_PATH.read_text()
            self.token = INCLUSTER_TOKEN_PATH.read_text()
            if INCLUSTER_CERT_PATH.is_file():
                self.cafile = INCLUSTER_CERT_PATH
        self.server = server or self.server or "https://localhost:6443"
        self.namespace = namespace or self.namespace
        self.token = token or self.token
        self.auth = auth or self.auth
        self.cafile = cafile or self.cafile
        self.certfile = certfile or self.certfile
        self.keyfile = keyfile or self.keyfile
        ctx = ssl.create_default_context(cafile=self.cafile)
        if self.certfile and self.keyfile:
            ctx.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
        headers = {
            # Add a custom User-Agent to identify the client
            # similar to kubectl
            "User-Agent": f"cloudcoil/{__version__} ({platform.platform()}) python/{platform.python_version()}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.client = httpx.Client(
            verify=ctx, auth=self.auth or None, base_url=self.server, headers=headers
        )
        self.async_client = httpx.AsyncClient(
            verify=ctx, auth=self.auth or None, base_url=self.server
        )
        self._rest_mapping: dict[GVK, Any] = {}

    def _create_rest_mapper(self):
        # Check if version if greater than 1.30
        version_response = self.client.get("/version")
        if version_response.status_code != 200:
            raise ValueError(f"Failed to get version: {version_response.text}")
        version_data = version_response.json()
        major, minor = version_data["major"], version_data["minor"]
        if major == 1 and minor < 30:
            raise ValueError(f"Kubernetes version {major}.{minor} is not supported")

        # Use the discovery client to get the API endpoints
        # and map the gvk to the correct endpoint
        # We will be getting the aggregated discovery information
        api_response = self.client.get(
            "/api",
            headers={
                "Accept": "application/json;v=v2;g=apidiscovery.k8s.io;as=APIGroupDiscoveryList"
            },
        )
        if api_response.status_code != 200:
            raise ValueError(f"Failed to get API: {api_response.text}")
        api_data = api_response.json()
        self._process_api_discovery(api_data)

        apis_response = self.client.get(
            "/apis",
            headers={
                "Accept": "application/json;v=v2;g=apidiscovery.k8s.io;as=APIGroupDiscoveryList"
            },
        )
        if apis_response.status_code != 200:
            raise ValueError(f"Failed to get APIs: {apis_response.text}")
        apis_data = apis_response.json()
        self._process_api_discovery(apis_data)

    def _process_api_discovery(self, api_discovery):
        if not isinstance(api_discovery, dict) or "items" not in api_discovery:
            return

        for api in api_discovery["items"]:
            group = api.get("metadata", {}).get("name", "")
            versions = api.get("versions", [])

            for version_data in versions:
                version = version_data.get("version")
                if not version:
                    continue

                for resource_data in version_data.get("resources", []):
                    kind = resource_data.get("responseKind", {}).get("kind")
                    resource = resource_data.get("resource")
                    scope = resource_data.get("scope")

                    if not all([kind, resource, scope]):
                        continue

                    namespaced = scope == "Namespaced"
                    # construct api_version using group and version
                    api_version = f"{group}/{version}" if group != "" else version
                    self._rest_mapping[GVK(api_version=api_version, kind=kind)] = {
                        "namespaced": namespaced,
                        "resource": resource,
                    }

    # Overload to allow for both sync and async clients
    @overload
    def client_for(self, resource: Type[T], sync: Literal[True] = True) -> APIClient[T]: ...

    @overload
    def client_for(self, resource: Type[T], sync: Literal[False] = False) -> AsyncAPIClient[T]: ...

    def client_for(
        self, resource: Type[T], sync: Literal[False, True] = True
    ) -> APIClient[T] | AsyncAPIClient[T]:
        self.initialize()
        if not issubclass(resource, Resource):
            raise ValueError(f"Resource {resource} is not a cloudcoil.Resource")
        gvk = resource.gvk()
        if gvk not in self._rest_mapping:
            raise ValueError(f"Resource with {gvk=} is not registered with the server")
        if sync:
            return APIClient(
                api_version=gvk.api_version,
                kind=resource,
                resource=self._rest_mapping[gvk]["resource"],
                namespaced=self._rest_mapping[gvk]["namespaced"],
                default_namespace=self.namespace,
                client=self.client,
            )
        return AsyncAPIClient(
            api_version=gvk.api_version,
            kind=resource,
            resource=self._rest_mapping[gvk]["resource"],
            namespaced=self._rest_mapping[gvk]["namespaced"],
            default_namespace=self.namespace,
            client=self.async_client,
        )

    def initialize(self):
        if not self._rest_mapping:
            self._create_rest_mapper()

    def __enter__(self):
        self.initialize()
        context._enter(self)
        return self

    def __exit__(self, *_):
        context._exit()
