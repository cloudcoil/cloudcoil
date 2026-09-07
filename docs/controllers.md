# Controllers

A reconciler reads the latest state and returns changes. `Application.main()` handles
configuration, watches, retries, signals and cleanup. Start with the
[quickstart](getting-started.md#write-a-controller) or browse the [patterns](patterns.md).

## Reconciliation runtime

```python
from cloudcoil.controller import Controller, Request, Result
from cloudcoil.application import Application
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Secret

async def reconcile(request: Request[ConfigMap]) -> Result | None:
    if request.resource is None:
        return
    print(request.namespace, request.name, request.resource.data)
    return Result(requeue_after=60)

app = Application("configmaps", Controller(ConfigMap, reconcile, workers=4))

if __name__ == "__main__":
    app.main()

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

`.owns(ChildType, OtherChildType, ...)` watches direct controller-owner references, comparing group,
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

## Managing children

Use `await request.ensure(ConfigMap(data={"message": "hello"}))` to create or
converge an owned child. Name and namespace default to the parent. Supply metadata
explicitly for multiple children of the same kind. Pair this with `.owns(ConfigMap)`
to repair drift and recreate deleted children from watch events.

Only supplied fields are managed: maps merge, lists replace, explicit `None`
removes a field, and omitted fields (including server-allocated Service IPs) survive.
No-op reconciliation performs no patch. Updates test UID and resourceVersion;
conflicts retry the entire reconciler. An existing child with another owner is
never adopted. Cross-namespace ownership is rejected. No child is written while
the parent is deleting; parent deletion uses Kubernetes garbage collection.

Children are written sequentially, without a multi-resource transaction. A retry
converges partially completed work. Obsolete children are not automatically pruned;
delete them explicitly with a client and declare delete access when required.

For arbitrary reads, both reconciliation and admission use
`client = await request.client(OtherResource)`. The client shares the operator's
connection and defaults to this request's namespace; pass a namespace to operations
for cross-namespace reads. Admission handlers must only read.

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

## Next steps

- [Live clients and informer reads](reads.md)
- [Controller patterns](patterns.md)
- [Deploy an operator](operators.md)
- [Runtime, leadership and observability](runtime.md)
