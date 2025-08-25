"""SharedInformerFactory for managing informer lifecycle."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, TypeVar, Union

from cloudcoil.resources import Resource

from ._informer import AsyncInformer
from ._sync_informer import SyncInformer
from ._types import Cache, InformerOptions

if TYPE_CHECKING:
    from cloudcoil.client._config import Config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class SharedInformerFactory:
    """Factory for creating and managing shared informers."""

    def __init__(self, config: "Config", cache_config: Cache):
        """Initialize the informer factory.

        Args:
            config: The CloudCoil config instance
            cache_config: Cache configuration
        """
        self._config = config
        self._cache_config = cache_config
        self._async_informers: Dict[str, AsyncInformer[Any]] = {}
        self._sync_informers: Dict[str, SyncInformer[Any]] = {}
        self._started = False
        self._start_tasks: List[asyncio.Task[None]] = []

    def get_informer(
        self,
        resource_type: Type[T],
        sync: bool = False,
        namespace: Optional[str] = None,
    ) -> Optional[Union[AsyncInformer[T], SyncInformer[T]]]:
        """Get informer for a specific resource type.

        Args:
            resource_type: The resource type to get informer for
            sync: Whether to return sync informer
            namespace: Optional namespace to scope informer to

        Returns:
            The informer instance, or None if caching is disabled for this resource
        """
        if not self._cache_config.should_cache(resource_type):
            return None

        if sync:
            return self.get_or_create_sync(resource_type, namespace)
        else:
            return self.get_or_create_async(resource_type, namespace)

    def get_or_create_async(
        self,
        resource_type: Type[T],
        namespace: Optional[str] = None,
        _skip_auto_start: bool = False,
    ) -> AsyncInformer[T]:
        """Get existing or create new async informer for resource type.

        Args:
            resource_type: The resource type
            namespace: Optional namespace to scope to
            _skip_auto_start: Skip automatic starting when factory is already started

        Returns:
            The async informer instance
        """
        # Create cache key based on resource type and namespace
        key = self._make_key(resource_type, namespace)

        if key not in self._async_informers:
            # Check if this resource should be cached
            if not self._cache_config.should_cache(resource_type):
                raise ValueError(f"Resource type {resource_type} is not configured for caching")

            # Create new async informer
            informer = self._create_async_informer(resource_type, namespace)
            self._async_informers[key] = informer

            # Start if factory is already started (unless explicitly skipped)
            if self._started and not _skip_auto_start:
                task = asyncio.create_task(informer._start())
                self._start_tasks.append(task)
                # Clean up completed tasks
                self._start_tasks = [t for t in self._start_tasks if not t.done()]

        return self._async_informers[key]  # type: ignore[return-value]

    def get_or_create_sync(
        self,
        resource_type: Type[T],
        namespace: Optional[str] = None,
        _skip_auto_start: bool = False,
    ) -> SyncInformer[T]:
        """Get existing or create new sync informer for resource type.

        Args:
            resource_type: The resource type
            namespace: Optional namespace to scope to
            _skip_auto_start: Skip automatic starting when factory is already started

        Returns:
            The sync informer instance
        """
        # Create cache key based on resource type and namespace
        key = self._make_key(resource_type, namespace)

        if key not in self._sync_informers:
            # Check if this resource should be cached
            if not self._cache_config.should_cache(resource_type):
                raise ValueError(f"Resource type {resource_type} is not configured for caching")

            # Create new sync informer
            informer = self._create_sync_informer(resource_type, namespace)
            self._sync_informers[key] = informer

            # Start if factory is already started (unless explicitly skipped)
            if self._started and not _skip_auto_start:
                informer._start()

        return self._sync_informers[key]  # type: ignore[return-value]

    def _make_key(self, resource_type: Type[Resource], namespace: Optional[str]) -> str:
        """Create cache key for resource type and namespace."""
        key = f"{resource_type.__module__}.{resource_type.__name__}"
        if namespace:
            key += f":{namespace}"
        return key

    def _create_async_informer(
        self,
        resource_type: Type[T],
        namespace: Optional[str],
    ) -> AsyncInformer[T]:
        """Create new async informer for resource type.

        Args:
            resource_type: The resource type
            namespace: Optional namespace to scope to

        Returns:
            New async informer instance
        """
        # Get async API client for this resource type (skip cache to avoid recursion)
        client = self._config.client_for(resource_type, sync=False, _skip_cache=True)

        # Create informer options
        options = self._create_options(resource_type, namespace)

        logger.debug(
            "Creating async informer for %s (namespace=%s)",
            resource_type.__name__,
            namespace or "all",
        )

        return AsyncInformer(client, options)

    def _create_sync_informer(
        self,
        resource_type: Type[T],
        namespace: Optional[str],
    ) -> SyncInformer[T]:
        """Create new sync informer for resource type.

        Args:
            resource_type: The resource type
            namespace: Optional namespace to scope to

        Returns:
            New sync informer instance
        """
        # Get sync API client for this resource type
        client = self._config.client_for(resource_type, sync=True, _skip_cache=True)

        # Create informer options
        options = self._create_options(resource_type, namespace)

        logger.debug(
            "Creating sync informer for %s (namespace=%s)",
            resource_type.__name__,
            namespace or "all",
        )

        return SyncInformer(client, options)

    def _create_options(
        self,
        resource_type: Type[Resource],
        namespace: Optional[str],
    ) -> InformerOptions:
        """Create informer options for resource type.

        Args:
            resource_type: The resource type
            namespace: Optional namespace

        Returns:
            Informer options
        """
        # Start with global config
        effective_namespace = namespace or self._get_effective_namespace(resource_type)
        options = InformerOptions(
            resync_period=self._cache_config.resync_period,
            namespace=effective_namespace,
            all_namespaces=effective_namespace
            is None,  # Watch all namespaces if no specific namespace
            label_selector=self._cache_config.label_selector,
            field_selector=self._cache_config.field_selector,
        )

        # Check for per-resource overrides
        if self._cache_config.per_resource and resource_type in self._cache_config.per_resource:
            resource_config = self._cache_config.per_resource[resource_type]
            if resource_config:
                if resource_config.resync_period is not None:
                    options.resync_period = resource_config.resync_period
                if resource_config.label_selector:
                    options.label_selector = resource_config.label_selector
                if resource_config.field_selector:
                    options.field_selector = resource_config.field_selector

        return options

    def _get_effective_namespace(self, resource_type: Type[Resource]) -> Optional[str]:
        """Get effective namespace for resource type.

        Args:
            resource_type: The resource type

        Returns:
            Namespace to use, or None for cluster-scoped
        """
        # Check if resource is namespaced
        gvk = resource_type.gvk()
        if gvk not in self._config._rest_mapping:
            logger.warning("Resource %s not found in REST mapping", gvk)
            return None

        rest_info = self._config._rest_mapping[gvk]
        if not rest_info.get("namespaced", False):
            # Cluster-scoped resource
            return None

        # Use namespace from cache config or config default
        if self._cache_config.namespaces:
            # If specific namespaces configured, this would need more complex logic
            # For now, just use the first one or None for all
            return None  # Watch all namespaces

        return self._config.namespace if self._config.namespace != "default" else None

    # Async methods (CloudCoil async_ prefix pattern)
    async def async_start(self) -> None:
        """Start all informers asynchronously."""
        if self._started:
            logger.debug("Informer factory already started")
            return

        logger.info("Starting async informer factory")
        self._started = True

        # Pre-create informers for configured resources
        if self._cache_config.resources:
            for resource_type in self._cache_config.resources:
                logger.debug("Pre-creating informer for %s", resource_type.__name__)
                # Create informer but skip auto-start since we'll start them all in batch
                self.get_or_create_async(resource_type, None, _skip_auto_start=True)

        # Start all existing async informers
        start_tasks = []
        for informer in self._async_informers.values():
            start_tasks.append(informer._start())

        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)

        logger.info("Async informer factory started with %d informers", len(self._async_informers))

    async def async_stop(self) -> None:
        """Stop all informers asynchronously."""
        if not self._started:
            return

        logger.info("Stopping async informer factory")
        self._started = False

        # Stop all async informers
        stop_tasks = []
        for informer in self._async_informers.values():
            stop_tasks.append(informer._stop())

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        logger.info("Async informer factory stopped")

    async def async_wait_for_sync(self, timeout: float = 30.0) -> bool:
        """Wait for all async informers to sync.

        Args:
            timeout: Maximum time to wait

        Returns:
            True if all synced within timeout, False otherwise
        """
        if not self._async_informers:
            return True

        # Wait for all async informers to sync
        sync_tasks = []
        for informer in self._async_informers.values():
            sync_tasks.append(informer._wait_for_sync(timeout))

        results = await asyncio.gather(*sync_tasks, return_exceptions=True)

        # Check if all succeeded
        for result in results:
            if isinstance(result, Exception) or not result:
                return False

        return True

    # Sync methods (verb-based naming)
    def start(self) -> None:
        """Start all informers synchronously."""
        if self._started:
            logger.debug("Informer factory already started")
            return

        logger.info("Starting sync informer factory")
        self._started = True

        # Pre-create informers for configured resources
        if self._cache_config.resources:
            for resource_type in self._cache_config.resources:
                logger.debug("Pre-creating sync informer for %s", resource_type.__name__)
                # Create informer but skip auto-start since we'll start them all in batch
                self.get_or_create_sync(resource_type, None, _skip_auto_start=True)

        # Start all existing sync informers
        for informer in self._sync_informers.values():
            informer._start()

        logger.info("Sync informer factory started with %d informers", len(self._sync_informers))

    def stop(self) -> None:
        """Stop all informers synchronously."""
        if not self._started:
            return

        logger.info("Stopping sync informer factory")
        self._started = False

        # Stop all sync informers
        for informer in self._sync_informers.values():
            informer._stop()

        logger.info("Sync informer factory stopped")

    def wait_for_sync(self, timeout: float = 30.0) -> bool:
        """Wait for all sync informers to sync.

        Args:
            timeout: Maximum time to wait

        Returns:
            True if all synced within timeout, False otherwise
        """
        if not self._sync_informers:
            return True

        # Wait for all sync informers to sync (with timeout per informer)
        start_time = time.time()
        for informer in self._sync_informers.values():
            remaining_timeout = max(0, timeout - (time.time() - start_time))
            if not informer._wait_for_sync(remaining_timeout):
                return False

        return True

    def has_synced(self) -> bool:
        """Check if all informers have synced.

        Returns:
            True if all informers have completed initial sync
        """
        # Check both async and sync informers
        async_synced = all(informer._has_synced() for informer in self._async_informers.values())
        sync_synced = all(informer._has_synced() for informer in self._sync_informers.values())

        # Return True if there are no informers, or all informers are synced
        if not self._async_informers and not self._sync_informers:
            return True

        return async_synced and sync_synced

    def resource_count(self) -> int:
        """Get total number of cached resources across all informers.

        Returns:
            Total number of cached resources
        """
        total = 0
        # Count from async informers
        for async_informer in self._async_informers.values():
            total += async_informer._store.size()
        # Count from sync informers
        for sync_informer in self._sync_informers.values():
            total += sync_informer._store.size()
        return total

    def list_async_informers(self) -> Dict[str, AsyncInformer[Any]]:
        """List all async informers.

        Returns:
            Dictionary mapping keys to async informers
        """
        return self._async_informers.copy()

    def list_sync_informers(self) -> Dict[str, SyncInformer[Any]]:
        """List all sync informers.

        Returns:
            Dictionary mapping keys to sync informers
        """
        return self._sync_informers.copy()
