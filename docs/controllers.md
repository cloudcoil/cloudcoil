# Controllers

A controller repeatedly converges current state. Start with one decorated function;
use [stages and cases](staged-controllers.md) when named progress or alternative
behaviors make the flow clearer. Application handles clients, watches, retry queues,
signals and cleanup.

```python
from cloudcoil.application import Application
from cloudcoil.controller import Context
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

app = Application("configmaps")
configs = app.controller(ConfigMap, label_selector="example.com/manage=true", workers=4)

@configs.reconcile(every=60)
async def reconcile(config: ConfigMap, ctx: Context[ConfigMap]) -> ConfigMap:
    config.data = {**(config.data or {}), "managed-by": "cloudcoil"}
    return config

if __name__ == "__main__":
    app.main()
```

A decorated handler takes `(resource)` or `(resource, ctx)`. The resource is a deep
copy of the present, non-deleting primary object; omit Context if unused. Events may
coalesce: handlers observe current state, not a history or an exactly-once stream.
Different keys can run concurrently, but one key never does. Handlers must tolerate
repeated execution and partial child writes.

## Choose the execution structure

| Structure | Use it for | What runs |
| --- | --- | --- |
| `@reconcile()` | Most controllers; ordinary guards and loops | One handler per pass |
| `@stage(condition=..., depends=...)` | Several responsibilities with visible progress | Every stage, in dependency order, until one waits or fails |
| `@case(when=..., after=...)` and `@otherwise()` | Mutually exclusive behavior | The first matching case, or the fallback |

A controller chooses one row. A stage can itself contain cases. Start with a
reconcile function and split it only when names and conditions make the flow
clearer. See [stages and reporting](staged-controllers.md) for ordering and outcomes.

## Registration and composition

For a reusable module, create `Controller(Model, owns=(...))`, decorate handlers,
then call `app.include(controller)`. Import that module before running the app;
there is no automatic module scanning. `app.controller(Model, ...)` creates and includes
the same group directly. Registrations perform no I/O. Manifest generation validates
completed definitions; startup freezes them. Duplicate inclusion and late registration
fail explicitly. A group has one reconciliation function, automatic stages, or cases.

## Watches and cached reads

Declare owned children with `owns=(ConfigMap, Deployment)`. Owner watches compare
parent group/kind/UID and support cluster-scoped owners with namespaced children.
For non-owning dependencies, register a mapper:

```python
from cloudcoil.controller import ResourceKey
from cloudcoil.models.kubernetes.core.v1 import Secret

@configs.watch(Secret)
def changed(secret: Secret) -> list[ResourceKey]:
    return [ResourceKey("settings", secret.namespace)]
```

Mappers are synchronous and must be fast and free of I/O. Updates map both old and
new versions, so removing a label or reference wakes former dependents. Mapper errors
stop the controller instead of losing events. The primary informer syncs before
secondary handlers, and every informer syncs before workers start.

Use `ctx.cached(Kind).get/list` for declared informer snapshots, `await ctx.get(Kind,
name)` for a live read, and `await ctx.client(Kind)` for full client operations.
Controller informers do not silently evict objects; scope and selectors control
memory. A missing cached object may have left the selected scope: it is not proof
that destructive cleanup is authorized. See [read contracts](reads.md).

## Managing children

`await ctx.ensure(ConfigMap(data={"message": "hello"}))` creates or converges an
owned child. Name and namespace default to the parent. Supply explicit metadata for
multiple children of the same kind; declare owns so child drift triggers repair.

Only supplied fields are managed: maps merge, lists replace, explicit None removes a
field, and omitted fields (including server-allocated Service IPs) survive. No-op
writes are skipped. Existing unrelated children cannot be adopted. UID/version
conflicts retry the whole reconciliation. Cross-namespace ownership is rejected.

There is no multi-resource transaction. Obsolete children require explicit guarded
deletion and corresponding RBAC. See the [child set example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/child_set.py).

## Returning resources and status

Return a modified primary resource to save successful spec/metadata/status edits.
Returning None does not save incidental primary edits. Explicit `ctx.set_status`
and `ctx.condition` reports are saved even on failure; see the [reporting contract](staged-controllers.md#status-helpers).
Unchanged values cause no PATCH. Use `Result(resource=obj, requeue_after=60)` for an
explicit per-pass timer, or `@reconcile(every=60)` for periodic successful passes.

All changes compare with an independent dispatch baseline, guarded by UID and
resourceVersion. They never rebase a stale desired snapshot over a new live read.
The returned object must have the same primary identity/version. Discovery sends
status to `/status` when present. Changes to main fields and status require two
non-atomic writes: a successful main write is not rolled back if status then conflicts.

Ordinary exceptions retry with backoff and jitter. `raise Wait("Pending", after=10)`
reports expected pending work; `TerminalError` suppresses automatic error retries.
Later inputs/resyncs still reconcile. `reconcile_timeout` bounds the callback and
its persistence; shutdown cancellation stops without writing a failure report.

## Finalizers

For a resource representing external state, pair provisioning and cleanup. This
excerpt assumes an `ExternalRecord` model and an idempotent provider adapter; see
the [complete finalizer example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/finalizers.py).

```python
records = app.controller(ExternalRecord)

@records.reconcile(every=60)
async def reconcile(record: ExternalRecord) -> None:
    assert record.metadata and record.metadata.uid
    await provider.put(record.metadata.uid, record.spec.value)

@records.finalize("example.com/external-record")
async def cleanup(record: ExternalRecord) -> None:
    assert record.metadata and record.metadata.uid
    await provider.delete(record.metadata.uid)
```

The runtime persists the finalizer before normal reconciliation, rechecks deletion,
and updates its write baseline after that live write. Deleting objects carrying the
finalizer enter cleanup instead. Cleanup errors retry and retain the finalizer;
success removes it. One finalizer handler owns this controller's cleanup; compose
multiple operations explicitly inside it. Cleanup must be idempotent and return None,
or raise Wait while pending. Cache absence never triggers destructive cleanup.

Use [application lifespans](lifespan.md) for process/leadership
resources; finalizers belong to individual Kubernetes objects.

## Next steps

- [Live clients and informer reads](reads.md)
- [Controller patterns](patterns.md)
- [Deploy an operator](operators.md)
- [Runtime, explicit writes and embedding](runtime.md)
