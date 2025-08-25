"""Private event dispatching abstraction for informers."""

import asyncio
import inspect
import logging
import threading
from typing import Any, Generic, List, Optional, TypeVar, Union

from cloudcoil.resources import Resource

from ._types import AsyncEventHandler, AsyncUpdateHandler, EventHandler, UpdateHandler

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class _AsyncEventDispatcher(Generic[T]):
    """Handles event dispatching for async informers with proper concurrency."""

    def __init__(self) -> None:
        self._add_handlers: List[Union[EventHandler, AsyncEventHandler]] = []
        self._update_handlers: List[Union[UpdateHandler, AsyncUpdateHandler]] = []
        self._delete_handlers: List[Union[EventHandler, AsyncEventHandler]] = []
        self._lock = asyncio.Lock()

    async def register_add_handler(self, handler: Union[EventHandler, AsyncEventHandler]) -> None:
        """Register an add event handler."""
        async with self._lock:
            self._add_handlers.append(handler)

    async def register_update_handler(
        self, handler: Union[UpdateHandler, AsyncUpdateHandler]
    ) -> None:
        """Register an update event handler."""
        async with self._lock:
            self._update_handlers.append(handler)

    async def register_delete_handler(
        self, handler: Union[EventHandler, AsyncEventHandler]
    ) -> None:
        """Register a delete event handler."""
        async with self._lock:
            self._delete_handlers.append(handler)

    async def dispatch_add(self, obj: T) -> None:
        """Dispatch add event to all handlers."""
        handlers = self._add_handlers.copy()  # Snapshot to avoid lock during dispatch
        await self._dispatch_to_handlers(handlers, obj)

    async def dispatch_update(self, old_obj: Optional[T], new_obj: T) -> None:
        """Dispatch update event to all handlers."""
        handlers = self._update_handlers.copy()
        await self._dispatch_to_update_handlers(handlers, old_obj, new_obj)

    async def dispatch_delete(self, obj: T) -> None:
        """Dispatch delete event to all handlers."""
        handlers = self._delete_handlers.copy()
        await self._dispatch_to_handlers(handlers, obj)

    async def _dispatch_to_handlers(
        self, handlers: List[Union[EventHandler, AsyncEventHandler]], obj: T
    ) -> None:
        """Dispatch event to handlers, handling both sync and async."""
        tasks: List[Any] = []

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    # Async handler - create task
                    tasks.append(asyncio.create_task(handler(obj)))
                else:
                    # Sync handler - run in executor to avoid blocking
                    # Use get_running_loop() which is the modern API
                    loop = asyncio.get_running_loop()
                    tasks.append(loop.run_in_executor(None, handler, obj))
            except Exception as e:
                logger.error("Error dispatching event to handler %s: %s", handler, e)

        # Wait for all handlers to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Handler error: %s", result)

    async def _dispatch_to_update_handlers(
        self,
        handlers: List[Union[UpdateHandler, AsyncUpdateHandler]],
        old_obj: Optional[T],
        new_obj: T,
    ) -> None:
        """Dispatch update event to handlers."""
        tasks: List[Any] = []

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(old_obj, new_obj)))
                else:
                    # Use get_running_loop() which is the modern API
                    loop = asyncio.get_running_loop()
                    tasks.append(loop.run_in_executor(None, handler, old_obj, new_obj))
            except Exception as e:
                logger.error("Error dispatching update to handler %s: %s", handler, e)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Update handler error: %s", result)


class _SyncEventDispatcher(Generic[T]):
    """Handles event dispatching for sync informers with proper thread safety."""

    def __init__(self) -> None:
        self._add_handlers: List[EventHandler] = []
        self._update_handlers: List[UpdateHandler] = []
        self._delete_handlers: List[EventHandler] = []
        self._lock = threading.RLock()

    def register_add_handler(self, handler: EventHandler) -> None:
        """Register an add event handler."""
        with self._lock:
            self._add_handlers.append(handler)

    def register_update_handler(self, handler: UpdateHandler) -> None:
        """Register an update event handler."""
        with self._lock:
            self._update_handlers.append(handler)

    def register_delete_handler(self, handler: EventHandler) -> None:
        """Register a delete event handler."""
        with self._lock:
            self._delete_handlers.append(handler)

    def dispatch_add(self, obj: T) -> None:
        """Dispatch add event to all handlers."""
        with self._lock:
            handlers = self._add_handlers.copy()

        for handler in handlers:
            try:
                handler(obj)
            except Exception as e:
                logger.error("Error in add handler %s: %s", handler, e)

    def dispatch_update(self, old_obj: Optional[T], new_obj: T) -> None:
        """Dispatch update event to all handlers."""
        with self._lock:
            handlers = self._update_handlers.copy()

        for handler in handlers:
            try:
                handler(old_obj, new_obj)
            except Exception as e:
                logger.error("Error in update handler %s: %s", handler, e)

    def dispatch_delete(self, obj: T) -> None:
        """Dispatch delete event to all handlers."""
        with self._lock:
            handlers = self._delete_handlers.copy()

        for handler in handlers:
            try:
                handler(obj)
            except Exception as e:
                logger.error("Error in delete handler %s: %s", handler, e)
