import asyncio
import json
import logging
import random
import threading
import time
from typing import Any, AsyncGenerator, Callable, Generic, Iterator, Literal, Type, TypeVar

import httpx
from pydantic import TypeAdapter

from cloudcoil.apimachinery import Status
from cloudcoil.errors import (
    APIError,
    ResourceAlreadyExists,
    ResourceNotFound,
    WaitTimeout,
    WatchError,
)
from cloudcoil.resources import (
    DEFAULT_PAGE_LIMIT,
    Resource,
    ResourceList,
    WaitPredicate,
    WatchEvent,
)

T = TypeVar("T", bound="Resource")

logger = logging.getLogger(__name__)

_WATCH_TIMEOUT_SECONDS = 300


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
        if not name and not namespace:
            return f"{api_base}/{self.resource}"
        # One of namespace or name exists
        # If name does not exist, then namespace must exist
        if not name:
            if self.namespaced:
                return f"{api_base}/namespaces/{namespace}/{self.resource}"
            return f"{api_base}/{self.resource}"
        # name exists
        if not namespace and self.namespaced:
            raise ValueError("namespace must be provided when name is provided")
        if self.namespaced:
            return f"{api_base}/namespaces/{namespace}/{self.resource}/{name}"
        return f"{api_base}/{self.resource}/{name}"

    def _handle_get_response(self, response: httpx.Response, namespace: str, name: str) -> T:
        if response.status_code == 404:
            raise ResourceNotFound(
                f"Resource kind='{self.kind.gvk().kind}', {namespace=}, {name=} not found"
            )
        return self.kind.model_validate_json(response.content)  # type: ignore

    def _handle_delete_response(
        self, response: httpx.Response, namespace: str, name: str
    ) -> T | Status:
        if response.status_code == 404:
            raise ResourceNotFound(
                f"Resource kind='{self.kind.gvk().kind}', {namespace=}, {name=} not found"
            )
        return TypeAdapter(Status | self.kind).validate_json(response.content)

    def _handle_create_response(self, response: httpx.Response) -> T:
        if response.status_code == 409:
            raise ResourceAlreadyExists(response.json()["details"])
        if not response.is_success:
            raise APIError(response.json())
        return self.kind.model_validate_json(response.content)  # type: ignore

    def _build_watch_params(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        field_selector: str | None = None,
        label_selector: str | None = None,
        resource_version: str | None = None,
        timeout: int = _WATCH_TIMEOUT_SECONDS,
    ) -> tuple[str, dict[str, Any]]:
        namespace = namespace or self.default_namespace
        if all_namespaces:
            namespace = None
        url = self._build_url(namespace=namespace)
        params = {
            "watch": "true",
            "timeoutSeconds": timeout,
            "allowWatchBookmarks": "true",
        }
        if resource_version:
            params["resourceVersion"] = resource_version
        if field_selector:
            params["fieldSelector"] = field_selector
        if label_selector:
            params["labelSelector"] = label_selector
        return url, params

    def _get_backoff_time(self, retry_count: int) -> float:
        """Calculate exponential backoff with jitter."""
        backoff = min(10.0, 0.1 * (2**retry_count))  # Cap at 10 seconds
        jitter = random.uniform(0, 0.1 * backoff)  # 10% jitter
        return backoff + jitter


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
        return self._handle_get_response(response, namespace, name)

    def create(self, body: T, dry_run: bool = False) -> T:
        if not (body.metadata):
            raise ValueError(f"metadata must be set for {body=}")
        namespace = body.namespace or self.default_namespace
        url = self._build_url(namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        response = self._client.post(
            url, json=body.model_dump(mode="json", by_alias=True), params=params
        )
        return self._handle_create_response(response)

    def update(self, body: T, dry_run: bool = False) -> T:
        if not (body.metadata):
            raise ValueError(f"metadata must be set for {body=}")
        namespace = body.namespace or self.default_namespace
        name = body.name
        url = self._build_url(namespace=namespace, name=name)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        response = self._client.put(
            url, json=body.model_dump(mode="json", by_alias=True), params=params
        )
        return self._handle_create_response(response)

    def delete(
        self,
        name: str,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> T | Status:
        namespace = namespace or self.default_namespace
        url = self._build_url(name=name, namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        if propagation_policy:
            params["propagationPolicy"] = propagation_policy.capitalize()
        if grace_period_seconds:
            params["gracePeriodSeconds"] = grace_period_seconds
        response = self._client.delete(url, params=params)
        return self._handle_delete_response(response, namespace, name)

    def remove(
        self,
        body: T,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> T | Status:
        if not (body.metadata and body.metadata.name):
            raise ValueError(f"metadata.name must be set for {body=}")
        namespace = body.metadata.namespace or self.default_namespace
        name = body.metadata.name
        return self.delete(
            name,
            namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    def list(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: None | str = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> ResourceList[T]:
        namespace = namespace or self.default_namespace
        if all_namespaces:
            namespace = None
        url = self._build_url(namespace=namespace)
        params: dict[str, str | int] = {}
        if continue_:
            params["continue"] = continue_
        if field_selector:
            params["fieldSelector"] = field_selector
        if label_selector:
            params["labelSelector"] = label_selector
        if limit:
            params["limit"] = limit
        response = self._client.get(url, params=params)
        if not response.is_success:
            raise APIError(response.json())
        output = ResourceList[self.kind].model_validate_json(response.content)  # type: ignore
        assert output.metadata
        output._next_page_params = {
            "namespace": namespace,
            "all_namespaces": all_namespaces,
            "continue_": output.metadata.continue_,
            "field_selector": field_selector,
            "label_selector": label_selector,
            "limit": limit,
        }
        return output

    def delete_all(  # renamed from delete_collection
        self,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> ResourceList[T]:
        namespace = namespace or self.default_namespace
        url = self._build_url(namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        if propagation_policy:
            params["propagationPolicy"] = propagation_policy.capitalize()
        if grace_period_seconds:
            params["gracePeriodSeconds"] = grace_period_seconds
        if label_selector:
            params["labelSelector"] = label_selector
        if field_selector:
            params["fieldSelector"] = field_selector
        response = self._client.delete(url, params=params)
        if not response.is_success:
            raise APIError(response.json())
        return ResourceList[self.kind].model_validate_json(response.content)  # type: ignore

    def watch(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        field_selector: str | None = None,
        label_selector: str | None = None,
        resource_version: str | None = None,
    ) -> Iterator[tuple[WatchEvent, T]]:
        retry_count = 0
        curr_resource_version = resource_version

        while True:
            try:
                url, params = self._build_watch_params(
                    namespace=namespace,
                    all_namespaces=all_namespaces,
                    field_selector=field_selector,
                    label_selector=label_selector,
                    resource_version=curr_resource_version,
                )

                with self._client.stream(
                    "GET", url, params=params, timeout=_WATCH_TIMEOUT_SECONDS + 5
                ) as response:
                    if response.status_code == 410:  # Gone
                        curr_resource_version = None
                        continue

                    response.raise_for_status()
                    retry_count = 0  # Reset retry counter on successful connection

                    for line in response.iter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        type_ = event["type"]
                        obj = self.kind.model_validate(event["object"])

                        if type_ == "ERROR":
                            if "status" in event["object"]:
                                status = event["object"]["status"]
                                if status == "Failure":
                                    reason = event["object"].get("reason", "")
                                    if reason == "Expired":
                                        curr_resource_version = None
                                        break
                            raise WatchError(f"Watch error: {event}")

                        if obj.metadata and obj.metadata.resource_version:
                            curr_resource_version = obj.metadata.resource_version
                        yield type_, obj

            except (httpx.RequestError, httpx.HTTPStatusError, WatchError) as e:
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code == 410:  # Gone
                        curr_resource_version = None
                        continue
                    if e.response.status_code == 404:  # Not Found
                        raise ResourceNotFound("Watch endpoint not found") from e

                retry_count += 1
                backoff = self._get_backoff_time(retry_count)
                logger.warning(f"Watch connection failed, retrying in {backoff:.1f}s: {e}")
                time.sleep(backoff)

    def wait_for(
        self,
        resource: T,
        predicates: dict[str, WaitPredicate],
        timeout: float | None = None,
    ) -> str:
        class WatchResult:
            def __init__(self) -> None:
                self.predicate_name: str | None = None
                self.error: Exception | None = None

        result = WatchResult()
        stop_event = threading.Event()

        def watch_and_evaluate() -> None:
            try:
                for event_type, obj in self.watch(
                    namespace=resource.namespace,
                    field_selector=f"metadata.name={resource.name}",
                    resource_version=resource.resource_version,
                ):
                    if stop_event.is_set():
                        return

                    for name, predicate in predicates.items():
                        if predicate(event_type, obj):
                            result.predicate_name = name
                            return

            except Exception as e:
                result.error = e

        # Start the watch in a separate thread
        watch_thread = threading.Thread(target=watch_and_evaluate)
        watch_thread.start()

        try:
            # Wait for the thread to complete or timeout
            watch_thread.join(timeout=timeout)

            # Handle timeout case
            if watch_thread.is_alive():
                raise WaitTimeout("Timeout waiting for condition")

            # Handle error case
            if result.error is not None:
                raise result.error

            # Handle unexpected termination
            if result.predicate_name is None:
                raise RuntimeError("Watch ended unexpectedly")

            return result.predicate_name
        finally:
            # Ensure stop_event is set in case we hit an error before setting it
            stop_event.set()


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
    ) -> T | Status:
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
        return self._handle_delete_response(response, namespace, name)

    async def remove(
        self,
        body: T,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> T | Status:
        if not (body.metadata and body.metadata.name):
            raise ValueError(f"metadata.name must be set for {body=}")
        namespace = body.metadata.namespace or self.default_namespace
        name = body.metadata.name
        return await self.delete(
            name,
            namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    async def list(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: None | str = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> ResourceList[T]:
        namespace = namespace or self.default_namespace
        if all_namespaces:
            namespace = None
        url = self._build_url(namespace=namespace)
        params: dict[str, str | int] = {}
        if continue_:
            params["continue"] = continue_
        if field_selector:
            params["fieldSelector"] = field_selector
        if label_selector:
            params["labelSelector"] = label_selector
        if limit:
            params["limit"] = limit
        response = await self._client.get(url, params=params)
        if not response.is_success:
            raise APIError(response.json())
        output = ResourceList[self.kind].model_validate_json(response.content)  # type: ignore
        assert output.metadata
        output._next_page_params = {
            "namespace": namespace,
            "all_namespaces": all_namespaces,
            "continue_": output.metadata.continue_,
            "field_selector": field_selector,
            "label_selector": label_selector,
            "limit": limit,
        }
        return output

    async def delete_all(  # renamed from delete_collection
        self,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> ResourceList[T]:
        namespace = namespace or self.default_namespace
        url = self._build_url(namespace=namespace)
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "All"
        if propagation_policy:
            params["propagationPolicy"] = propagation_policy.capitalize()
        if grace_period_seconds:
            params["gracePeriodSeconds"] = grace_period_seconds
        if label_selector:
            params["labelSelector"] = label_selector
        if field_selector:
            params["fieldSelector"] = field_selector
        response = await self._client.delete(url, params=params)
        if not response.is_success:
            raise APIError(response.json())
        return ResourceList[self.kind].model_validate_json(response.content)  # type: ignore

    async def watch(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        field_selector: str | None = None,
        label_selector: str | None = None,
        resource_version: str | None = None,
    ) -> AsyncGenerator[
        tuple[Literal["ADDED", "MODIFIED", "DELETED", "ERROR", "BOOKMARK"], T], None
    ]:
        retry_count = 0
        curr_resource_version = resource_version

        while True:
            try:
                url, params = self._build_watch_params(
                    namespace=namespace,
                    all_namespaces=all_namespaces,
                    field_selector=field_selector,
                    label_selector=label_selector,
                    resource_version=curr_resource_version,
                )

                async with self._client.stream(
                    "GET", url, params=params, timeout=_WATCH_TIMEOUT_SECONDS + 5
                ) as response:
                    if response.status_code == 410:  # Gone
                        curr_resource_version = None
                        continue

                    response.raise_for_status()
                    retry_count = 0  # Reset retry counter on successful connection

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        type_ = event["type"]
                        obj = self.kind.model_validate(event["object"])

                        if type_ == "ERROR":
                            if "status" in event["object"]:
                                status = event["object"]["status"]
                                if status == "Failure":
                                    reason = event["object"].get("reason", "")
                                    if reason == "Expired":
                                        curr_resource_version = None
                                        break
                            raise WatchError(f"Watch error: {event}")

                        if obj.metadata and obj.metadata.resource_version:
                            curr_resource_version = obj.metadata.resource_version
                        yield type_, obj

            except (httpx.RequestError, httpx.HTTPStatusError, WatchError) as e:
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code == 410:  # Gone
                        curr_resource_version = None
                        continue
                    if e.response.status_code == 404:  # Not Found
                        raise ResourceNotFound("Watch endpoint not found") from e

                retry_count += 1
                backoff = self._get_backoff_time(retry_count)
                logger.warning(f"Watch connection failed, retrying in {backoff:.1f}s: {e}")
                await asyncio.sleep(backoff)

    async def wait_for(
        self,
        resource: T,
        predicates: dict[str, Callable[[WatchEvent, T], bool | None]],
        timeout: float | None = None,
    ) -> str:
        """Async version of wait_for that uses asyncio for timing out the watch."""

        async def watch_and_evaluate() -> str:
            async for event_type, obj in self.watch(
                namespace=resource.namespace,
                field_selector=f"metadata.name={resource.name}",
                resource_version=resource.resource_version,
            ):
                for name, predicate in predicates.items():
                    result = predicate(event_type, obj)
                    if result:
                        return name
            raise RuntimeError("Watch ended unexpectedly")

        try:
            return await asyncio.wait_for(watch_and_evaluate(), timeout=timeout)
        except asyncio.TimeoutError:
            raise WaitTimeout("Timeout waiting for condition")
