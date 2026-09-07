# Working with resources

Start with the [quickstart](getting-started.md) for installation and a first API call.
This guide covers typed resource operations and builders.

## Reading Resources

```python
from cloudcoil.client import Config
import cloudcoil.models.kubernetes as k8s

# Get a resource
service = k8s.core.v1.Service.get("kubernetes")

# Iterate resources, following server pagination
for pod in k8s.core.v1.Pod.list(namespace="default"):
    print(f"Found pod: {pod.metadata.name}")

# Async equivalent
async for pod in await k8s.core.v1.Pod.async_list():
    print(f"Found pod: {pod.metadata.name}")
```
## Building resources

Ordinary constructors have static types and Pydantic validation:

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

All three construct a model without API access. Call `settings.create()` or
`await settings.async_create()` to persist it. Builders validate at `build()`;
fluent chains are immutable outside context-manager scopes. Handwritten models
have dynamic builders, but constructors provide more precise static field types.
See [custom resource builders](custom-resources.md#use-a-handwritten-resource-as-a-client).

## Creating Resources

```python
# Create with Pythonic syntax
namespace = k8s.core.v1.Namespace(
    metadata=dict(name="dev")
).create()

# Generate names automatically
test_ns = k8s.core.v1.Namespace(
    metadata=dict(generate_name="test-")
).create()
```

## Modifying Resources

```python
# Update resources fluently
deployment = k8s.apps.v1.Deployment.get("web")
deployment.spec.replicas = 3
deployment.update()

# Or use the save method which handles both create and update
configmap = k8s.core.v1.ConfigMap(
    metadata=dict(name="config"),
    data={"key": "value"}
)
configmap.save()  # Creates the ConfigMap

configmap.data["key"] = "new-value"
configmap.save()  # Updates the ConfigMap
```

## Deleting Resources

```python
# Delete by name
k8s.core.v1.Pod.delete("nginx", namespace="default")

# Or remove the resource instance
pod = k8s.core.v1.Pod.get("nginx")
pod.remove()
```

## Watching Resources

```python
for event_type, resource in k8s.core.v1.Pod.watch(field_selector="metadata.name=mypod"):
    # Wait for the pod to be deleted
    if event_type == "DELETED":
        break

# You can also use the async watch
async for event_type, resource in k8s.core.v1.Pod.async_watch(field_selector="metadata.name=mypod"):
    # Wait for the pod to be deleted
    if event_type == "DELETED":
        break
```

## Waiting for Resources

```python
# Wait for a resource to reach a desired state
pod = k8s.core.v1.Pod.get("nginx")
pod.wait_for(lambda _, pod: pod.status.phase == "Running", timeout=300)

# You can also check of the resource to be deleted
await pod.async_wait_for(lambda event, _: event == "DELETED", timeout=300)

# You can also supply multiple conditions. The wait will end when the first condition is met.
# It will also return the key of the condition that was met.
test_pod = k8s.core.v1.Pod.get("tests")
status = await test_pod.async_wait_for({
    "succeeded": lambda _, pod: pod.status.phase == "Succeeded",
    "failed": lambda _, pod: pod.status.phase == "Failed"
    }, timeout=300)
assert status == "succeeded"
```

## Dynamic Resources

```python
from cloudcoil.resources import get_dynamic_resource

# Get a dynamic resource class for any CRD or resource without a model
DynamicJob = get_dynamic_resource("Job", "batch/v1")

# Create using dictionary syntax
job = DynamicJob(
    metadata={"name": "dynamic-job"},
    spec={
        "template": {
            "spec": {
                "containers": [{"name": "job", "image": "busybox"}],
                "restartPolicy": "Never"
            }
        }
    }
)

# Create on the cluster
created = job.create()

# Access fields using dict-like syntax
assert created["spec"]["template"]["spec"]["containers"][0]["image"] == "busybox"

# Update metadata (a Job pod template is immutable)
created.metadata.labels = {"example.com/source": "dynamic"}
updated = created.update()

# Get raw dictionary representation
raw_dict = updated.raw
```

`Unstructured` mapping access accepts Python field names and wire aliases and returns
live values, including declared fields on subclasses. For example,
`resource["spec"]["replicas"] = 2` updates the resource directly. Declared nested
models remain typed models: use `resource["metadata"].name` or `resource.metadata.name`.
Use `resource.raw` for a serialized dictionary snapshot. Membership tests include
fields whose value is `None`; serialization may omit those fields.

## Resource Parsing

```python
from cloudcoil import resources

# Parse YAML files
deployment = resources.parse_file("deployment.yaml")

# Parse multiple resources
documents = resources.parse_file("k8s-manifests.yaml", load_all=True)

# Get resource class by GVK if its an existing resource model class
Job = resources.get_model("Job", api_version="batch/v1")
```

## Context Management

```python
# Temporarily switch namespace
with Config(namespace="kube-system"):
    pods = k8s.core.v1.Pod.list()

# Custom configs
with Config(kubeconfig="dev-cluster.yaml"):
    services = k8s.core.v1.Service.list()
```
