# Building controllers

Cloudcoil is growing an async controller framework around its typed resources and
informers. The goal is a small reconciliation API, with lifecycle and correctness
handled by the runtime. Progress is tracked in [#63](https://github.com/cloudcoil/cloudcoil/issues/63).

## Incremental roadmap

1. **Implemented — Workqueue:** deduplicated keys, one active worker per key, delayed requeues,
   capped exponential retries with jitter, cancellation, and shutdown.
2. **Implemented — Informer correctness:** enqueue initial state and relist changes, recover from
   expired resource versions, and reliably register handlers before startup.
3. **Implemented — Controller runtime:** typed reconciliation requests, concurrent workers,
   readiness, startup/shutdown, retries, child ownership watches, and custom maps.
4. **Partially implemented — Safe mutations:** guarded JSON Patch calculation,
   live-read mutation, status and finalizer helpers. Server-side apply and reusable
   ownership-setting helpers remain.
5. **Partially implemented — Production operation:** shared informers and Lease-based
   leader election. Metrics, health endpoints, and Kubernetes Event reporting remain.
6. **Later — Advanced framework:** admission webhooks, optional CEL validation, and
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
models. Standalone controllers own their informers; a Manager shares compatible watches. It lists
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
Manager shares informers only for the same Config instance, model class, namespace
scope, selectors, and timing settings. It registers all subscribers before starting
any watch, ensuring every controller sees initial objects. Different scopes or
Config instances stay separate. `manager.informer_count` exposes the actual watch
count. Supply `Manager(..., config=config)` as a default; a controller-specific Config
takes precedence.

## Leader election

Run multiple replicas with the same Lease name and namespace:

```python
from cloudcoil.controller import LeaderElection, Manager

manager = Manager(
    controller,
    config=config,
    leader_election=LeaderElection("configmap-mirror", namespace="default"),
)
await manager.run(stop=stop_event)
```

Only the elected manager starts informers and workers. Standbys wait without listing
watched resources, and `manager.ready` stays false until leadership and initial sync.
Use the default unique identity for each replica; never share an explicit identity
between live processes. Lease requests use the election's Config, then the manager's,
then the first controller's, then the active context. The Lease namespace defaults
to that Config's namespace. Resource watches retain their own Configs and scopes.

The service account needs `get`, `create`, and `update` on `leases` in API group
`coordination.k8s.io`, in the Lease namespace. Pre-creating the Lease allows omitting
`create` and restricting `get/update` with `resourceNames`. Kubernetes RBAC cannot
restrict `create` by resource name.

Defaults are `lease_duration=15`, `renew_deadline=10`, and `retry_period=2` seconds;
require `0 < retry_period < renew_deadline < lease_duration`. Writes compare
resourceVersion. Takeover waits for an unchanged record for the advertised duration,
measured with a local monotonic clock, rather than trusting another host's timestamp.
Explicit stop keeps renewal running while workers drain, then releases ownership.
Loss of ownership or renewal deadline cancels and joins workers, raises
`LeadershipLost`, and ends the manager; restart the process to participate again.
Fatal authorization errors propagate immediately. Failed release leaves the Lease to
expire; a successor's Lease is never deliberately cleared.

Lease election coordinates cooperative processes; it cannot fence a paused process
or an already-started external operation. Keep reconciliation idempotent and
cancellable, and use external fencing where side effects require it. This follows
the limitations described by [client-go leader election](https://pkg.go.dev/k8s.io/client-go/tools/leaderelection).
See also [Kubernetes Leases](https://kubernetes.io/docs/concepts/architecture/leases/).

## Optimistic changes and finalizers

Use `mutate` for a narrow update based on a **live, uncached** read:

```python
from cloudcoil.controller import mutate
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

async def mark_observed(resource: ConfigMap) -> ConfigMap:
    def change(current: ConfigMap) -> None:
        assert current.metadata is not None
        current.metadata.annotations = {
            **(current.metadata.annotations or {}),
            "example.com/observed": "true",
        }
    return await mutate(resource, change)
```

The callback edits a deep copy, must return `None`, and must not perform external
side effects. A no-op skips PATCH. Changes use JSON Patch with UID and resourceVersion
tests; conflicts propagate for reconciliation to retry from fresh state. A resource
recreated under the same name is rejected before invoking the callback. `status=True`
uses the status subresource and rejects changes outside status.

For explicit control, `cloudcoil.patches.diff(original, desired)` generates a guarded
patch between copies of one fetched resource. Apply it with
`await original.async_patch(operations)` or `original.patch(operations)`; both accept
`subresource="status"` and `dry_run=True`. Skip the write when the diff is empty.
`patches.json_patch(before_json, after_json)` calculates unguarded RFC 6902 patches
for arbitrary JSON values. Arrays are replaced atomically, object keys are diffed,
and JSON Pointer characters are escaped. No strategic-merge or field ownership is
inferred. [JSON Patch specification](https://www.rfc-editor.org/rfc/rfc6902).

`await ensure_finalizer(resource, "example.com/cleanup")` persists your finalizer
before provisioning external state; `await remove_finalizer(...)` removes only that
entry after successful cleanup. Both use live reads and UID/version tests, preserve
other controllers' finalizers, and skip no-op writes. Adding a missing finalizer
after deletion starts raises `TerminalError`.

Check deletionTimestamp before provisioning and again on the object returned by
ensure_finalizer. On deletion, run idempotent cleanup only if your finalizer is
present, then remove it. Kubernetes can mark deletion concurrently with any request;
finalizers coordinate cleanup, not exactly-once external operations. Never remove a
finalizer merely to bypass a failing cleanup. See [Kubernetes finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/).


## Runnable example and verification

[configmap_controller.py](https://github.com/cloudcoil/cloudcoil/blob/main/examples/configmap_controller.py)
mirrors ConfigMaps labelled `example.com/mirror=true` to owned `<name>-mirror`
ConfigMaps. It reconciles pre-existing sources, propagates source edits, repairs
child edits, and recreates deleted children. It refuses to adopt an unrelated object
and skips unchanged writes. Its namespaced service account needs `get/list/watch`,
`create`, and `patch` on ConfigMaps; scope the role to the example namespace.

From a checkout with dependencies installed and a kubeconfig pointing to your test
cluster, run `uv run python examples/configmap_controller.py --namespace default`.
Create a labelled source ConfigMap to observe the mirror. SIGINT/SIGTERM drain the
controller. This example assumes a Linux process, as used in Kubernetes containers.

Tests cover the queue, snapshot/watch recovery, retry and shutdown behavior, child
ownership, mapping changes, optimistic mutations, finalizers, and mypy/Pyright caller
inference. The CI matrix also runs the example reconciler against real Kubernetes
and checks UID/version preconditions and finalizer deletion behavior.
