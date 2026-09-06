"""A level-based reconcile loop over Cloudcoil informers."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Self

from cloudcoil._context import context
from cloudcoil.caching._informer import AsyncInformer
from cloudcoil.caching._types import InformerOptions
from cloudcoil.client import Config
from cloudcoil.resources import Resource

from ._queue import QueueClosed, WorkQueue
from ._types import Request, ResourceKey, Result, TerminalError

logger = logging.getLogger(__name__)

type Reconciler[T: Resource] = Callable[[Request[T]], Awaitable[Result | None]]
type Mapper[T: Resource] = Callable[[T], Iterable[ResourceKey]]


@dataclass
class _Watch:
    resource: type[Resource]
    mapper: Mapper[Any] | None = None  # None denotes a controller-owner watch.


class Controller[T: Resource]:
    """Reconcile one primary kind, with optional child and dependency watches.

    Configure watches before run(). Each instance runs once. The runtime owns its
    informers and worker tasks; Config ownership remains with the caller. Workers
    run only after every informer has synced. Failures retry with capped backoff;
    cancellation and fatal watch errors stop the controller and its sibling tasks.
    """

    def __init__(
        self,
        resource: type[T],
        reconcile: Reconciler[T],
        *,
        config: Config | None = None,
        namespace: str | None = None,
        all_namespaces: bool = False,
        label_selector: str | None = None,
        workers: int = 1,
        resync_period: float = 300,
        sync_timeout: float = 30,
        shutdown_timeout: float = 10,
        reconcile_timeout: float | None = None,
    ) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be a positive integer")
        for name, value in (
            ("sync_timeout", sync_timeout),
            ("shutdown_timeout", shutdown_timeout),
            ("reconcile_timeout", reconcile_timeout),
        ):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        self.resource = resource
        self.reconcile = reconcile
        self.config = config
        self._options = InformerOptions(
            namespace=namespace,
            all_namespaces=all_namespaces,
            label_selector=label_selector,
            resync_period=resync_period,
            max_items=0,
        )
        self._workers = workers
        self._sync_timeout = sync_timeout
        self._shutdown_timeout = shutdown_timeout
        self._reconcile_timeout = reconcile_timeout
        self._queue = WorkQueue[ResourceKey]()
        self._watches: list[_Watch] = []
        self._informers: list[AsyncInformer[Any]] = []
        self._primary: AsyncInformer[T] | None = None
        self._primary_namespaced = True
        self._used = False
        self._ready = asyncio.Event()
        self._finished = asyncio.Event()
        self._failure: BaseException | None = None

    def owns(self, resource: type[Resource]) -> Self:
        """Enqueue primary owners when a child changes (direct controller references).

        Owner matching uses group/kind and UID, including across served versions.
        For indirect or non-owning relationships use watch(..., mapper=...).
        """
        return self._add_watch(_Watch(resource))

    def watch[U: Resource](self, resource: type[U], *, mapper: Mapper[U]) -> Self:
        """Map secondary resources to primary keys; updates map both old and new state.

        Mappers run on the event loop and should be fast and free of I/O. A mapper
        failure stops the controller instead of silently losing a dependency event.
        """
        return self._add_watch(_Watch(resource, mapper))

    def _add_watch(self, watch: _Watch) -> Self:
        if self._used:
            raise RuntimeError("Configure watches before running the controller")
        self._watches.append(watch)
        return self

    def enqueue(self, key: ResourceKey) -> None:
        """Request a primary key explicitly, including from an external event source."""
        if not isinstance(key, ResourceKey):
            raise TypeError("enqueue expects a ResourceKey")
        self._queue.add(key)

    @property
    def ready(self) -> bool:
        """Whether all watches have synced and reconcile workers are running."""
        return self._ready.is_set()

    async def wait_ready(self, timeout: float = 30) -> None:
        """Wait for startup, propagating startup failure instead of hanging."""
        ready = asyncio.create_task(self._ready.wait())
        finished = asyncio.create_task(self._finished.wait())
        try:
            async with asyncio.timeout(timeout):
                await asyncio.wait((ready, finished), return_when=asyncio.FIRST_COMPLETED)
            if self._failure is not None:
                raise self._failure
            if not self.ready:
                raise RuntimeError("Controller stopped before becoming ready")
        finally:
            for task in (ready, finished):
                task.cancel()
            await asyncio.gather(ready, finished, return_exceptions=True)

    async def _enqueue_primary(self, obj: T) -> None:
        self.enqueue(ResourceKey.from_resource(obj))

    async def _update_primary(self, old: T | None, new: T) -> None:
        await self._enqueue_primary(new)

    def _owner_keys(self, obj: Resource) -> Iterable[ResourceKey]:
        if not obj.metadata or self._primary is None:
            return
        primary_gvk = self.resource.gvk()
        namespace = obj.namespace if self._primary_namespaced else None
        for ref in obj.metadata.owner_references or []:
            if not ref.controller or ref.kind != primary_gvk.kind:
                continue
            if ref.api_version.rpartition("/")[0] != primary_gvk.group:
                continue
            owner = self._primary.get(ref.name, namespace)
            if owner is not None and owner.metadata and owner.metadata.uid == ref.uid:
                yield ResourceKey(ref.name, namespace)

    async def _install(self, config: Config) -> None:
        primary_client = await config.async_client_for(self.resource, cached=False)
        self._primary_namespaced = primary_client.namespaced
        self._primary = AsyncInformer(primary_client, self._options)
        self._primary.on_add(self._enqueue_primary)
        self._primary.on_update(self._update_primary)
        self._primary.on_delete(self._enqueue_primary)
        self._informers.append(self._primary)
        for watch in self._watches:
            client = await config.async_client_for(watch.resource, cached=False)
            # A primary selector is not generally a selector for its dependencies.
            options = self._options.model_copy(update={"label_selector": None})
            # Cluster-scoped owners may have children in any namespace.
            if not self._primary_namespaced and client.namespaced:
                options = options.model_copy(update={"namespace": None, "all_namespaces": True})
            informer = AsyncInformer(client, options)
            mapper = watch.mapper or self._owner_keys

            async def changed(obj: Resource, mapper: Mapper[Any] = mapper) -> None:
                try:
                    # Validate the entire mapping before enqueueing a partial result.
                    keys = list(mapper(obj.model_copy(deep=True)))
                    if not all(isinstance(key, ResourceKey) for key in keys):
                        raise TypeError("Watch mappers must return ResourceKey values")
                    for key in keys:
                        self.enqueue(key)
                except Exception as exc:
                    self._failure = exc
                    self._mapping_failed.set()

            async def updated(old: Resource | None, new: Resource, changed: Any = changed) -> None:
                if old is not None:
                    await changed(old)
                await changed(new)

            informer.on_add(changed)
            informer.on_delete(changed)
            informer.on_update(updated)
            self._informers.append(informer)

    async def _sync(self) -> None:
        async with asyncio.timeout(self._sync_timeout):
            # Primary sync first makes owner UID checks meaningful for secondary lists.
            for informer in self._informers:
                await informer._start()
                assert informer._watch._task is not None
                waiter = asyncio.create_task(informer._sync_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        (waiter, informer._watch._task), return_when=asyncio.FIRST_COMPLETED
                    )
                    if informer._watch._task in done:
                        raise informer._watch._error or RuntimeError("Informer stopped before sync")
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)

    async def _worker(self) -> None:
        assert self._primary is not None
        while True:
            try:
                key = await self._queue.get()
            except QueueClosed:
                return
            try:
                resource = self._primary.get(key.name, key.namespace)
                request = Request(
                    key, resource.model_copy(deep=True) if resource is not None else None
                )
                async with asyncio.timeout(self._reconcile_timeout):
                    result = await self.reconcile(request)
                if result is not None and not isinstance(result, Result):
                    raise TypeError("Reconcile must return Result or None")
                self._queue.forget(key)
                if result is not None and result.requeue_after is not None:
                    self._queue.add_after(key, result.requeue_after)
            except TerminalError:
                self._queue.forget(key)
                logger.exception(
                    "Terminal reconcile error for %s %s", self.resource.gvk().kind, key
                )
            except Exception:
                delay = self._queue.retry(key)
                logger.exception(
                    "Reconcile failed for %s %s; retry in %.2fs",
                    self.resource.gvk().kind,
                    key,
                    delay,
                )
            finally:
                self._queue.done(key)

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Run until stop is set or the caller cancels; drain on an explicit stop.

        An explicit stop drains accepted ready work up to shutdown_timeout, then
        cancels remaining workers. Cancellation/fatal errors cancel workers directly.
        Delayed retries are discarded; the next process recovers by listing state.
        """
        if self._used:
            raise RuntimeError("Controller instances can only run once")
        self._used = True
        stop = stop if stop is not None else asyncio.Event()
        self._mapping_failed = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []
        workers: list[asyncio.Task[None]] = []
        graceful = False
        try:
            config = self.config or context.active_config
            async with config:
                try:
                    await self._install(config)
                    sync = asyncio.create_task(self._sync())
                    stopped = asyncio.create_task(stop.wait())
                    mapping_failed = asyncio.create_task(self._mapping_failed.wait())
                    tasks.extend((sync, stopped, mapping_failed))
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    if stopped in done:
                        graceful = True
                        return
                    if mapping_failed in done:
                        raise self._failure or RuntimeError("Watch mapping failed")
                    await sync
                    workers = [asyncio.create_task(self._worker()) for _ in range(self._workers)]
                    tasks.extend(workers)
                    self._ready.set()
                    watches = [
                        i._watch._task for i in self._informers if i._watch._task is not None
                    ]
                    done, _ = await asyncio.wait(
                        [stopped, mapping_failed, *workers, *watches],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if mapping_failed in done:
                        raise self._failure or RuntimeError("Watch mapping failed")
                    if stopped in done:
                        graceful = True
                    else:
                        for informer in self._informers:
                            if informer._watch._error is not None:
                                raise informer._watch._error
                        for worker in workers:
                            if worker in done:
                                await worker
                        raise RuntimeError("Controller task stopped unexpectedly")
                finally:
                    self._ready.clear()
                    # Stop startup before stopping informers it might still create.
                    for task in tasks:
                        if task not in workers:
                            task.cancel()
                    await asyncio.gather(
                        *(task for task in tasks if task not in workers), return_exceptions=True
                    )
                    for informer in reversed(self._informers):
                        await informer._stop()
                    self._queue.shutdown(immediate=not graceful)
                    if graceful and workers:
                        try:
                            async with asyncio.timeout(self._shutdown_timeout):
                                await asyncio.gather(*workers)
                        except TimeoutError:
                            pass
                    for worker in workers:
                        worker.cancel()
                    await asyncio.gather(*workers, return_exceptions=True)
        except BaseException as exc:
            self._failure = exc
            raise
        finally:
            self._queue.shutdown(immediate=True)
            self._finished.set()
