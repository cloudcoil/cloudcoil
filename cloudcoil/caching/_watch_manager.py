"""Private watch management abstraction for informers."""

import asyncio
import logging
import random
import threading
from typing import Any, Awaitable, Callable, Generic, List, Optional, TypeVar

from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.resources import Resource

from ._types import InformerOptions, InformerState

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)

# Type aliases for callbacks
AsyncItemsCallback = Callable[[List[T], str], Awaitable[None]]
AsyncEventCallback = Callable[[str, Any], Awaitable[None]]
SyncItemsCallback = Callable[[List[T], str], None]
SyncEventCallback = Callable[[str, Any], None]


class _AsyncWatchManager(Generic[T]):
    """Manages the watch loop for async informers with proper concurrency patterns."""

    def __init__(
        self,
        client: AsyncAPIClient[T],
        options: InformerOptions,
        on_items_callback: AsyncItemsCallback[T],
        on_event_callback: AsyncEventCallback,
    ):
        self._client = client
        self._options = options
        self._on_items = on_items_callback
        self._on_event = on_event_callback

        # State management
        self._state = InformerState.STOPPED
        self._task: Optional[asyncio.Task] = None
        self._resource_version: Optional[str] = None
        self._stop_event = asyncio.Event()

        # Exponential backoff with jitter
        self._backoff = _ExponentialBackoff()

    async def start(self) -> None:
        """Start the watch loop."""
        if self._state != InformerState.STOPPED:
            return

        self._state = InformerState.STARTING
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the watch loop gracefully."""
        if self._state in (InformerState.STOPPED, InformerState.STOPPING):
            return

        self._state = InformerState.STOPPING
        self._stop_event.set()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._state = InformerState.STOPPED

    async def _run(self) -> None:
        """Main watch loop with error recovery."""
        while not self._stop_event.is_set():
            try:
                # Initial list if needed
                if self._resource_version is None:
                    await self._initial_list()

                # Watch for changes
                await self._watch()

                # Reset backoff on success
                self._backoff.reset()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Watch error for %s: %s", self._client.kind.__name__, e)

                if self._state == InformerState.STARTING:
                    self._state = InformerState.FAILED
                    break

                # Wait with exponential backoff
                delay = self._backoff.next_delay()
                await asyncio.sleep(delay)

    async def _initial_list(self) -> None:
        """Perform initial resource listing."""
        logger.debug("Initial list for %s", self._client.kind.__name__)

        resource_list = await self._client.list(
            namespace=self._options.namespace,
            all_namespaces=self._options.all_namespaces,
            label_selector=self._options.label_selector,
            field_selector=self._options.field_selector,
            limit=self._options.page_size,
        )

        items = resource_list.items if hasattr(resource_list, "items") else []

        # Store resource version for watch
        if hasattr(resource_list, "metadata") and resource_list.metadata:
            self._resource_version = resource_list.metadata.resource_version

        # Notify about initial items
        await self._on_items(items, self._resource_version or "")

        if self._state == InformerState.STARTING:
            self._state = InformerState.RUNNING

    async def _watch(self) -> None:
        """Watch for resource changes."""
        async for event_type, event_obj in self._client.watch(
            namespace=self._options.namespace,
            all_namespaces=self._options.all_namespaces,
            label_selector=self._options.label_selector,
            field_selector=self._options.field_selector,
            resource_version=self._resource_version,
            timeout_seconds=self._options.timeout_seconds,
        ):
            if self._stop_event.is_set():
                break

            # Update resource version
            if hasattr(event_obj, "metadata") and event_obj.metadata:
                self._resource_version = event_obj.metadata.resource_version

            # Handle event
            await self._on_event(event_type, event_obj)

    @property
    def is_running(self) -> bool:
        """Check if watch is running."""
        return self._state == InformerState.RUNNING


class _SyncWatchManager(Generic[T]):
    """Manages the watch loop for sync informers with proper threading patterns."""

    def __init__(
        self,
        client: APIClient[T],
        options: InformerOptions,
        on_items_callback: SyncItemsCallback[T],
        on_event_callback: SyncEventCallback,
    ):
        self._client = client
        self._options = options
        self._on_items = on_items_callback
        self._on_event = on_event_callback

        # State management with proper locking
        self._state = InformerState.STOPPED
        self._state_lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._resource_version: Optional[str] = None

        # Exponential backoff
        self._backoff = _ExponentialBackoff()

    def start(self) -> None:
        """Start the watch thread."""
        with self._state_lock:
            if self._state != InformerState.STOPPED:
                return

            self._state = InformerState.STARTING
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._run,
                name=f"watch-{self._client.kind.__name__}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the watch thread gracefully."""
        with self._state_lock:
            if self._state in (InformerState.STOPPED, InformerState.STOPPING):
                return

            self._state = InformerState.STOPPING
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        with self._state_lock:
            self._state = InformerState.STOPPED

    def _run(self) -> None:
        """Main watch loop with error recovery."""
        while not self._stop_event.is_set():
            try:
                # Initial list if needed
                if self._resource_version is None:
                    self._initial_list()

                # Watch for changes
                self._watch()

                # Reset backoff on success
                self._backoff.reset()

            except Exception as e:
                logger.error("Watch error for %s: %s", self._client.kind.__name__, e)

                with self._state_lock:
                    if self._state == InformerState.STARTING:
                        self._state = InformerState.FAILED
                        break

                # Wait with exponential backoff
                delay = self._backoff.next_delay()
                self._stop_event.wait(delay)

    def _initial_list(self) -> None:
        """Perform initial resource listing."""
        logger.debug("Initial list for %s", self._client.kind.__name__)

        resource_list = self._client.list(
            namespace=self._options.namespace,
            all_namespaces=self._options.all_namespaces,
            label_selector=self._options.label_selector,
            field_selector=self._options.field_selector,
            limit=self._options.page_size,
        )

        items = resource_list.items if hasattr(resource_list, "items") else []

        # Store resource version
        if hasattr(resource_list, "metadata") and resource_list.metadata:
            self._resource_version = resource_list.metadata.resource_version

        # Notify about initial items
        self._on_items(items, self._resource_version or "")

        with self._state_lock:
            if self._state == InformerState.STARTING:
                self._state = InformerState.RUNNING

    def _watch(self) -> None:
        """Watch for resource changes."""
        for event_type, event_obj in self._client.watch(
            namespace=self._options.namespace,
            all_namespaces=self._options.all_namespaces,
            label_selector=self._options.label_selector,
            field_selector=self._options.field_selector,
            resource_version=self._resource_version,
            timeout_seconds=self._options.timeout_seconds,
        ):
            if self._stop_event.is_set():
                break

            # Update resource version
            if hasattr(event_obj, "metadata") and event_obj.metadata:
                self._resource_version = event_obj.metadata.resource_version

            # Handle event
            self._on_event(event_type, event_obj)

    @property
    def is_running(self) -> bool:
        """Check if watch is running."""
        with self._state_lock:
            return self._state == InformerState.RUNNING


class _ExponentialBackoff:
    """Exponential backoff with jitter for retry logic."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 300.0,
        multiplier: float = 2.0,
        jitter: float = 0.1,
    ):
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._multiplier = multiplier
        self._jitter = jitter
        self._current_delay = initial_delay

    def next_delay(self) -> float:
        """Get next delay with exponential backoff and jitter."""
        delay = self._current_delay

        # Add jitter (±10% by default)
        jitter_amount = delay * self._jitter
        delay += random.uniform(-jitter_amount, jitter_amount)

        # Update for next time
        self._current_delay = min(self._current_delay * self._multiplier, self._max_delay)

        return max(0, delay)

    def reset(self) -> None:
        """Reset backoff to initial delay."""
        self._current_delay = self._initial_delay
