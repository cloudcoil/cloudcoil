"""Test utilities for CloudCoil tests."""

import asyncio
import time
from typing import Any, Callable, Optional, TypeVar

from cloudcoil.caching._informer import AsyncInformer, SyncInformer

T = TypeVar("T")


async def wait_for_condition(
    condition: Callable[[], bool],
    timeout: float = 10.0,
    interval: float = 0.1,
    message: str = "Condition not met",
) -> None:
    """Wait for a condition to become true.

    Args:
        condition: A callable that returns True when the condition is met
        timeout: Maximum time to wait in seconds
        interval: Time between checks in seconds
        message: Error message if timeout occurs

    Raises:
        TimeoutError: If condition is not met within timeout
    """
    start_time = asyncio.get_event_loop().time()
    while not condition():
        if asyncio.get_event_loop().time() - start_time > timeout:
            raise TimeoutError(f"{message} after {timeout}s")
        await asyncio.sleep(interval)


def sync_wait_for_condition(
    condition: Callable[[], bool],
    timeout: float = 10.0,
    interval: float = 0.1,
    message: str = "Condition not met",
) -> None:
    """Synchronously wait for a condition to become true.

    Args:
        condition: A callable that returns True when the condition is met
        timeout: Maximum time to wait in seconds
        interval: Time between checks in seconds
        message: Error message if timeout occurs

    Raises:
        TimeoutError: If condition is not met within timeout
    """
    start_time = time.time()
    while not condition():
        if time.time() - start_time > timeout:
            raise TimeoutError(f"{message} after {timeout}s")
        time.sleep(interval)


async def wait_for_cache_update(
    informer: AsyncInformer,
    name: str,
    namespace: Optional[str] = None,
    check: Optional[Callable[[Any], bool]] = None,
    timeout: float = 10.0,
) -> Any:
    """Wait for a resource to appear or update in the cache.

    Args:
        informer: The informer to check
        name: Resource name to wait for
        namespace: Resource namespace
        check: Optional additional check on the resource
        timeout: Maximum time to wait

    Returns:
        The resource once it meets all conditions

    Raises:
        TimeoutError: If resource doesn't meet conditions within timeout
    """

    def condition():
        obj = informer.get(name, namespace)
        if obj is None:
            return False
        if check is not None:
            return check(obj)
        return True

    await wait_for_condition(
        condition, timeout=timeout, message=f"Cache update for {name} in {namespace}"
    )
    return informer.get(name, namespace)


def sync_wait_for_cache_update(
    informer: SyncInformer,
    name: str,
    namespace: Optional[str] = None,
    check: Optional[Callable[[Any], bool]] = None,
    timeout: float = 10.0,
) -> Any:
    """Synchronously wait for a resource to appear or update in the cache.

    Args:
        informer: The informer to check
        name: Resource name to wait for
        namespace: Resource namespace
        check: Optional additional check on the resource
        timeout: Maximum time to wait

    Returns:
        The resource once it meets all conditions

    Raises:
        TimeoutError: If resource doesn't meet conditions within timeout
    """

    def condition():
        obj = informer.get(name, namespace)
        if obj is None:
            return False
        if check is not None:
            return check(obj)
        return True

    sync_wait_for_condition(
        condition, timeout=timeout, message=f"Cache update for {name} in {namespace}"
    )
    return informer.get(name, namespace)


class EventRecorder:
    """Records events for testing informer event handlers."""

    def __init__(self):
        self.added_items = []
        self.updated_items = []
        self.deleted_items = []
        self._add_event = asyncio.Event()
        self._update_event = asyncio.Event()
        self._delete_event = asyncio.Event()

    async def on_add(self, obj):
        """Handler for add events."""
        self.added_items.append(obj)
        self._add_event.set()

    async def on_update(self, old_obj, new_obj):
        """Handler for update events."""
        self.updated_items.append((old_obj, new_obj))
        self._update_event.set()

    async def on_delete(self, obj):
        """Handler for delete events."""
        self.deleted_items.append(obj)
        self._delete_event.set()

    async def wait_for_add(self, timeout: float = 10.0) -> None:
        """Wait for an add event."""
        await asyncio.wait_for(self._add_event.wait(), timeout=timeout)
        self._add_event.clear()

    async def wait_for_update(self, timeout: float = 10.0) -> None:
        """Wait for an update event."""
        await asyncio.wait_for(self._update_event.wait(), timeout=timeout)
        self._update_event.clear()

    async def wait_for_delete(self, timeout: float = 10.0) -> None:
        """Wait for a delete event."""
        await asyncio.wait_for(self._delete_event.wait(), timeout=timeout)
        self._delete_event.clear()

    async def wait_for_item_count(
        self,
        event_type: str,
        count: int,
        timeout: float = 10.0,
    ) -> None:
        """Wait for a specific number of events of a given type."""

        def condition():
            if event_type == "add":
                return len(self.added_items) >= count
            elif event_type == "update":
                return len(self.updated_items) >= count
            elif event_type == "delete":
                return len(self.deleted_items) >= count
            return False

        await wait_for_condition(
            condition, timeout=timeout, message=f"Waiting for {count} {event_type} events"
        )

    def clear(self):
        """Clear all recorded events."""
        self.added_items.clear()
        self.updated_items.clear()
        self.deleted_items.clear()
        self._add_event.clear()
        self._update_event.clear()
        self._delete_event.clear()


class SyncEventRecorder:
    """Records events for testing sync informer event handlers."""

    def __init__(self):
        self.added_items = []
        self.updated_items = []
        self.deleted_items = []
        self._add_event = False
        self._update_event = False
        self._delete_event = False

    def on_add(self, obj):
        """Handler for add events."""
        self.added_items.append(obj)
        self._add_event = True

    def on_update(self, old_obj, new_obj):
        """Handler for update events."""
        self.updated_items.append((old_obj, new_obj))
        self._update_event = True

    def on_delete(self, obj):
        """Handler for delete events."""
        self.deleted_items.append(obj)
        self._delete_event = True

    def wait_for_add(self, timeout: float = 10.0) -> None:
        """Wait for an add event."""
        sync_wait_for_condition(
            lambda: self._add_event, timeout=timeout, message="Waiting for add event"
        )
        self._add_event = False

    def wait_for_update(self, timeout: float = 10.0) -> None:
        """Wait for an update event."""
        sync_wait_for_condition(
            lambda: self._update_event, timeout=timeout, message="Waiting for update event"
        )
        self._update_event = False

    def wait_for_delete(self, timeout: float = 10.0) -> None:
        """Wait for a delete event."""
        sync_wait_for_condition(
            lambda: self._delete_event, timeout=timeout, message="Waiting for delete event"
        )
        self._delete_event = False

    def wait_for_item_count(
        self,
        event_type: str,
        count: int,
        timeout: float = 10.0,
    ) -> None:
        """Wait for a specific number of events of a given type."""

        def condition():
            if event_type == "add":
                return len(self.added_items) >= count
            elif event_type == "update":
                return len(self.updated_items) >= count
            elif event_type == "delete":
                return len(self.deleted_items) >= count
            return False

        sync_wait_for_condition(
            condition, timeout=timeout, message=f"Waiting for {count} {event_type} events"
        )

    def clear(self):
        """Clear all recorded events."""
        self.added_items.clear()
        self.updated_items.clear()
        self.deleted_items.clear()
        self._add_event = False
        self._update_event = False
        self._delete_event = False
