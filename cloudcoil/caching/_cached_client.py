"""Cached client wrappers that use informers for read operations."""

import logging
from typing import TYPE_CHECKING, Type, TypeVar

import httpx

from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.errors import ResourceNotFound
from cloudcoil.resources import Resource, ResourceList

if TYPE_CHECKING:
    from ._informer import AsyncInformer
    from ._sync_informer import SyncInformer

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class CachedClient(APIClient[T]):
    """Sync client wrapper that uses informer cache for read operations.

    This client extends the base APIClient to use an informer's cache for get/list
    operations, improving performance by avoiding unnecessary API calls.

    Behavioral differences from base client:
    - In strict mode: Cache misses raise ResourceNotFound (same as base client)
    - In non-strict mode: Cache misses fall back to API calls
    - List operations return empty results if cache not synced in strict mode
    """

    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        subresources: list[str],
        default_namespace: str,
        namespaced: bool,
        client: httpx.Client,
        informer: "SyncInformer[T]",
        strict: bool = False,
    ):
        """Initialize cached client.

        Args:
            api_version: API version of the resource
            kind: Resource type class
            resource: Resource name (plural)
            subresources: List of subresource names
            default_namespace: Default namespace for operations
            namespaced: Whether resource is namespaced
            client: The httpx.Client instance
            informer: The informer providing cached data
            strict: If True, only use cache (never fall back to API).
                In strict mode, cache misses raise ResourceNotFound instead of
                falling back to the API, matching base client behavior
        """
        # Initialize parent with all required attributes
        super().__init__(
            api_version=api_version,
            kind=kind,
            resource=resource,
            subresources=subresources,
            default_namespace=default_namespace,
            namespaced=namespaced,
            client=client,
        )

        # Store informer and strict mode
        self._informer = informer
        self._strict = strict

    def get(self, name: str, namespace: str | None = None) -> T:
        """Get a resource by name.

        Uses cache if available, falls back to API if not strict mode.
        """
        # Try cache first
        cached = self._informer.get(name, namespace)
        if cached is not None:
            logger.debug("Cache hit for %s/%s", namespace, name)
            return cached

        # In strict mode, raise error like base client would
        if self._strict:
            logger.debug("Cache miss for %s/%s (strict mode)", namespace, name)
            raise ResourceNotFound(
                f"Resource kind='{self.kind.gvk().kind}', {namespace=}, {name=} not found in cache"
            )

        # Fall back to API using parent's implementation
        logger.debug("Cache miss for %s/%s, fetching from API", namespace, name)
        return super().get(name, namespace)

    def list(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = 100,
    ) -> ResourceList[T]:
        """List resources.

        Uses cache if available and synced, falls back to API if not strict mode.
        """
        # Check if cache is ready
        if self._informer.has_synced():
            logger.debug("Using cache for list operation")
            items = self._informer.list(
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
            )
            # Wrap in ResourceList object - use self.kind like base client does
            result = ResourceList[self.kind](  # type: ignore[valid-type, name-defined]
                items=items,
                metadata=None,
                api_version=f"{self.api_version}",
                kind=f"{self.kind.gvk().kind}List",
            )
            return result

        # In strict mode, return empty list if cache not ready
        if self._strict:
            logger.debug("Cache not synced (strict mode)")
            return ResourceList[self.kind](  # type: ignore[valid-type, name-defined]
                items=[],
                metadata=None,
                api_version=f"{self.api_version}",
                kind=f"{self.kind.gvk().kind}List",
            )

        # Fall back to API using parent's implementation
        logger.debug("Cache not synced, fetching from API")
        return super().list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            continue_=continue_,
            field_selector=field_selector,
            label_selector=label_selector,
            limit=limit,
        )


class AsyncCachedClient(AsyncAPIClient[T]):
    """Async client wrapper that uses informer cache for read operations.

    This client extends the base AsyncAPIClient to use an informer's cache for get/list
    operations, improving performance by avoiding unnecessary API calls.

    Behavioral differences from base client:
    - In strict mode: Cache misses raise ResourceNotFound (same as base client)
    - In non-strict mode: Cache misses fall back to API calls
    - List operations return empty results if cache not synced in strict mode
    """

    def __init__(
        self,
        api_version: str,
        kind: Type[T],
        resource: str,
        subresources: list[str],
        default_namespace: str,
        namespaced: bool,
        client: httpx.AsyncClient,
        informer: "AsyncInformer[T]",
        strict: bool = False,
    ):
        """Initialize async cached client.

        Args:
            api_version: API version of the resource
            kind: Resource type class
            resource: Resource name (plural)
            subresources: List of subresource names
            default_namespace: Default namespace for operations
            namespaced: Whether resource is namespaced
            client: The httpx.AsyncClient instance
            informer: The async informer providing cached data
            strict: If True, only use cache (never fall back to API).
                In strict mode, cache misses raise ResourceNotFound instead of
                falling back to the API, matching base client behavior
        """
        # Initialize parent with all required attributes
        super().__init__(
            api_version=api_version,
            kind=kind,
            resource=resource,
            subresources=subresources,
            default_namespace=default_namespace,
            namespaced=namespaced,
            client=client,
        )

        # Store informer and strict mode
        self._informer = informer
        self._strict = strict

    async def get(self, name: str, namespace: str | None = None) -> T:
        """Get a resource by name.

        Uses cache if available, falls back to API if not strict mode.
        """
        # Try cache first (cache reads are synchronous even in async informer)
        cached = self._informer.get(name, namespace)
        if cached is not None:
            logger.debug("Cache hit for %s/%s", namespace, name)
            return cached

        # In strict mode, raise error like base client would
        if self._strict:
            logger.debug("Cache miss for %s/%s (strict mode)", namespace, name)
            raise ResourceNotFound(
                f"Resource kind='{self.kind.gvk().kind}', {namespace=}, {name=} not found in cache"
            )

        # Fall back to API using parent's implementation
        logger.debug("Cache miss for %s/%s, fetching from API", namespace, name)
        return await super().get(name, namespace)

    async def list(
        self,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: str | None = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = 100,
    ) -> ResourceList[T]:
        """List resources.

        Uses cache if available and synced, falls back to API if not strict mode.
        """
        # Check if cache is ready
        if self._informer.has_synced():
            logger.debug("Using cache for list operation")
            items = self._informer.list(
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
            )
            # Wrap in ResourceList object - use self.kind like base client does
            result = ResourceList[self.kind](  # type: ignore[valid-type, name-defined]
                items=items,
                metadata=None,
                api_version=f"{self.api_version}",
                kind=f"{self.kind.gvk().kind}List",
            )
            return result

        # In strict mode, return empty list if cache not ready
        if self._strict:
            logger.debug("Cache not synced (strict mode)")
            return ResourceList[self.kind](  # type: ignore[valid-type, name-defined]
                items=[],
                metadata=None,
                api_version=f"{self.api_version}",
                kind=f"{self.kind.gvk().kind}List",
            )

        # Fall back to API using parent's implementation
        logger.debug("Cache not synced, fetching from API")
        return await super().list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            continue_=continue_,
            field_selector=field_selector,
            label_selector=label_selector,
            limit=limit,
        )
