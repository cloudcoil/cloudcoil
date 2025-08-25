"""Cache implementation for informer system."""

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator, Optional, Type, TypeVar, Union

from ._types import Cache as CacheConfig
from ._types import CacheStatus

if TYPE_CHECKING:
    from cloudcoil.resources import Resource

    from ._factory import SharedInformerFactory
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
        self._factory: Optional["SharedInformerFactory"] = None
        self._started: bool = False
        self._pause_count: int = 0  # For nested pause context managers
        self._original_enabled: Optional[bool] = None  # Store original state

    def set_factory(self, factory: "SharedInformerFactory") -> None:
        """Set the informer factory (called by Config)."""
        self._factory = factory

    # Async methods (CloudCoil async_ prefix pattern)
    async def async_start(self) -> None:
        """Start all informers asynchronously."""
        if not self.enabled or self._started:
            return
        if self._factory:
            await self._factory.async_start()
            self._started = True
            logger.debug("Cache started")

    async def async_stop(self) -> None:
        """Stop all informers asynchronously."""
        if self._factory and self._started:
            await self._factory.async_stop()
            self._started = False
            logger.debug("Cache stopped")

    async def async_wait_for_cache_sync(self, timeout: Optional[float] = None) -> bool:
        """Wait for cache to sync asynchronously.

        Args:
            timeout: Maximum time to wait (uses sync_timeout if not provided)

        Returns:
            True if synced, False if timeout
        """
        if not self.enabled or not self._factory:
            return True
        timeout = timeout or self.sync_timeout
        return await self._factory.async_wait_for_sync(timeout)

    # Synchronous methods (verb-based naming)
    def start(self) -> None:
        """Start all informers synchronously (blocks until started)."""
        if not self.enabled or self._started:
            return
        if self._factory:
            self._factory.start()
            self._started = True

    def stop(self) -> None:
        """Stop all informers synchronously (blocks until stopped)."""
        if self._factory and self._started:
            self._factory.stop()
            self._started = False

    def wait_for_cache_sync(self, timeout: Optional[float] = None) -> bool:
        """Wait for cache to sync synchronously.

        Args:
            timeout: Maximum time to wait (uses sync_timeout if not provided)

        Returns:
            True if synced, False if timeout
        """
        if not self.enabled or not self._factory:
            return True
        timeout = timeout or self.sync_timeout
        return self._factory.wait_for_sync(timeout)

    # Non-blocking methods (no I/O)
    def ready(self) -> bool:
        """Check if cache is synced and ready (non-blocking check)."""
        if not self.enabled:
            return True
        if not self._factory or not self._started:
            return False
        return self._factory.has_synced()

    def get_informer(
        self,
        resource_type: Type[T],
        sync: bool = False,
        namespace: Optional[str] = None,
    ) -> Optional[Union["AsyncInformer[T]", "SyncInformer[T]"]]:
        """Get informer for a specific resource type (no I/O needed).

        Args:
            resource_type: The resource type
            sync: Whether to return sync wrapper
            namespace: Optional namespace scope

        Returns:
            The informer instance, or None if not available
        """
        if not self.enabled or not self._factory:
            return None
        return self._factory.get_informer(resource_type, sync=sync, namespace=namespace)

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

        if not self._factory:
            return CacheStatus(enabled=True, ready=False)

        return CacheStatus(
            enabled=True,
            started=self._started,
            ready=self.ready(),
            resource_count=self._factory.resource_count(),
            informer_count=len(self._factory._async_informers) + len(self._factory._sync_informers),
        )
