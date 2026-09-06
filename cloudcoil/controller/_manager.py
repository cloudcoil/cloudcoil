"""Structured lifecycle and shared watches for a group of controllers."""

import asyncio
from typing import Any

from cloudcoil._context import context
from cloudcoil.client import Config

from ._controller import Controller
from ._health import HealthServer
from ._informers import _InformerPool
from ._leader import LeaderElection
from ._metrics import _render


class Manager:
    """Run controllers together, sharing compatible watches and stopping on failure.

    Configs may be specified per controller, on the manager, or in the active
    context, in that order. Watch sharing never crosses Config instances. Each
    manager runs once and owns the shared informers until all workers have stopped.
    """

    def __init__(
        self,
        *controllers: Controller[Any],
        config: Config | None = None,
        leader_election: LeaderElection | None = None,
        health: HealthServer | None = None,
    ) -> None:
        if not controllers:
            raise ValueError("A manager needs at least one controller")
        if len({id(controller) for controller in controllers}) != len(controllers):
            raise ValueError("A controller cannot be registered twice")
        self._names = tuple(
            controller.name or f"{controller.resource.gvk().kind.lower()}-{index}"
            for index, controller in enumerate(controllers, 1)
        )
        if len(set(self._names)) != len(self._names):
            raise ValueError("Managed controllers must have distinct metric names")
        self.health = health
        self._running = False
        self._controllers = controllers
        self._config = config
        self.leader_election = leader_election
        self._pool = _InformerPool()
        self._used = False
        self._finished = asyncio.Event()
        self._failure: BaseException | None = None

    @property
    def ready(self) -> bool:
        return (
            self.healthy
            and (self.leader_election is None or self.leader_election.is_leader)
            and not self._finished.is_set()
            and all(controller.ready for controller in self._controllers)
        )

    @property
    def healthy(self) -> bool:
        """Running without fatal failure, including startup and standby."""
        return self._running and self._failure is None and not self._finished.is_set()

    def metrics(self) -> str:
        """Prometheus text exposition; local counters persist after shutdown."""
        return _render(self)

    @property
    def informer_count(self) -> int:
        """Number of distinct manager-owned watch subscriptions."""
        return self._pool.count

    async def wait_ready(self, timeout: float = 30) -> None:
        async def wait_controllers() -> None:
            async with asyncio.TaskGroup() as group:
                for controller in self._controllers:
                    group.create_task(controller.wait_ready(timeout))

        ready = asyncio.create_task(wait_controllers())
        finished = asyncio.create_task(self._finished.wait())
        try:
            async with asyncio.timeout(timeout):
                await asyncio.wait((ready, finished), return_when=asyncio.FIRST_COMPLETED)
            if self._failure is not None:
                raise self._failure
            if self._finished.is_set():
                raise RuntimeError("Manager stopped before becoming ready")
            await ready
            if not self.ready:
                raise RuntimeError("Manager stopped or lost leadership before becoming ready")
        finally:
            ready.cancel()
            finished.cancel()
            await asyncio.gather(ready, finished, return_exceptions=True)

    async def _prepare(self) -> None:
        if any(
            controller._used or controller._pool is not None for controller in self._controllers
        ):
            raise RuntimeError("Controllers must be unused and belong to only one manager")
        # Register every handler before starting any shared list/watch. Otherwise a
        # late subscriber could miss initial objects and events during registration.
        for controller in self._controllers:
            controller._pool = self._pool
            config = controller.config or self._config or context.active_config
            await controller._install(config)
            controller._prepared_config = config

    async def _run_controllers(self, stop: asyncio.Event | None) -> None:
        await self._prepare()
        async with asyncio.TaskGroup() as group:
            for controller in self._controllers:
                group.create_task(controller.run(stop=stop))

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Run until explicit stop, cancellation, or a fatal controller failure."""
        if self._used:
            raise RuntimeError("Manager instances can only run once")
        self._used = True
        self._running = True
        try:
            if self.health is not None:
                await self.health._start(self)
            stop = stop if stop is not None else asyncio.Event()
            if self.leader_election is None:
                if not stop.is_set():
                    await self._run_controllers(stop)
            else:
                config = (
                    self.leader_election.config
                    or self._config
                    or self._controllers[0].config
                    or context.active_config
                )
                await self.leader_election._run(
                    lambda: self._run_controllers(stop),
                    config=config,
                    stop=stop,
                )
        except BaseException as exc:
            self._failure = exc
            raise
        finally:
            self._running = False
            try:
                await self._pool.stop()
            finally:
                try:
                    if self.health is not None:
                        await self.health._close()
                finally:
                    self._finished.set()
