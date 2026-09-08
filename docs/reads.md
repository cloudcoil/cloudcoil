# Live clients and informer reads

Controller Context and AdmissionRequest both expose explicit live clients and caches.
In a decorated controller:

```python
# Live API access to any kind; async, using the shared Config.
client = await ctx.client(ConfigMap)
config = await client.get("settings")

# Local snapshots from an already registered informer; synchronous.
config = ctx.cached(ConfigMap).get("settings")
pods = ctx.cached(Pod).list(labels={"app": "web"})
```

| Read | Source | Missing object | Scope |
| --- | --- | --- | --- |
| `await client.get(...)` | API server | `ResourceNotFound` | Client/request namespace; explicit overrides allowed |
| `cached.get(...)` | Informer snapshot | `None` | Registered watch scope and selectors |
| `cached.list(...)` | Informer snapshot | Empty list | Registered watch scope, then local filtering |

Live clients share the operator's connections. Handlers do not open or close
transports. A namespace argument on an operation overrides the request namespace;
it does not mutate the shared Config. Declare extra API permissions with
[`RBACRule`](operators.md#resources-and-permissions).

## Controller informers

The primary kind is registered automatically. Use `owns=(ChildKind, ...)` for
owned children, or `@controller.watch(DependencyKind)` for unowned dependencies.
A mapper can list `controller.cached(PrimaryKind)` to find affected parents.
The primary informer syncs before secondary handlers start. Updates map both old
and new objects, so removing a label or reference also reconciles former dependents.

The [dependency rollout](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/dependency_rollout.py)
cache-gets referenced ConfigMaps and reverse-maps their changes to Deployments.
The [Workload summary](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/workload_summary.py)
cache-lists existing Pods by labels and updates CR status without owning those Pods.

For a watch used only for reads, `.watch(Kind, mapper=lambda obj: [])` registers
its informer without scheduling primary work on its events. Use this only when
another event or periodic reconciliation makes those changes observable to your
application. If the primary kind is also a child kind, `cached(PrimaryKind)` refers
to the primary selector, not the broader child watch.

## Snapshot semantics

- Reads require a running, synced informer. An unwatched kind raises `ValueError`;
  unavailable or failed informers raise `RuntimeError`.
- Reads never call the API server or silently fall back. Missing objects may be
  absent, outside the selector, or not yet observed.
- Returned objects are deep copies. Editing them does not corrupt the informer.
- Lists are eventually consistent linear scans with exact AND label matching.
  They are not indexed joins, paginated API queries or atomic multi-object snapshots.
- `namespace=` overrides the default. `all_namespaces=True` includes all *watched*
  namespaces; it cannot expand the watch's scope.

Controller informers do not silently evict objects. Use selectors and namespace
scope to control memory. For destructive operations derived from a snapshot, check
live state or send identity/version preconditions. The
[child pruning example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/child_set.py)
checks ownership and supplies UID/resourceVersion guards to DELETE.

## Admission caches

Admission serves on every replica, including controller standbys. It cannot depend
on the leader's controller informers. Configure a separate cache on the operator:

```python
from cloudcoil.caching import Cache
from cloudcoil.models.kubernetes.core.v1 import Namespace
from cloudcoil.application import Application
from cloudcoil.application import RBACRule, WebhookServer

app = Application(
    "namespace-policy",
    cache=Cache(
        resources=[Namespace],
        mode="strict",
        wait_for_sync=True,
        max_items_per_resource=0,
    ),
    rules=(RBACRule(Namespace, ("get", "list", "watch")),),
    webhook=WebhookServer(tls_secret="namespace-policy-tls"),
)
```

Register policies with @app.validate(Model) or @app.mutate(Model).
Each replica syncs this cache before serving. `request.cached(Kind)` requires the
kind in `Cache.resources`. Use one configured namespace or `namespaces=None` for
all namespaces. `max_items_per_resource=0` disables eviction. If you pass an explicit
`Config`, configure its cache there instead of also passing `Application(cache=...)`.

A cache miss is not proof of absence. The
[cached admission example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_cached.py)
falls back to a live read on misses; hits can still be stale. Use live reads for
policies that must reflect current state. Neither cache nor live reads make
cross-resource policy checks and admission persistence an atomic transaction.
Callbacks must not write external state, including on dry runs.

See [client caching](caching.md) for cached resource methods and direct informer
subscriptions outside the operator runtime.

