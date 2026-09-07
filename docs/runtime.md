# Runtime and observability

`Application` configures this runtime for ordinary applications. Use the lower-level
APIs here when embedding controllers or tuning their lifecycle.

## Controller and manager lifecycle

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
