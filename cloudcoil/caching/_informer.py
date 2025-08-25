"""Refactored informer implementations with better concurrency and minimal public API."""

import asyncio
import logging
import threading
from typing import Any, Callable, Generic, List, Optional, TypeVar, Union, overload

from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.resources import Resource

from ._event_dispatcher import _AsyncEventDispatcher, _SyncEventDispatcher
from ._store import ConcurrentStore
from ._types import (
    AsyncEventHandler,
    AsyncUpdateHandler,
    EventHandler,
    InformerOptions,
    UpdateHandler,
)
from ._watch_manager import _AsyncWatchManager, _SyncWatchManager

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class AsyncInformer(Generic[T]):
    """Async informer with minimal public API and better concurrency patterns.

    Public API:
    - get(name, namespace) - Get resource from cache
    - list(namespace, label_selector, field_selector) - List resources from cache
    - on_add(handler) - Register add event handler
    - on_update(handler) - Register update event handler
    - on_delete(handler) - Register delete event handler

    All other methods and attributes are private implementation details.
    """

    def __init__(
        self,
        client: AsyncAPIClient[T],
        options: InformerOptions,
    ):
        """Initialize the async informer."""
        self._client = client
        self._options = options

        # Components
        self._store = ConcurrentStore[T](max_items=10000)
        self._dispatcher = _AsyncEventDispatcher[T]()
        self._watch = _AsyncWatchManager(
            client=client,
            options=options,
            on_items_callback=self._handle_initial_items,
            on_event_callback=self._handle_watch_event,
        )

        # Sync state
        self._sync_event = asyncio.Event()
        self._started = False

        # Pending handlers to register when loop is available
        self._pending_handlers: List[tuple] = []

    # ============ Public Read API ============

    def get(self, name: str, namespace: Optional[str] = None) -> Optional[T]:
        """Get a resource from cache by name."""
        return self._store.get_by_name(name, namespace)

    def list(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
    ) -> List[T]:
        """List resources from cache with optional filtering."""
        items = self._store.list()

        # Apply filters
        if namespace is not None:
            items = [
                item
                for item in items
                if hasattr(item, "metadata")
                and item.metadata
                and item.metadata.namespace == namespace
            ]

        if label_selector:
            items = self._filter_by_labels(items, label_selector)

        if field_selector:
            items = self._filter_by_fields(items, field_selector)

        return items

    # ============ Public Event API ============

    @overload
    def on_add(self, handler: Union[EventHandler, AsyncEventHandler]) -> None:
        """Register a handler for add events."""
        ...

    @overload
    def on_add(
        self, handler: None = None
    ) -> Callable[[Union[EventHandler, AsyncEventHandler]], Union[EventHandler, AsyncEventHandler]]:
        """Use as a decorator to register a handler for add events."""
        ...

    def on_add(self, handler: Optional[Union[EventHandler, AsyncEventHandler]] = None) -> Any:
        """Register a handler for add events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_add
            def handle_add(obj):
                print(f"Added: {obj.metadata.name}")

            # As a regular method
            informer.on_add(handle_add)
        """

        def register(
            h: Union[EventHandler, AsyncEventHandler],
        ) -> Union[EventHandler, AsyncEventHandler]:
            # Defer task creation to avoid RuntimeError when no loop is running
            try:
                # Try to get the running loop
                loop = asyncio.get_running_loop()
                # If we have a loop, create the task
                loop.create_task(self._dispatcher.register_add_handler(h))
            except RuntimeError:
                # No running loop - store for later registration
                self._pending_handlers.append(("add", h))
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    @overload
    def on_update(self, handler: Union[UpdateHandler, AsyncUpdateHandler]) -> None:
        """Register a handler for update events."""
        ...

    @overload
    def on_update(
        self, handler: None = None
    ) -> Callable[
        [Union[UpdateHandler, AsyncUpdateHandler]], Union[UpdateHandler, AsyncUpdateHandler]
    ]:
        """Use as a decorator to register a handler for update events."""
        ...

    def on_update(self, handler: Optional[Union[UpdateHandler, AsyncUpdateHandler]] = None) -> Any:
        """Register a handler for update events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_update
            def handle_update(old_obj, new_obj):
                print(f"Updated: {new_obj.metadata.name}")

            # As a regular method
            informer.on_update(handle_update)
        """

        def register(
            h: Union[UpdateHandler, AsyncUpdateHandler],
        ) -> Union[UpdateHandler, AsyncUpdateHandler]:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dispatcher.register_update_handler(h))
            except RuntimeError:
                # No running loop - store for later registration
                self._pending_handlers.append(("update", h))
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    @overload
    def on_delete(self, handler: Union[EventHandler, AsyncEventHandler]) -> None:
        """Register a handler for delete events."""
        ...

    @overload
    def on_delete(
        self, handler: None = None
    ) -> Callable[[Union[EventHandler, AsyncEventHandler]], Union[EventHandler, AsyncEventHandler]]:
        """Use as a decorator to register a handler for delete events."""
        ...

    def on_delete(self, handler: Optional[Union[EventHandler, AsyncEventHandler]] = None) -> Any:
        """Register a handler for delete events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_delete
            def handle_delete(obj):
                print(f"Deleted: {obj.metadata.name}")

            # As a regular method
            informer.on_delete(handle_delete)
        """

        def register(
            h: Union[EventHandler, AsyncEventHandler],
        ) -> Union[EventHandler, AsyncEventHandler]:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dispatcher.register_delete_handler(h))
            except RuntimeError:
                # No running loop - store for later registration
                self._pending_handlers.append(("delete", h))
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    # ============ Public Index API (Advanced Usage) ============

    def add_index(self, name: str, index_func: Callable[[T], str]) -> None:
        """Add a custom index for fast lookups.

        Args:
            name: The name of the index
            index_func: Function that extracts index key from a resource
        """
        self._store.add_index(name, index_func)

    def get_by_index(self, index_name: str, index_key: str) -> List[T]:
        """Get resources by custom index."""
        return self._store.get_by_index(index_name, index_key)

    def list_index_keys(self, index_name: str) -> List[str]:
        """List all keys for a given index."""
        return self._store.list_index_keys(index_name)

    # ============ Public Status API ============

    def has_synced(self) -> bool:
        """Check if initial sync is complete."""
        return self._has_synced()

    # ============ Private Implementation ============

    async def _start(self) -> None:
        """Start the informer (internal use only)."""
        if self._started:
            return
        self._started = True

        # Register any pending handlers now that we have a loop
        for handler_type, handler in self._pending_handlers:
            if handler_type == "add":
                await self._dispatcher.register_add_handler(handler)
            elif handler_type == "update":
                await self._dispatcher.register_update_handler(handler)
            elif handler_type == "delete":
                await self._dispatcher.register_delete_handler(handler)
        self._pending_handlers.clear()

        await self._watch.start()

    async def _stop(self) -> None:
        """Stop the informer (internal use only)."""
        if not self._started:
            return
        self._started = False
        await self._watch.stop()

    async def _wait_for_sync(self, timeout: float = 30.0) -> bool:
        """Wait for initial sync (internal use only)."""
        try:
            await asyncio.wait_for(self._sync_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _has_synced(self) -> bool:
        """Check if initial sync complete (internal use only)."""
        return self._sync_event.is_set() and self._watch.is_running

    async def _handle_initial_items(self, items: List[T], resource_version: str) -> None:
        """Handle initial list of items."""
        await self._store.replace(items)
        self._sync_event.set()
        logger.info(
            "Initial sync complete for %s: %d items", self._client.kind.__name__, len(items)
        )

    async def _handle_watch_event(self, event_type: str, obj: Any) -> None:
        """Handle watch event."""
        if event_type == "BOOKMARK":
            # Just a resource version update
            return
        elif event_type == "ADDED":
            await self._handle_add(obj)
        elif event_type == "MODIFIED":
            await self._handle_update(obj)
        elif event_type == "DELETED":
            await self._handle_delete(obj)
        elif event_type == "ERROR":
            logger.error("Watch error event: %s", obj)

    async def _handle_add(self, obj: T) -> None:
        """Handle resource add."""
        await self._store.add(obj)
        await self._dispatcher.dispatch_add(obj)

    async def _handle_update(self, obj: T) -> None:
        """Handle resource update."""
        key = self._get_key(obj)
        old_obj = self._store.get(key) if key else None
        await self._store.add(obj)  # add acts as update
        await self._dispatcher.dispatch_update(old_obj, obj)

    async def _handle_delete(self, obj: T) -> None:
        """Handle resource delete."""
        await self._store.delete(obj)
        await self._dispatcher.dispatch_delete(obj)

    def _get_key(self, obj: T) -> Optional[str]:
        """Get cache key for object."""
        if hasattr(obj, "metadata") and obj.metadata:
            namespace = obj.metadata.namespace or ""
            name = obj.metadata.name
            return f"{namespace}/{name}" if name else None
        return None

    def _filter_by_labels(self, items: List[T], selector: str) -> List[T]:
        """Filter items by label selector."""
        # Simple implementation - just check for exact matches
        parts = selector.split("=")
        if len(parts) != 2:
            return items

        key, value = parts[0].strip(), parts[1].strip()
        return [
            item
            for item in items
            if hasattr(item, "metadata")
            and item.metadata
            and item.metadata.labels
            and item.metadata.labels.get(key) == value
        ]

    def _filter_by_fields(self, items: List[T], selector: str) -> List[T]:
        """Filter items by field selector."""
        # Simple implementation for metadata.name and metadata.namespace
        parts = selector.split("=")
        if len(parts) != 2:
            return items

        field, value = parts[0].strip(), parts[1].strip()

        if field == "metadata.name":
            return [
                item
                for item in items
                if hasattr(item, "metadata") and item.metadata and item.metadata.name == value
            ]
        elif field == "metadata.namespace":
            return [
                item
                for item in items
                if hasattr(item, "metadata") and item.metadata and item.metadata.namespace == value
            ]

        return items


class SyncInformer(Generic[T]):
    """Sync informer with minimal public API and better threading patterns.

    Public API:
    - get(name, namespace) - Get resource from cache
    - list(namespace, label_selector, field_selector) - List resources from cache
    - on_add(handler) - Register add event handler
    - on_update(handler) - Register update event handler
    - on_delete(handler) - Register delete event handler

    All other methods and attributes are private implementation details.
    """

    def __init__(
        self,
        client: APIClient[T],
        options: InformerOptions,
    ):
        """Initialize the sync informer."""
        self._client = client
        self._options = options

        # Components
        self._store = ConcurrentStore[T](max_items=10000)
        self._dispatcher = _SyncEventDispatcher[T]()
        self._watch = _SyncWatchManager(
            client=client,
            options=options,
            on_items_callback=self._handle_initial_items,
            on_event_callback=self._handle_watch_event,
        )

        # Sync state
        self._sync_event = threading.Event()
        self._started = False
        self._started_lock = threading.Lock()

    # ============ Public Read API ============

    def get(self, name: str, namespace: Optional[str] = None) -> Optional[T]:
        """Get a resource from cache by name."""
        return self._store.get_by_name(name, namespace)

    def list(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
    ) -> List[T]:
        """List resources from cache with optional filtering."""
        items = self._store.list()

        # Apply filters
        if namespace is not None:
            items = [
                item
                for item in items
                if hasattr(item, "metadata")
                and item.metadata
                and item.metadata.namespace == namespace
            ]

        if label_selector:
            items = self._filter_by_labels(items, label_selector)

        if field_selector:
            items = self._filter_by_fields(items, field_selector)

        return items

    # ============ Public Event API ============

    @overload
    def on_add(self, handler: EventHandler) -> None:
        """Register a handler for add events."""
        ...

    @overload
    def on_add(self, handler: None = None) -> Callable[[EventHandler], EventHandler]:
        """Use as a decorator to register a handler for add events."""
        ...

    def on_add(self, handler: Optional[EventHandler] = None) -> Any:
        """Register a handler for add events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_add
            def handle_add(obj):
                print(f"Added: {obj.metadata.name}")

            # As a regular method
            informer.on_add(handle_add)
        """

        def register(h: EventHandler) -> EventHandler:
            self._dispatcher.register_add_handler(h)
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    @overload
    def on_update(self, handler: UpdateHandler) -> None:
        """Register a handler for update events."""
        ...

    @overload
    def on_update(self, handler: None = None) -> Callable[[UpdateHandler], UpdateHandler]:
        """Use as a decorator to register a handler for update events."""
        ...

    def on_update(self, handler: Optional[UpdateHandler] = None) -> Any:
        """Register a handler for update events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_update
            def handle_update(old_obj, new_obj):
                print(f"Updated: {new_obj.metadata.name}")

            # As a regular method
            informer.on_update(handle_update)
        """

        def register(h: UpdateHandler) -> UpdateHandler:
            self._dispatcher.register_update_handler(h)
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    @overload
    def on_delete(self, handler: EventHandler) -> None:
        """Register a handler for delete events."""
        ...

    @overload
    def on_delete(self, handler: None = None) -> Callable[[EventHandler], EventHandler]:
        """Use as a decorator to register a handler for delete events."""
        ...

    def on_delete(self, handler: Optional[EventHandler] = None) -> Any:
        """Register a handler for delete events. Can be used as a decorator.

        Usage:
            # As a decorator
            @informer.on_delete
            def handle_delete(obj):
                print(f"Deleted: {obj.metadata.name}")

            # As a regular method
            informer.on_delete(handle_delete)
        """

        def register(h: EventHandler) -> EventHandler:
            self._dispatcher.register_delete_handler(h)
            return h

        if handler is None:
            # Being used as a decorator
            return register
        else:
            # Being called directly with a handler
            register(handler)
            return None

    # ============ Public Index API (Advanced Usage) ============

    def add_index(self, name: str, index_func: Callable[[T], str]) -> None:
        """Add a custom index for fast lookups.

        Args:
            name: The name of the index
            index_func: Function that extracts index key from a resource
        """
        self._store.add_index(name, index_func)

    def get_by_index(self, index_name: str, index_key: str) -> List[T]:
        """Get resources by custom index."""
        return self._store.get_by_index(index_name, index_key)

    def list_index_keys(self, index_name: str) -> List[str]:
        """List all keys for a given index."""
        return self._store.list_index_keys(index_name)

    # ============ Public Status API ============

    def has_synced(self) -> bool:
        """Check if initial sync is complete."""
        return self._has_synced()

    # ============ Private Implementation ============

    def _start(self) -> None:
        """Start the informer (internal use only)."""
        with self._started_lock:
            if self._started:
                return
            self._started = True
            self._watch.start()

    def _stop(self) -> None:
        """Stop the informer (internal use only)."""
        with self._started_lock:
            if not self._started:
                return
            self._started = False
            self._watch.stop()

    def _wait_for_sync(self, timeout: float = 30.0) -> bool:
        """Wait for initial sync (internal use only)."""
        return self._sync_event.wait(timeout=timeout)

    def _has_synced(self) -> bool:
        """Check if initial sync complete (internal use only)."""
        return self._sync_event.is_set() and self._watch.is_running

    def _handle_initial_items(self, items: List[T], resource_version: str) -> None:
        """Handle initial list of items."""
        self._store.sync_replace(items)  # Use sync version
        self._sync_event.set()
        logger.info(
            "Initial sync complete for %s: %d items", self._client.kind.__name__, len(items)
        )

    def _handle_watch_event(self, event_type: str, obj: Any) -> None:
        """Handle watch event."""
        if event_type == "BOOKMARK":
            return
        elif event_type == "ADDED":
            self._handle_add(obj)
        elif event_type == "MODIFIED":
            self._handle_update(obj)
        elif event_type == "DELETED":
            self._handle_delete(obj)
        elif event_type == "ERROR":
            logger.error("Watch error event: %s", obj)

    def _handle_add(self, obj: T) -> None:
        """Handle resource add."""
        self._store.sync_add(obj)
        self._dispatcher.dispatch_add(obj)

    def _handle_update(self, obj: T) -> None:
        """Handle resource update."""
        key = self._get_key(obj)
        old_obj = self._store.get(key) if key else None
        self._store.sync_add(obj)  # add works as update too
        self._dispatcher.dispatch_update(old_obj, obj)

    def _handle_delete(self, obj: T) -> None:
        """Handle resource delete."""
        self._store.sync_delete(obj)
        self._dispatcher.dispatch_delete(obj)

    def _get_key(self, obj: T) -> Optional[str]:
        """Get cache key for object."""
        if hasattr(obj, "metadata") and obj.metadata:
            namespace = obj.metadata.namespace or ""
            name = obj.metadata.name
            return f"{namespace}/{name}" if name else None
        return None

    def _filter_by_labels(self, items: List[T], selector: str) -> List[T]:
        """Filter items by label selector."""
        parts = selector.split("=")
        if len(parts) != 2:
            return items

        key, value = parts[0].strip(), parts[1].strip()
        return [
            item
            for item in items
            if hasattr(item, "metadata")
            and item.metadata
            and item.metadata.labels
            and item.metadata.labels.get(key) == value
        ]

    def _filter_by_fields(self, items: List[T], selector: str) -> List[T]:
        """Filter items by field selector."""
        parts = selector.split("=")
        if len(parts) != 2:
            return items

        field, value = parts[0].strip(), parts[1].strip()

        if field == "metadata.name":
            return [
                item
                for item in items
                if hasattr(item, "metadata") and item.metadata and item.metadata.name == value
            ]
        elif field == "metadata.namespace":
            return [
                item
                for item in items
                if hasattr(item, "metadata") and item.metadata and item.metadata.namespace == value
            ]

        return items
