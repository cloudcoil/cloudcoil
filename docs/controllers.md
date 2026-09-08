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

## Registration and composition

For a reusable module, create `Controller(Model, owns=(...))`, decorate handlers,
then call `app.include(controller)`. `app.controller(Model, ...)` creates and includes
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

Use [application lifespans](operators.md#lifespan-decorators) for process/leadership
resources; finalizers belong to individual Kubernetes objects.

## Low-level embedding

The existing `Controller(Model, request_callback)` interface remains available.
Request contains an optional resource, name, namespace, key, Config and clients;
callers handle absence/deletion explicitly in that interface. Existing Stages/Cases
and immediate awaited Request.event calls retain their low-level contracts.

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

## Next steps

- [Live clients and informer reads](reads.md)
- [Controller patterns](patterns.md)
- [Deploy an operator](operators.md)
- [Runtime, leadership and observability](runtime.md)
