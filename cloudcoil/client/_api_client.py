from typing import Any, Generic, Literal, Type, TypeVar

import httpx

from cloudcoil._decorators import async_to_sync
from cloudcoil.client._resource import Resource
from cloudcoil.client.errors import APIError, ResourceAlreadyExists, ResourceNotFound

T = TypeVar("T", bound="Resource")


class AsyncAPIClient(Generic[T]):
    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        default_namespace: str,
        namespaced: bool,
        client: httpx.AsyncClient,
    ) -> None:
        self.api_version = api_version
        self.kind = kind
        self.resource = resource
        self.default_namespace = default_namespace
        self.namespaced = namespaced
        self._client = client

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

    def _handle_get_response(self, response: httpx.Response, namespace: str, name: str) -> T:
        if response.status_code == 404:
            raise ResourceNotFound(
                f"Resource kind='{self.kind.__name__}', {namespace=}, {name=} not found"
            )
        return self.kind.model_validate_json(response.content)  # type: ignore

    def _handle_create_response(self, response: httpx.Response) -> T:
        if response.status_code == 409:
            raise ResourceAlreadyExists(response.json()["details"])
        if not response.is_success:
            raise APIError(response.json())
        return self.kind.model_validate_json(response.content)  # type: ignore

    async def get(self, name: str, namespace: str | None = None) -> T:
        namespace = namespace or self.default_namespace
        url = self._build_url(name=name, namespace=namespace)
        response = await self._client.get(url)
        return self._handle_get_response(response, namespace, name)

    async def create(self, body: T, dry_run: bool = False) -> T:
        if not (body.metadata):
            raise ValueError(f"metadata.name must be set for {body=}")
        namespace = body.namespace or self.default_namespace
        url = self._build_url(namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        response = await self._client.post(
            url, json=body.model_dump(mode="json", by_alias=True), params=params
        )
        return self._handle_create_response(response)

    async def update(self, body: T, dry_run: bool = False) -> T:
        if not (body.metadata):
            raise ValueError(f"metadata must be set for {body=}")
        namespace = body.namespace or self.default_namespace
        name = body.name
        url = self._build_url(namespace=namespace, name=name)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        response = await self._client.put(
            url, json=body.model_dump(mode="json", by_alias=True), params=params
        )
        return self._handle_create_response(response)

    async def delete(
        self,
        name: str,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> T:
        namespace = namespace or self.default_namespace
        url = self._build_url(name=name, namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        if propagation_policy:
            params["propagationPolicy"] = propagation_policy.capitalize()
        if grace_period_seconds:
            params["gracePeriodSeconds"] = grace_period_seconds
        response = await self._client.delete(url, params=params)
        return self._handle_get_response(response, namespace, name)


class APIClient(AsyncAPIClient[T]):
    @async_to_sync(AsyncAPIClient[T].get)
    def get(*args, **kwargs):
        pass

    @async_to_sync(AsyncAPIClient[T].create)
    def create(*args, **kwargs):
        pass

    @async_to_sync(AsyncAPIClient[T].update)
    def update(*args, **kwargs):
        pass

    @async_to_sync(AsyncAPIClient[T].delete)
    def delete(*args, **kwargs):
        pass
