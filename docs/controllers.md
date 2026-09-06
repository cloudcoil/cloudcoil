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
5. **Partially implemented — Production operation:** shared informers, Lease-based
   leader election, metrics, and health endpoints. Kubernetes Event reporting remains.
6. **Partially implemented — Extension authoring:** model-driven CRD generation and
   typed mutating/validating admission webhooks. Conversion webhooks, local CEL
   evaluation, and multi-resource YAML application remain later milestones.

See [Custom resources and admission](custom-resources.md) to define one resource
model for schema generation, reconciliation, and admission.

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

Return a modified primary resource to persist its changes automatically, or use
`Result(resource=resource, requeue_after=seconds)` to save and schedule another pass.
Return `None`/`Result()` for success without a write, or `Result(requeue_after=seconds)`
to check again without a write. See the write contract below.
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

## Health and metrics

```python
from cloudcoil.controller import HealthServer, Manager

manager = Manager(controller, health=HealthServer(host="0.0.0.0", port=8080))
await manager.run(stop=stop_event)
```

The optional listener starts before election and initial sync, and closes with the
manager. No server is started by default. `HealthServer()` binds loopback; use an
explicit container interface for Kubernetes probes. Bind failures stop startup.

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` | 200 while running, including startup and standby; 503 after fatal failure while shutting down. |
| `GET /readyz` | 200 after every controller syncs and leadership is held when enabled; otherwise 503. |
| `GET /metrics` | Prometheus text format, including on standby. |

Use `/healthz` for liveness and `/readyz` for readiness. Standby replicas are
intentionally unready: do not use readiness to restart them. The listener is plain
HTTP without authentication; use your Pod/network access controls. It only serves
these GET routes, closes each connection, and bounds header size and read time.
`health.address` exposes the bound address (`port=0` requests an available port).

`manager.healthy`, `manager.ready`, and `manager.metrics()` also work without an HTTP
server, allowing integration with an existing application. `controller.status`
returns an immutable snapshot of readiness, queued/processing/delayed keys, completed
successes/errors/terminal errors/cancellations, and total reconcile duration.

Metrics include manager readiness and informer count, leadership acquisitions and
transient renewal failures, queue depth, active workers, delayed keys, reconcile
outcomes, and a duration histogram in seconds. Counters are local to each instance,
reset on recreation, and remain inspectable after shutdown. Duration includes failed
and cancelled attempts; active attempts enter counters only when they finish.

Set `Controller(..., name="configmap-mirror")` for a stable metric label. Names must
be unique within a manager; unnamed controllers receive `<kind>-<position>` labels.
No object names, namespaces, UIDs, or error messages become metric labels. Scrape
instances separately, and sum/rate their counters as appropriate. Queue depth counts
waiting keys, excluding keys currently processing and pending timers.

## Returning resources and status

Returning the primary resource is the simplest way to save changes:

```python
async def reconcile(request: Request[ConfigMap]) -> ConfigMap | None:
    resource = request.resource
    if resource is None:
        return None
    resource.data = {**(resource.data or {}), "managed-by": "cloudcoil"}
    return resource
```

The runtime retains an independent snapshot from dispatch, compares the returned
resource against it, and sends only changed fields as JSON Patch. Editing
`request.resource` and returning `None` does **not** save. Unchanged returned resources
produce no request, avoiding a write loop when the controller sees its own updates.
All writes test UID and resourceVersion; conflicts retry the **whole reconciliation**
against the latest cached state. The runtime never rebases a stale desired snapshot
onto a fresh object, which could remove another writer's changes.

Status works the same way for generated built-in and CRD models:

```python
# MyResource is your generated CRD model, with the status fields defined by its schema.
async def reconcile(request: Request[MyResource]) -> MyResource | None:
    resource = request.resource
    if resource is None:
        return None
    resource.status = MyResourceStatus(phase="Ready")
    return resource
```

API discovery determines whether `/status` exists. When it does, status changes go
there; ordinary fields go to the main endpoint. A status-only return sends one
status PATCH. Changes to both use **two non-atomic writes**, main first, then status
with the resourceVersion returned by the first write. If status changes unexpectedly
in that response, or the second write conflicts, reconciliation retries; an already
successful main write is not rolled back. CRDs without a status subresource persist
inline status through the main endpoint. Grant `patch` on `<plural>/status` as well
as `<plural>` when both are used. Stable status values are essential: timestamps
updated on every pass will intentionally produce a write loop.

The return value must be the same primary kind, name, namespace, UID, and version as
the request snapshot. This updates existing resources; it does not create an absent
resource, adopt a replacement UID, or save arbitrary child resources. Use resource
creation APIs and `mutate(child, ...)` for children. Resource writes and the callback
share `reconcile_timeout`; the runtime records success and schedules a requested
requeue only after patches succeed. Arrays are replaced as whole fields, guarded by
the version check; this is JSON Patch, not server-side apply or field ownership.

Use `Result(resource=resource, requeue_after=60)` to combine saving with a timer.
Use explicit helpers when you need to observe a write response, persist a finalizer
**before** an external side effect, or make a change based on a live read. After an
explicit write, return `None` or a scheduling-only `Result`; do not return the saved
object against the older request snapshot. Likewise, do not mix explicit primary
writes and automatic returned-primary writes within one attempt.

## Optimistic changes and finalizers

For explicit writes, use `mutate` for a narrow update based on a **live, uncached** read:

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
Add `--lease configmap-mirror --health-port 8080` when running replicas with probes
and metrics. All replicas must use the same Lease name and namespace and receive the
Lease permissions described above. Set the Pod termination grace period above
`shutdown_timeout + retry_period` (12 seconds with defaults), with additional room
for process overhead. Create a labelled source ConfigMap to observe the mirror.
SIGINT/SIGTERM drain the controller. This example assumes a Linux process, as used in Kubernetes containers.

Tests cover the queue, snapshot/watch recovery, retry and shutdown behavior, child
ownership, mapping changes, optimistic mutations, finalizers, and mypy/Pyright caller
inference. The CI matrix also runs the example reconciler against real Kubernetes
and checks UID/version preconditions, finalizer deletion, shared subscriptions, and
Lease handoff between managers, and returned CRD spec/status patches without a write loop.
