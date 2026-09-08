# Working with resources

Every generated Kubernetes model and handwritten `Resource` subclass has typed
client operations. Use constructors or builders to create local values, then call
an API method explicitly. The [quickstart](getting-started.md) covers installation.

## Configure and read

```python
from cloudcoil.client import Config
from cloudcoil.models.kubernetes.core.v1 import Pod, Service

with Config(namespace="default"):
    service = Service.get("kubernetes")
    for pod in Pod.list():
        print(pod.name)
```

Config uses kubeconfig locally or ServiceAccount credentials in a Pod. Supply
`kubeconfig="dev-cluster.yaml"` to choose a file. A context makes that configuration
active and manages its lifetime. An explicit `namespace=` on a request overrides
the context's default.

Async code enters `async with config` and uses `async_` resource methods:

```python
async def pod_names() -> list[str | None]:
    async with Config(namespace="default"):
        pods = await Pod.async_list()
        return [pod.name async for pod in pods]
```

Iterating a ResourceList follows server continuation tokens. `.items` contains
only the current page. For an explicit client, use `await Pod.async_client(config)`
or `Pod.client(config)`. Client methods use `get`, `list`, `create`, etc.; async
clients are awaited. In controllers, use `await ctx.client(Pod)` to share the
application's connection and namespace; see [read contracts](reads.md).

## Build a local resource

Ordinary constructors provide static field types and Pydantic validation:

```python
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

settings = ConfigMap(
    metadata=ObjectMeta(name="settings", namespace="default"),
    data={"message": "hello"},
)
```

Generated models also provide typed fluent builders:

```python
settings = (
    ConfigMap.builder()
    .metadata(lambda meta: meta.name("settings").namespace("default"))
    .data({"message": "hello"})
    .build()
)
```

For imperative construction, use a context builder:

```python
with ConfigMap.new() as builder:
    with builder.metadata() as meta:
        meta.name("settings")
        meta.namespace("default")
    builder.data({"message": "hello"})
settings = builder.build()
```

All three produce a local model without API access. Builders validate at `build()`;
fluent chains are immutable outside context-manager scopes. A builder context
constructs values; it does not create or clean up cluster resources. Handwritten
models have dynamic builders; use constructors for precise static field types.

## Create, update and delete

```python
settings = settings.create()
settings.data = {"message": "updated"}
settings = settings.update()

# save creates a missing resource or updates an existing one.
settings = settings.save()

# Delete the fetched instance, or delete by name.
settings.remove()
# ConfigMap.delete("settings", namespace="default")
```

Use the returned model to retain server-assigned metadata and resourceVersion.
`update` performs replacement; it is different from an owned-child `ctx.ensure`
that manages only supplied fields. `save` respects the fetched/supplied version.
Conflicts propagate rather than silently overwriting a newer object.

Async equivalents include `async_create`, `async_update`, `async_save`,
`async_remove` and `async_delete`. Use `dry_run=True` to request a server dry run.
For a narrow guarded change, see [explicit writes](runtime.md#explicit-guarded-writes).
For reconciled primary resources, [return the changed object](controllers.md#returning-resources-and-status)
and let the controller persist it.

## Watch and wait

```python
for event_type, pod in Pod.watch(field_selector="metadata.name=nginx"):
    if event_type == "DELETED":
        break
```

Async watches are iterators; do not await the iterator itself:

```python
async def wait_for_deletion() -> None:
    async for event_type, pod in Pod.async_watch(field_selector="metadata.name=nginx"):
        if event_type == "DELETED":
            return
```

For a fetched resource, `wait_for` also evaluates a predicate until it succeeds or
the timeout expires:

```python
pod = Pod.get("nginx", namespace="default")
pod.wait_for(
    lambda _, current: current.status is not None and current.status.phase == "Running",
    timeout=300,
)
```

`async_wait_for` is the async equivalent. A dictionary of named predicates returns
the name of the first satisfied predicate. Use [controllers](controllers.md) when
you need retry queues and ongoing convergence instead of a one-off watch.

## Resources without generated models

`get_dynamic_resource` creates an `Unstructured` resource type from its API identity:

```python
from cloudcoil.resources import get_dynamic_resource

DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
settings = DynamicConfigMap(
    metadata={"name": "settings", "namespace": "default"},
    data={"message": "hello"},
)
settings["data"]["message"] = "updated"
payload = settings.raw
```

This constructs a local object. Call `create` or another resource method to persist
it. Unknown fields support dictionary access; declared nested models such as
metadata remain typed (`settings.metadata.name`). Mapping access returns live
values, while `.raw` returns a serialized snapshot. Membership includes fields
whose value is `None`; serialization can omit them.

## Parse manifests and look up models

```python
from cloudcoil import resources
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

settings = resources.parse({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {"name": "settings"},
    "data": {"message": "hello"},
})
assert isinstance(settings, ConfigMap)
```

`resources.parse_file("manifests.yaml", load_all=True)` reads multiple documents;
omit `load_all` for one resource. Import or install the model package containing
the types you intend to parse.

`resources.get_model("ConfigMap", api_version="v1")` performs runtime model lookup
and returns `type[Resource]`. A generated package's own `get_model` preserves the
concrete static type for literal arguments. Specify `api_version` when a kind has
multiple versions; ambiguous bare names fail. See [model typing](models.md#ide-typing).
