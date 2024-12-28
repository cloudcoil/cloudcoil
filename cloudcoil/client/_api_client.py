from typing import TYPE_CHECKING, Generic, Type, TypeVar

import httpx

if TYPE_CHECKING:
    from cloudcoil.client._resource import Resource

T = TypeVar("T", bound="Resource")


class ResourceNotFound(Exception):
    pass


class _BaseAPIClient(Generic[T]):
    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        default_namespace: str,
        namespaced: bool,
    ) -> None:
        self.api_version = api_version
        self.kind = kind
        self.resource = resource
        self.default_namespace = default_namespace
        self.namespaced = namespaced

    def _build_url(self, namespace: str | None = None, name: str | None = None) -> str:
        api_base = f"/api/{self.api_version}"
        if "/" in self.api_version:
            api_base = f"/apis/{self.api_version}"
        if not (name and namespace):
            return f"{api_base}/{self.resource}"
        if not namespace:
            raise ValueError("namespace must be provided when name is provided")
        if self.namespaced:
            return f"{api_base}/namespaces/{namespace}/{self.resource}/{name}"
        return f"{api_base}/{self.resource}/{name}"

    def _handle_response(self, response: httpx.Response, namespace: str, name: str) -> T:
        if response.status_code == 404:
            raise ResourceNotFound(
                f"Resource kind='{self.kind.__name__}', {namespace=}, {name=} not found"
            )
        return self.kind.model_validate_json(response.content)  # type: ignore


class APIClient(_BaseAPIClient[T]):
    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        default_namespace: str,
        namespaced: bool,
        client: httpx.Client,
    ) -> None:
        super().__init__(api_version, kind, resource, default_namespace, namespaced)
        self._client = client

    def get(self, name: str, namespace: str | None = None) -> T:
        namespace = namespace or self.default_namespace
        url = self._build_url(name=name, namespace=namespace)
        response = self._client.get(url)
        return self._handle_response(response, namespace, name)


class AsyncAPIClient(_BaseAPIClient[T]):
    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        default_namespace: str,
        namespaced: bool,
        client: httpx.AsyncClient,
    ) -> None:
        super().__init__(api_version, kind, resource, default_namespace, namespaced)
        self._client = client

    async def get(self, name: str, namespace: str | None = None) -> T:
        namespace = namespace or self.default_namespace
        url = self._build_url(name=name, namespace=namespace)
        response = await self._client.get(url)
        return self._handle_response(response, namespace, name)
