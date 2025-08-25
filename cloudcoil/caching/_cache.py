"""Cache implementation for informer system."""

import asyncio
import logging
import time
from contextlib import contextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    Type,
    TypeVar,
    Union,
    overload,
)

from ._types import Cache as CacheConfig
from ._types import CacheStatus, InformerOptions

if TYPE_CHECKING:
    from cloudcoil.client._api_client import APIClient, AsyncAPIClient
    from cloudcoil.resources import Resource

from ._informer import AsyncInformer
from ._sync_informer import SyncInformer

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="Resource")


class Cache(CacheConfig):
    """Cache configuration and runtime control.

    This extends the CacheConfig Pydantic model with runtime methods for
    controlling the informer system lifecycle.

    Configuration fields are validated by Pydantic, while runtime methods
    provide lifecycle control following CloudCoil's async-first patterns.
    """

    def __init__(self, **data: Any) -> None:
        """Initialize cache with configuration."""
        super().__init__(**data)
        self._client_factory: Optional[Any] = None  # Will be set to client_for method
        self._async_informers: Dict[str, "AsyncInformer[Any]"] = {}
        self._sync_informers: Dict[str, "SyncInformer[Any]"] = {}
        self._started: bool = False
        self._start_tasks: List[asyncio.Task] = []  # Track informer start tasks
        self._pause_count: int = 0  # For nested pause context managers
        self._original_enabled: Optional[bool] = None  # Store original state

    def set_client_factory(self, factory: Any) -> None:
        """Set the client factory function (called by Config)."""
        self._client_factory = factory

    @overload
    def _create_client(self, resource_type: Type[T], sync: Literal[True]) -> "APIClient[T]": ...

    @overload
    def _create_client(
        self, resource_type: Type[T], sync: Literal[False]
    ) -> "AsyncAPIClient[T]": ...

    def _create_client(
        self, resource_type: Type[T], sync: bool
    ) -> Union["APIClient[T]", "AsyncAPIClient[T]"]:
        """Create a properly typed client using the factory."""
        if not self._client_factory:
            raise RuntimeError("Client factory not set")
        # Use cached=False to get base client without caching
        return self._client_factory(resource_type, sync=sync, cached=False)  # type: ignore[return-value]

    # Async methods (CloudCoil async_ prefix pattern)
    async def async_start(self) -> None:
        """Start all informers asynchronously."""
        if not self.enabled or self._started:
            return

        self._started = True

        # Pre-create informers for configured resources
        if self.resources:
            logger.debug("Pre-creating informers for %d configured resources", len(self.resources))
            for resource_type in self.resources:
                # This will create the informer if it doesn't exist
                self.get_informer(resource_type, sync=False)

        # Start all async informers and track tasks
        self._start_tasks = []
        if self._async_informers:
            for key, informer in self._async_informers.items():
                if isinstance(informer, AsyncInformer):
                    logger.debug("Starting informer for %s", key)
                    task = asyncio.create_task(informer._start())
                    self._start_tasks.append(task)

            # Wait for all informers to start
            if self._start_tasks:
                await asyncio.gather(*self._start_tasks, return_exceptions=True)

        logger.debug("Cache started with %d async informers", len(self._async_informers))

    async def async_stop(self) -> None:
        """Stop all informers asynchronously."""
        if not self._started:
            return

        self._started = False

        # Stop all async informers
        if self._async_informers:
            tasks = []
            for informer in self._async_informers.values():
                if isinstance(informer, AsyncInformer):
                    tasks.append(informer._stop())
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug("Cache stopped")

    async def async_wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for cache to be ready asynchronously.

        Args:
            timeout: Maximum time to wait (uses sync_timeout if not provided)

        Returns:
            True if ready, False if timeout
        """
        if not self.enabled:
            return True

        # If resources are configured but no informers created yet, that's not ready
        if self.resources and not self._async_informers and not self._sync_informers:
            logger.warning("Cache has configured resources but no informers created yet")
            return False

        # If no informers at all and no resources configured, that's OK
        if not self._async_informers and not self._sync_informers and not self.resources:
            return True

        timeout = timeout or self.sync_timeout

        # First wait for any pending start tasks
        if self._start_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._start_tasks, return_exceptions=True),
                    timeout=timeout / 2,  # Use half timeout for starting
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for informers to start")
                return False

        # Then wait for all async informers to sync
        sync_tasks = []
        for informer in self._async_informers.values():
            if isinstance(informer, AsyncInformer):
                sync_tasks.append(informer._wait_for_sync(timeout))

        if sync_tasks:
            results = await asyncio.gather(*sync_tasks, return_exceptions=True)
            return all(r is True for r in results if not isinstance(r, Exception))

        return True

    # Synchronous methods (verb-based naming)
    def start(self) -> None:
        """Start all informers synchronously (blocks until started)."""
        if not self.enabled or self._started:
            return

        self._started = True

        # Pre-create informers for configured resources
        if self.resources:
            logger.debug(
                "Pre-creating sync informers for %d configured resources", len(self.resources)
            )
            for resource_type in self.resources:
                # This will create the informer if it doesn't exist
                self.get_informer(resource_type, sync=True)

        # Start all sync informers
        for informer in self._sync_informers.values():
            if isinstance(informer, SyncInformer):
                informer._start()

        logger.debug("Cache started with %d sync informers", len(self._sync_informers))

    def stop(self) -> None:
        """Stop all informers synchronously (blocks until stopped)."""
        if not self._started:
            return

        self._started = False

        # Stop all sync informers
        for informer in self._sync_informers.values():
            if isinstance(informer, SyncInformer):
                informer._stop()

        logger.debug("Cache stopped")

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for cache to be ready synchronously.

        Args:
            timeout: Maximum time to wait (uses sync_timeout if not provided)

        Returns:
            True if ready, False if timeout
        """
        if not self.enabled:
            return True

        # If resources are configured but no informers created yet, that's not ready
        if self.resources and not self._sync_informers and not self._async_informers:
            logger.warning("Cache has configured resources but no informers created yet")
            return False

        # If no informers at all and no resources configured, that's OK
        if not self._sync_informers and not self._async_informers and not self.resources:
            return True

        timeout = timeout or self.sync_timeout

        # Wait for all sync informers to sync
        start_time = time.time()
        for informer in self._sync_informers.values():
            if isinstance(informer, SyncInformer):
                remaining = max(0, timeout - (time.time() - start_time))
                if not informer._wait_for_sync(remaining):
                    return False

        return True

    # Non-blocking methods (no I/O)
    def ready(self) -> bool:
        """Check if cache is synced and ready (non-blocking check)."""
        if not self.enabled:
            return True
        if not self._started:
            return False

        # Check if all informers have synced
        for informer in self._async_informers.values():
            if isinstance(informer, AsyncInformer) and not informer._has_synced():
                return False

        for sync_informer in self._sync_informers.values():
            if isinstance(sync_informer, SyncInformer) and not sync_informer._has_synced():
                return False

        return True

    def get_informer(
        self,
        resource_type: Type[T],
        sync: bool = False,
        namespace: Optional[str] = None,
    ) -> Optional[Union["AsyncInformer[T]", "SyncInformer[T]"]]:
        """Get or create informer for a specific resource type.

        Args:
            resource_type: The resource type
            sync: Whether to return sync wrapper
            namespace: Optional namespace scope

        Returns:
            The informer instance, or None if not available
        """
        if not self.enabled or not self._client_factory:
            return None

        # Check if we should cache this resource
        if not self.should_cache(resource_type):
            return None

        # Create cache key
        key = f"{resource_type.__module__}.{resource_type.__name__}"
        if namespace:
            key += f":{namespace}"

        if sync:
            # Get or create sync informer
            if key not in self._sync_informers:
                # Create sync client using factory
                sync_client: APIClient[T] = self._create_client(resource_type, True)
                options = self._create_options(resource_type, namespace)

                sync_informer: SyncInformer[T] = SyncInformer(sync_client, options)
                self._sync_informers[key] = sync_informer  # type: ignore[assignment]

                # Auto-start if cache is running
                if self._started:
                    sync_informer._start()  # type: ignore[func-returns-value]
                    # Note: Sync informers start synchronously, no task tracking needed

            return self._sync_informers[key]  # type: ignore[return-value]
        else:
            # Get or create async informer
            if key not in self._async_informers:
                # Create async client using factory
                async_client: AsyncAPIClient[T] = self._create_client(resource_type, False)
                options = self._create_options(resource_type, namespace)

                async_informer: AsyncInformer[T] = AsyncInformer(async_client, options)
                self._async_informers[key] = async_informer  # type: ignore[assignment]

                # Auto-start if cache is running
                if self._started:
                    task = asyncio.create_task(async_informer._start())
                    self._start_tasks.append(task)

                    # Also create a task to wait for initial sync
                    async def wait_for_sync():
                        try:
                            await task  # Wait for start to complete
                            await async_informer._wait_for_sync(self.sync_timeout)
                        except Exception as e:
                            logger.error("Error starting informer for %s: %s", key, e)

                    asyncio.create_task(wait_for_sync())

            return self._async_informers[key]  # type: ignore[return-value]

    def _create_options(
        self,
        resource_type: Type["Resource"],
        namespace: Optional[str],
    ) -> InformerOptions:
        """Create informer options for resource type."""
        return InformerOptions(
            resync_period=self.resync_period,
            namespace=namespace,
            all_namespaces=namespace is None,
            label_selector=self.label_selector,
            field_selector=self.field_selector,
        )

    # Context managers
    @contextmanager
    def pause(self) -> Generator[None, None, None]:
        """Temporarily disable cache within this context.

        Supports nested usage with reference counting.
        """
        self._pause_count += 1
        if self._pause_count == 1:
            # First pause - save state and disable
            self._original_enabled = self.enabled
            self.enabled = False
        try:
            yield
        finally:
            self._pause_count -= 1
            if self._pause_count == 0:
                # Last pause exiting - restore state
                if self._original_enabled is not None:
                    self.enabled = self._original_enabled
                self._original_enabled = None

    @contextmanager
    def strict_mode(self) -> Generator[None, None, None]:
        """Temporarily use strict mode within this context."""
        original_mode = self.mode
        self.mode = "strict"
        try:
            yield
        finally:
            self.mode = original_mode

    @contextmanager
    def fallback_mode(self) -> Generator[None, None, None]:
        """Temporarily use fallback mode within this context."""
        original_mode = self.mode
        self.mode = "fallback"
        try:
            yield
        finally:
            self.mode = original_mode

    def status(self) -> CacheStatus:
        """Get cache status information."""
        if not self.enabled:
            return CacheStatus(enabled=False)

        if not self._client_factory:
            return CacheStatus(enabled=True, ready=False)

        # Count total resources across all informers
        resource_count = 0
        for informer in self._async_informers.values():
            resource_count += informer._store.size()
        for sync_informer in self._sync_informers.values():
            resource_count += sync_informer._store.size()

        return CacheStatus(
            enabled=True,
            started=self._started,
            ready=self.ready(),
            resource_count=resource_count,
            informer_count=len(self._async_informers) + len(self._sync_informers),
        )
