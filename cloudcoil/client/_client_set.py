import base64
import os
import ssl
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal, Type, TypeVar, overload

import httpx
import yaml

from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.client._context import context
from cloudcoil.client._resource import Resource

T = TypeVar("T", bound=Resource)

DEFAULT_KUBECONFIG = Path.home() / ".kube" / "config"
INCLUSTER_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
INCLUSTER_CERT_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
INCLUSTER_NAMESPACE_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


class ClientSet:
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
            if "current-context" not in kubeconfig_data:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have current-context")
            current_context = kubeconfig_data["current-context"]
            for context_data in kubeconfig_data["contexts"]:
                if context_data["name"] == current_context:
                    break
            else:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have context {current_context}")
            context = context_data["context"]
            for cluster_data in kubeconfig_data["clusters"]:
                if cluster_data["name"] == context["cluster"]:
                    break
            else:
                raise ValueError(
                    f"Kubeconfig {kubeconfig} does not have cluster {context['cluster']}"
                )
            cluster = cluster_data["cluster"]
            for user_data in kubeconfig_data["users"]:
                if user_data["name"] == context["user"]:
                    break
            else:
                raise ValueError(f"Kubeconfig {kubeconfig} does not have user {context['user']}")
            user = user_data["user"]
            self.server = cluster["server"]
            if "certificate-authority" in cluster:
                self.cafile = cluster["certificate-authority"]
            if "certificate-authority-data" in cluster:
                # Write certificate to disk at a temporary location and use it
                cafile = Path(tempdir.name) / "ca.crt"
                cafile.write_bytes(base64.b64decode(cluster["certificate-authority-data"]))
                self.cafile = cafile

            if "namespace" in context:
                self.namespace = context["namespace"]
            if "token" in user:
                self.token = user["token"]
            elif "client-certificate" in user and "client-key" in user:
                self.certfile = user["client-certificate"]
                self.keyfile = user["client-key"]
            elif "client-certificate-data" in user and "client-key-data" in user:
                # Write client certificate and key to disk at a temporary location
                # and use them
                client_cert = Path(tempdir.name) / "client.crt"
                client_cert.write_bytes(base64.b64decode(user["client-certificate-data"]))
                client_key = Path(tempdir.name) / "client.key"
                client_key.write_bytes(base64.b64decode(user["client-key-data"]))
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
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        self.client = httpx.Client(
            verify=ctx, auth=self.auth or None, base_url=self.server, headers=headers
        )
        self.async_client = httpx.AsyncClient(
            verify=ctx, auth=self.auth or None, base_url=self.server
        )
        self._rest_mapping: dict[tuple[str, str], Any] = {}

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
                    self._rest_mapping[(api_version, kind)] = {
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
        if not issubclass(resource, Resource):
            raise ValueError(f"Resource {resource} is not a cloudcoil.Resource")
        key = (api_version, kind) = resource.gvk()
        if key not in self._rest_mapping:
            raise ValueError(
                f"Resource with {api_version=} and {kind=} is not registered with the server"
            )
        if sync:
            return APIClient(
                api_version=api_version,
                kind=resource,
                resource=self._rest_mapping[key]["resource"],
                namespaced=self._rest_mapping[key]["namespaced"],
                default_namespace=self.namespace,
                client=self.client,
            )
        return AsyncAPIClient(
            api_version=api_version,
            kind=resource,
            resource=self._rest_mapping[key]["resource"],
            namespaced=self._rest_mapping[key]["namespaced"],
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
