"""Structured lifecycle for a group of controllers."""

import asyncio
from typing import Any

from ._controller import Controller


class Manager:
    """Run controllers together; one fatal failure cancels and joins its siblings.

    Configs are supplied to controllers or inherited from the active context.
    This manages process lifecycle, not leader election or shared informer caches.
    """

    def __init__(self, *controllers: Controller[Any]) -> None:
        if not controllers:
            raise ValueError("A manager needs at least one controller")
        if len({id(controller) for controller in controllers}) != len(controllers):
            raise ValueError("A controller cannot be registered twice")
        self._controllers = controllers

    @property
    def ready(self) -> bool:
        return all(controller.ready for controller in self._controllers)

    async def wait_ready(self, timeout: float = 30) -> None:
        async with asyncio.TaskGroup() as group:
            for controller in self._controllers:
                group.create_task(controller.wait_ready(timeout))

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Run until explicit stop, cancellation, or a fatal controller failure."""
        async with asyncio.TaskGroup() as group:
            for controller in self._controllers:
                group.create_task(controller.run(stop=stop))
