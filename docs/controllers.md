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
