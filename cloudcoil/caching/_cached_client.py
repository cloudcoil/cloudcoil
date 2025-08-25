"""Cached client wrappers that use informers for read operations."""

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Optional, TypeVar

from cloudcoil.resources import Resource

if TYPE_CHECKING:
    from cloudcoil.client._api_client import APIClient, AsyncAPIClient

    from ._informer import AsyncInformer
    from ._sync_informer import SyncInformer

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class CachedClient:
    """Sync client wrapper that uses informer cache for read operations."""

    def __init__(
        self,
        client: "APIClient[T]",
        informer: "SyncInformer[T]",
        strict: bool = False,
    ):
        """Initialize cached client.

        Args:
            client: The underlying API client
            informer: The informer providing cached data
            strict: If True, only use cache (never fall back to API)
        """
        self._client = client
        self._informer = informer
        self._strict = strict

    def get(self, name: str, namespace: Optional[str] = None) -> Optional[T]:
        """Get a resource by name.

        Uses cache if available, falls back to API if not strict mode.
        """
        # Try cache first
        cached = self._informer.get(name, namespace)
        if cached is not None:
            logger.debug("Cache hit for %s/%s", namespace or "default", name)
            return cached

        # In strict mode, don't fall back to API
        if self._strict:
            logger.debug("Cache miss for %s/%s (strict mode)", namespace or "default", name)
            return None

        # Fall back to API
        logger.debug("Cache miss for %s/%s, fetching from API", namespace or "default", name)
        return self._client.get(name, namespace)

    def list(
        self,
        namespace: Optional[str] = None,
        all_namespaces: bool = False,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:  # Should be ResourceList[T] but avoiding circular import
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
            # Wrap in ResourceList-like object
            # TODO: Import and use actual ResourceList
            return type("ResourceList", (), {"items": items, "metadata": {}})()

        # In strict mode, return empty if cache not ready
        if self._strict:
            logger.debug("Cache not synced (strict mode)")
            return type("ResourceList", (), {"items": [], "metadata": {}})()

        # Fall back to API
        logger.debug("Cache not synced, fetching from API")
        return self._client.list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            label_selector=label_selector,
            field_selector=field_selector,
            **kwargs,
        )

    def watch(self, **kwargs: Any) -> Iterator[tuple[str, T]]:
        """Watch for changes. Always uses API (cache handles its own watching)."""
        return self._client.watch(**kwargs)

    def create(self, body: T, dry_run: bool = False) -> T:
        """Create a resource. Always uses API."""
        return self._client.create(body, dry_run)

    def update(self, body: T, dry_run: bool = False) -> T:
        """Update a resource. Always uses API."""
        return self._client.update(body, dry_run)

    def update_status(self, body: T, dry_run: bool = False) -> T:
        """Update resource status. Always uses API."""
        return self._client.update_status(body, dry_run)

    def delete(
        self,
        name: str,
        namespace: Optional[str] = None,
        propagation_policy: str = "Background",
        grace_period_seconds: Optional[int] = None,
        dry_run: bool = False,
    ) -> Any:
        """Delete a resource. Always uses API."""
        return self._client.delete(
            name, namespace, propagation_policy, grace_period_seconds, dry_run
        )

    def remove(
        self,
        obj: T,
        propagation_policy: str = "Background",
        grace_period_seconds: Optional[int] = None,
        dry_run: bool = False,
    ) -> Any:
        """Remove a resource. Always uses API."""
        return self._client.remove(obj, propagation_policy, grace_period_seconds, dry_run)

    def delete_all(
        self,
        namespace: Optional[str] = None,
        dry_run: bool = True,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
        propagation_policy: str = "Background",
    ) -> Any:
        """Delete all resources. Always uses API."""
        return self._client.delete_all(
            namespace, dry_run, label_selector, field_selector, propagation_policy
        )

    def wait_for(
        self,
        name: str,
        condition: Any,
        namespace: Optional[str] = None,
        timeout: float = 300,
    ) -> T:
        """Wait for a condition. Always uses API."""
        return self._client.wait_for(name, condition, namespace, timeout)

    def scale(self, body: T, replicas: int) -> T:
        """Scale a resource. Always uses API."""
        return self._client.scale(body, replicas)

    # Delegate all other attributes to the underlying client
    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to the underlying client."""
        return getattr(self._client, name)


class AsyncCachedClient:
    """Async client wrapper that uses informer cache for read operations."""

    def __init__(
        self,
        client: "AsyncAPIClient[T]",
        informer: "AsyncInformer[T]",
        strict: bool = False,
    ):
        """Initialize async cached client.

        Args:
            client: The underlying async API client
            informer: The async informer providing cached data
            strict: If True, only use cache (never fall back to API)
        """
        self._client = client
        self._informer = informer
        self._strict = strict

    async def get(self, name: str, namespace: Optional[str] = None) -> Optional[T]:
        """Get a resource by name.

        Uses cache if available, falls back to API if not strict mode.
        """
        # Try cache first (cache reads are synchronous even in async informer)
        cached = self._informer.get(name, namespace)
        if cached is not None:
            logger.debug("Cache hit for %s/%s", namespace or "default", name)
            return cached

        # In strict mode, don't fall back to API
        if self._strict:
            logger.debug("Cache miss for %s/%s (strict mode)", namespace or "default", name)
            return None

        # Fall back to API
        logger.debug("Cache miss for %s/%s, fetching from API", namespace or "default", name)
        return await self._client.get(name, namespace)

    async def list(
        self,
        namespace: Optional[str] = None,
        all_namespaces: bool = False,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:  # Should be ResourceList[T]
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
            # Wrap in ResourceList-like object
            return type("ResourceList", (), {"items": items, "metadata": {}})()

        # In strict mode, return empty if cache not ready
        if self._strict:
            logger.debug("Cache not synced (strict mode)")
            return type("ResourceList", (), {"items": [], "metadata": {}})()

        # Fall back to API
        logger.debug("Cache not synced, fetching from API")
        return await self._client.list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            label_selector=label_selector,
            field_selector=field_selector,
            **kwargs,
        )

    async def watch(self, **kwargs: Any) -> AsyncIterator[tuple[str, T]]:
        """Watch for changes. Always uses API (cache handles its own watching)."""
        async for event in self._client.watch(**kwargs):
            yield event

    async def create(self, body: T, dry_run: bool = False) -> T:
        """Create a resource. Always uses API."""
        return await self._client.create(body, dry_run)

    async def update(self, body: T, dry_run: bool = False) -> T:
        """Update a resource. Always uses API."""
        return await self._client.update(body, dry_run)

    async def update_status(self, body: T, dry_run: bool = False) -> T:
        """Update resource status. Always uses API."""
        return await self._client.update_status(body, dry_run)

    async def delete(
        self,
        name: str,
        namespace: Optional[str] = None,
        propagation_policy: str = "Background",
        grace_period_seconds: Optional[int] = None,
        dry_run: bool = False,
    ) -> Any:
        """Delete a resource. Always uses API."""
        return await self._client.delete(
            name, namespace, propagation_policy, grace_period_seconds, dry_run
        )

    async def remove(
        self,
        obj: T,
        propagation_policy: str = "Background",
        grace_period_seconds: Optional[int] = None,
        dry_run: bool = False,
    ) -> Any:
        """Remove a resource. Always uses API."""
        return await self._client.remove(obj, propagation_policy, grace_period_seconds, dry_run)

    async def delete_all(
        self,
        namespace: Optional[str] = None,
        dry_run: bool = True,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
        propagation_policy: str = "Background",
    ) -> Any:
        """Delete all resources. Always uses API."""
        return await self._client.delete_all(
            namespace, dry_run, label_selector, field_selector, propagation_policy
        )

    async def wait_for(
        self,
        name: str,
        condition: Any,
        namespace: Optional[str] = None,
        timeout: float = 300,
    ) -> T:
        """Wait for a condition. Always uses API."""
        return await self._client.wait_for(name, condition, namespace, timeout)

    async def scale(self, body: T, replicas: int) -> T:
        """Scale a resource. Always uses API."""
        return await self._client.scale(body, replicas)

    # Delegate all other attributes to the underlying client
    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to the underlying client."""
        return getattr(self._client, name)
