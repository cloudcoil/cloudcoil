"""Concurrent-safe store implementation for caching Kubernetes resources."""

import asyncio
import logging
import threading
from typing import Callable, Dict, Generic, List, Optional, Set, TypeVar

from cloudcoil.resources import Resource

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class ConcurrentStore(Generic[T]):
    """Concurrent-safe cache store for resources with custom indexing.

    Safe for both async (coroutine) and sync (thread) access patterns.
    Uses asyncio.Lock for async operations and threading.RLock for sync wrappers.

    Example:
        >>> store = ConcurrentStore[Pod]()
        >>> # Add custom index
        >>> store.add_index("by_app", lambda pod: pod.metadata.labels.get("app", ""))
        >>> # Add items (async)
        >>> await store.add(pod1)
        >>> await store.add(pod2)
        >>> # Query by index
        >>> nginx_pods = store.get_by_index("by_app", "nginx")
    """

    def __init__(
        self,
        key_func: Optional[Callable[[T], str]] = None,
        max_items: int = 10000,
    ):
        """Initialize the concurrent store.

        Args:
            key_func: Function to extract key from object (default: namespace/name)
            max_items: Maximum number of items to store (0 = unlimited)
        """
        self._items: Dict[str, T] = {}
        self._indices: Dict[str, Dict[str, Set[str]]] = {}
        self._index_funcs: Dict[str, Callable[[T], str]] = {}
        self._key_func = key_func or self._default_key_func
        self._max_items = max_items

        # Dual locking strategy for async-first with sync wrapper support
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.RLock()

    @staticmethod
    def _default_key_func(obj: T) -> str:
        """Default key function using namespace/name."""
        if hasattr(obj, "metadata") and obj.metadata:
            if obj.metadata.namespace:
                return f"{obj.metadata.namespace}/{obj.metadata.name}"
            return obj.metadata.name or ""
        return ""

    def add_index(self, name: str, index_func: Callable[[T], str]) -> None:
        """Add a custom index for efficient lookups.

        This method is thread-safe and can be called from any context.

        Args:
            name: Name of the index
            index_func: Function that extracts index key from object

        Example:
            >>> # Index by label
            >>> store.add_index("by_app", lambda obj: obj.metadata.labels.get("app", ""))
            >>> # Index by owner
            >>> store.add_index("by_owner",
            ...     lambda obj: obj.metadata.owner_references[0].name
            ...     if obj.metadata.owner_references else ""
            ... )
        """
        with self._thread_lock:
            self._index_funcs[name] = index_func
            self._indices[name] = {}

            # Rebuild index for existing items
            for key, obj in self._items.items():
                index_key = index_func(obj)
                if index_key:
                    if index_key not in self._indices[name]:
                        self._indices[name][index_key] = set()
                    self._indices[name][index_key].add(key)

    def get_by_index(self, index_name: str, index_key: str) -> List[T]:
        """Get objects by custom index.

        This is a read operation and is safe without locks.

        Args:
            index_name: Name of the index to use
            index_key: The index key to look up

        Returns:
            List of objects matching the index key

        Raises:
            KeyError: If the index doesn't exist
        """
        if index_name not in self._indices:
            raise KeyError(f"Index {index_name} not found")

        keys = self._indices[index_name].get(index_key, set())
        return [self._items[key] for key in keys if key in self._items]

    def list_index_keys(self, index_name: str) -> List[str]:
        """List all keys in a given index.

        Args:
            index_name: Name of the index

        Returns:
            List of all index keys

        Raises:
            KeyError: If the index doesn't exist
        """
        if index_name not in self._indices:
            raise KeyError(f"Index {index_name} not found")
        return list(self._indices[index_name].keys())

    async def add(self, obj: T) -> None:
        """Add or update an object in the store (async-safe).

        Args:
            obj: The object to add or update
        """
        async with self._async_lock:
            self._add_internal(obj)

    def sync_add(self, obj: T) -> None:
        """Add or update an object in the store (thread-safe for sync wrapper).

        Args:
            obj: The object to add or update
        """
        with self._thread_lock:
            self._add_internal(obj)

    def _add_internal(self, obj: T) -> None:
        """Internal add implementation (must be called with lock held)."""
        key = self._key_func(obj)
        if not key:
            logger.warning("Object has no key, skipping: %s", obj)
            return

        # Check max items limit
        if self._max_items > 0 and key not in self._items:
            if len(self._items) >= self._max_items:
                logger.warning(
                    "Store at max capacity (%d items), dropping oldest item",
                    self._max_items,
                )
                # Drop the oldest item (first in dict)
                oldest_key = next(iter(self._items))
                self._delete_internal(oldest_key)

        old_obj = self._items.get(key)
        self._items[key] = obj
        self._update_indices(key, old_obj, obj)

    def _update_indices(self, key: str, old_obj: Optional[T], new_obj: Optional[T]) -> None:
        """Update all indices when an object changes."""
        for index_name, index_func in self._index_funcs.items():
            # Remove from old index
            if old_obj:
                old_index_key = index_func(old_obj)
                if old_index_key and old_index_key in self._indices[index_name]:
                    self._indices[index_name][old_index_key].discard(key)
                    if not self._indices[index_name][old_index_key]:
                        del self._indices[index_name][old_index_key]

            # Add to new index
            if new_obj:
                new_index_key = index_func(new_obj)
                if new_index_key:
                    if new_index_key not in self._indices[index_name]:
                        self._indices[index_name][new_index_key] = set()
                    self._indices[index_name][new_index_key].add(key)

    def get(self, key: str) -> Optional[T]:
        """Get an object by key (safe without lock - read-only operation).

        In Python, dict.get() is atomic due to GIL.
        Safe for both async and sync contexts.

        Args:
            key: The key to look up

        Returns:
            The object if found, None otherwise
        """
        return self._items.get(key)

    def get_by_name(self, name: str, namespace: Optional[str] = None) -> Optional[T]:
        """Get an object by name and namespace.

        Args:
            name: Name of the object
            namespace: Namespace of the object (optional)

        Returns:
            The object if found, None otherwise
        """
        if namespace:
            key = f"{namespace}/{name}"
        else:
            key = name
        return self.get(key)

    def list(self) -> List[T]:
        """List all objects in the store (returns snapshot).

        list() creates a new list, safe for iteration.

        Returns:
            List of all objects in the store
        """
        return list(self._items.values())

    def list_keys(self) -> List[str]:
        """List all keys in the store.

        Returns:
            List of all keys
        """
        return list(self._items.keys())

    async def delete(self, obj: T) -> None:
        """Delete an object from the store (async-safe).

        Args:
            obj: The object to delete
        """
        async with self._async_lock:
            key = self._key_func(obj)
            if key:
                self._delete_internal(key)

    def sync_delete(self, obj: T) -> None:
        """Delete an object from the store (thread-safe for sync wrapper).

        Args:
            obj: The object to delete
        """
        with self._thread_lock:
            key = self._key_func(obj)
            if key:
                self._delete_internal(key)

    def _delete_internal(self, key: str) -> None:
        """Internal delete implementation (must be called with lock held)."""
        if key in self._items:
            obj = self._items[key]
            del self._items[key]
            self._update_indices(key, obj, None)

    async def replace(self, items: List[T]) -> None:
        """Replace all items in the store (async-safe).

        Args:
            items: New list of items to store
        """
        async with self._async_lock:
            self._replace_internal(items)

    def sync_replace(self, items: List[T]) -> None:
        """Replace all items in the store (thread-safe for sync wrapper).

        Args:
            items: New list of items to store
        """
        with self._thread_lock:
            self._replace_internal(items)

    def _replace_internal(self, items: List[T]) -> None:
        """Internal replace implementation (must be called with lock held)."""
        # Clear existing items and indices
        self._items.copy()
        self._items.clear()

        # Clear indices
        for index_name in self._indices:
            self._indices[index_name].clear()

        # Add new items
        for item in items:
            key = self._key_func(item)
            if key:
                self._items[key] = item
                # Update indices for new item
                for index_name, index_func in self._index_funcs.items():
                    index_key = index_func(item)
                    if index_key:
                        if index_key not in self._indices[index_name]:
                            self._indices[index_name][index_key] = set()
                        self._indices[index_name][index_key].add(key)

    def size(self) -> int:
        """Get the number of items in the store.

        Returns:
            Number of items
        """
        return len(self._items)

    def clear(self) -> None:
        """Clear all items from the store (thread-safe)."""
        with self._thread_lock:
            self._items.clear()
            for index in self._indices.values():
                index.clear()
