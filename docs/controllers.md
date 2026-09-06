# Building controllers

Cloudcoil is growing an async controller framework around its typed resources and
informers. The goal is a small reconciliation API, with lifecycle and correctness
handled by the runtime. Progress is tracked in [#63](https://github.com/cloudcoil/cloudcoil/issues/63).

## Incremental roadmap

1. **Workqueue:** deduplicated keys, one active worker per key, delayed requeues,
   capped exponential retries with jitter, cancellation, and shutdown.
2. **Informer correctness:** enqueue initial state and relist changes, recover from
   expired resource versions, and reliably register handlers before startup.
3. **Controller runtime:** typed reconciliation requests, concurrent workers,
   readiness, startup/shutdown, retries, child ownership watches, and custom maps.
4. **Safe mutations:** patch calculation, conflict handling, status and finalizer
   helpers, and declarative ownership.
5. **Production operation:** shared informer management, leader election with
   Leases, metrics, health endpoints, and Kubernetes Event reporting.
6. **Advanced framework:** admission webhooks, optional CEL validation, and
   multi-resource YAML application. These remain separate from the reconcile loop.

## Workqueue

`cloudcoil.controller.WorkQueue[K]` is an in-memory queue for hashable keys. All
operations run on one asyncio event loop. `add(key)` coalesces repeated events;
`await get()` reserves a key until `done(key)`. An event arriving during processing
schedules another pass without allowing concurrent processing of that key.

Use `retry(key)` after a failure, `forget(key)` after success, and
`add_after(key, seconds)` for explicit periodic work. A fresh event supersedes a
pending delay. Timers are coalesced per key and do not create sleeping tasks.
Always call `done` in `finally`, including when a worker is cancelled.

`shutdown()` stops accepting new work and discards delayed retries while allowing
ready work to drain. `shutdown(immediate=True)` also discards ready work. Neither
cancels in-flight work; the caller owns worker tasks. `await join()` waits for
accepted work to finish. Keys are not persisted: a controller must list current
state on startup to recover after process restarts.

## Reconciliation runtime

```python
import asyncio

from cloudcoil.client import Config
from cloudcoil.controller import Controller, Request, Result
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Secret


async def reconcile(request: Request[ConfigMap]) -> Result | None:
    resource = request.resource
    if resource is None:
        return  # Absent from this controller's watched scope.
    print(request.namespace, request.name, resource.data)
    return Result(requeue_after=60)


async def main():
    config = Config()
    controller = Controller(
        ConfigMap, reconcile, config=config,
        namespace="default", label_selector="app=example", workers=4,
    ).owns(Secret)
    await controller.run()


asyncio.run(main())
```

`Controller(ResourceType, reconcile, ...)` works with generated Kubernetes and CRD
models. Each controller owns its own primary and secondary informers; it lists
before watching and waits for **all** initial snapshots before starting workers.
There is no silent cache eviction in controller informers. Scope selection limits
memory and list/watch permissions; secondary watches do not inherit the primary
label selector. Resync periodically relists and enqueues unchanged objects too.

A `Request[T]` contains `name`, `namespace`, `key`, and an independent deep copy of
the latest cached `resource: T | None`. Reconciliation is level-based: events may
coalesce and no event history or exactly-once execution is promised. Writes must
be idempotent and use optimistic concurrency. A missing object may have left a
label-selected scope; it is not sufficient evidence for destructive external
cleanup. Use finalizers and a live read for external deletion workflows.

Return `None`/`Result()` on success or `Result(requeue_after=seconds)` to check again.
Exceptions are logged and retried with exponential backoff (1s base, 60s cap, 10%
jitter). `TerminalError` suppresses that retry; future events/resyncs still run.
`reconcile_timeout=` optionally limits each attempt. A fresh event takes priority
over a delayed retry. Different keys can run concurrently; one key never does.

`.owns(ChildType)` watches direct controller-owner references, comparing group,
kind, and UID. It handles cluster-scoped owners and children across namespaces.
Use `.watch(OtherType, mapper=...)` for indirect or non-owning dependencies:

```python
from cloudcoil.controller import ResourceKey

controller.watch(
    Secret,
    mapper=lambda secret: [ResourceKey("settings", secret.namespace)],
)
```

Mappers return primary keys, run on the event loop, and must be fast and free of
I/O. Updates map both old and new state so removing or changing a dependency also
reconciles its former target. Mapping failures stop the controller and propagate.
Register watches before running. `controller.enqueue(key)` accepts external
signals from the same event loop.

`await controller.run(stop=stop_event)` drains ready work on explicit stop up to
`shutdown_timeout` (10s by default), discards delayed retries, and cancels unfinished
workers. Task cancellation stops immediately and joins watch/worker tasks. Callbacks
must cooperate with asyncio cancellation. Instances run once; create a new instance
to restart. The runtime activates the supplied/ambient Config; callers own its HTTP
clients. `controller.ready` and `await controller.wait_ready()` expose readiness and
startup failures. Fatal watch errors propagate rather than leaving a ready zombie.

`Manager(controller_a, controller_b)` runs controllers with a shared lifetime:
`await manager.run(stop=stop_event)` and `await manager.wait_ready()` have matching
semantics. A fatal failure cancels siblings and propagates as an `ExceptionGroup`.
This is process lifecycle management; informer sharing and leader election are
future milestones. Run one active process for each controller until leader election
is implemented, or supply external coordination.
