# cloudcoil

🚀 Cloud native operations made beautifully simple with Python

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.svg)](https://pypi.python.org/pypi/cloudcoil)
[![Downloads](https://static.pepy.tech/badge/cloudcoil)](https://pepy.tech/project/cloudcoil)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/license/apache-2-0/)
[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)

> Modern, async-first Kubernetes client with elegant Pythonic syntax and full type safety

## 🤝 Support the Project

If you find Cloudcoil useful, please consider giving it a star on GitHub! Your support helps the project grow and encourages continued development.

[![Star on GitHub](https://img.shields.io/github/stars/cloudcoil/cloudcoil.svg?style=social)](https://github.com/cloudcoil/cloudcoil)

## ✨ Features

- 🔥 **Elegant, Pythonic API** - Feels natural to Python developers including fluent and context manager style resource builders
- ⚡ **Async First** - Native async/await support for high performance
- 🛡️ **Type Safe** - Standard IDE typing and runtime validation
- 🧪 **Testing Ready** - Built-in pytest fixtures for K8s integration tests
- 📦 **Zero Config** - Works with your existing kubeconfig
- 🪶 **Minimal Dependencies** - Only requires httpx, pydantic, and pyyaml

## Controllers

Build typed async controllers with retries, dependency watches, shared informers, and graceful
shutdown. Reconcile the latest state while Cloudcoil handles watch recovery and work
scheduling:

```python
from cloudcoil.controller import Controller, Request
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Secret

async def reconcile(request: Request[ConfigMap]) -> ConfigMap | None:
    resource = request.resource
    if resource is None:
        return None
    resource.data = {**(resource.data or {}), "managed-by": "cloudcoil"}
    return resource  # Cloudcoil patches changes; unchanged returns perform no write.

controller = Controller(ConfigMap, reconcile, workers=4).owns(Secret)
# In your async entry point: await controller.run()
```

Use `Manager(..., leader_election=LeaderElection("my-controller"),
health=HealthServer(port=8080))` for replica coordination, probes, and metrics.

See the [controller guide](https://cloudcoil.github.io/cloudcoil/controllers/) for
optimistic mutations, finalizers, custom dependencies, lifecycle, and the incremental
framework roadmap. A [runnable example](examples/configmap_controller.py) mirrors
ConfigMaps into owned children and repairs drift. Returned resources are patched with
UID/version guards, with automatic status-subresource routing. Use
`Result(resource=resource, requeue_after=60)` to save and schedule another pass.

Define your own resource once and use `CRD(Widget, plural="widgets").to_yaml()` to
generate its Kubernetes definition. Typed `AdmissionWebhook` handlers use the same
model for mutation and validation. See the [custom resource guide](https://cloudcoil.github.io/cloudcoil/custom-resources/)
and the [complete Widget operator example](examples/widget_operator.py).

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Kubernetes support
uv add cloudcoil[kubernetes]
```

Using pip:

```bash
pip install cloudcoil[kubernetes]
```

Cloudcoil deprecates Kubernetes minors when they reach [upstream end of life](https://kubernetes.io/releases/).
As of September 6, 2026, **1.33 and older are deprecated**; CI and model generation
cover **1.34–1.37**. Kubernetes 1.34 remains supported until October 27, 2026.
The `kubernetes-1-29` through `kubernetes-1-32` extras remain available only for
existing installations; they receive no new model releases or dedicated CI.
See the [support policy and migration guide](VERSIONING.md#kubernetes-support-policy).

The unversioned `kubernetes` extra currently installs the latest published models,
which are still 1.32. Until supported model releases are published, generate and
install matching models from a checkout:

```bash
uv run --extra codegen --extra kubernetes python tools/generate_kubernetes.py \
  --version 1.37.0 --output output/kubernetes-1.37
uv pip install --no-deps output/kubernetes-1.37
```

Use `uv run --no-sync` with these locally installed models so uv does not replace
them with the version in the lockfile. CI exercises the full controller, CRD, and
admission suite against Kubernetes 1.34–1.37 using matching generated models. Test fixtures default to kind 0.33.0 with
Kubernetes 1.37.0, or k3d 5.9.0 with its separately released k3s 1.36.4.

## 🔌 Integrations

Discover more Cloudcoil model integrations for popular Kubernetes operators and CRDs at [cloudcoil-models on GitHub](https://github.com/topics/cloudcoil-models).

Current first-class integrations include:

| Name | Github | PyPI | 
| ------- | ------- | -------  | 
| [cert-manager](https://github.com/cert-manager/cert-manager) | [models-cert-manager](https://github.com/cloudcoil/models-cert-manager) | [cloudcoil.models.cert_manager](https://pypi.org/project/cloudcoil.models.cert-manager) |
| [fluxcd](https://github.com/fluxcd/flux2) | [models-fluxcd](https://github.com/cloudcoil/models-fluxcd) | [cloudcoil.models.fluxcd](https://pypi.org/project/cloudcoil.models.fluxcd) |
| [istio](https://github.com/istio/istio) | [models-istio](https://github.com/cloudcoil/models-istio) | [cloudcoil.models.istio](https://pypi.org/project/cloudcoil.models.istio) |
| [keda](https://github.com/kedacore/keda) | [models-keda](https://github.com/cloudcoil/models-keda) | [cloudcoil.models.keda](https://pypi.org/project/cloudcoil.models.keda) |
| [knative-serving](https://github.com/knative/serving) | [models-knative-serving](https://github.com/cloudcoil/models-knative-serving) | [cloudcoil.models.knative_serving](https://pypi.org/project/cloudcoil.models.knative-serving) |
| [knative-eventing](https://github.com/knative/eventing) | [models-knative-eventing](https://github.com/cloudcoil/models-knative-eventing) | [cloudcoil.models.knative_eventing](https://pypi.org/project/cloudcoil.models.knative-eventing) |
| [kpack](https://github.com/pivotal/kpack) | [models-kpack](https://github.com/cloudcoil/models-kpack) | [cloudcoil.models.kpack](https://pypi.org/project/cloudcoil.models.kpack) |
| [kyverno](https://github.com/kyverno/kyverno) | [models-kyverno](https://github.com/cloudcoil/models-kyverno) | [cloudcoil.models.kyverno](https://pypi.org/project/cloudcoil.models.kyverno) |
| [prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) | [models-prometheus-operator](https://github.com/cloudcoil/models-prometheus-operator) | [cloudcoil.models.prometheus_operator](https://pypi.org/project/cloudcoil.models.prometheus_operator) |
| [sealed-secrets](https://github.com/bitnami-labs/sealed-secrets) | [models-sealed-secrets](https://github.com/cloudcoil/models-sealed-secrets) | [cloudcoil.models.sealed_secrets](https://pypi.org/project/cloudcoil.models.sealed_secrets) |
| [velero](https://github.com/vmware-tanzu/velero) | [models-velero](https://github.com/cloudcoil/models-velero) | [cloudcoil.models.velero](https://pypi.org/project/cloudcoil.models.velero) |

You can install these integrations using

```bash
uv add cloudcoil[kyverno]
# You can also install multiple dependencies at once
uv add cloudcoil[cert-manager,fluxcd,kyverno]
# You can also install all available models in cloudcoil using
uv add cloudcoil[all-models]
```

> Missing an integration you need? [Open a model request](https://github.com/cloudcoil/cloudcoil/issues/new?template=%F0%9F%94%8C-model-request.md) to suggest a new integration!

## 💡 Examples

### Finding and filtering logs

Read or follow a Pod or workload with the same interface:

```python
from cloudcoil import logs

print(logs.read("deployment/worker", namespace="jobs", tail_lines=50))
with logs.stream("deployment/worker", namespace="jobs") as records:
    for record in records:
        print(record.pod, record.container, record.message)
```

These built-in workload objects work too, including metadata-only references:

| Resource | String target (singular/plural also accepted) |
| --- | --- |
| Deployment | `deploy/worker` |
| ReplicaSet | `rs/worker` |
| StatefulSet | `sts/database` |
| DaemonSet | `ds/agent` |
| Job | `job/migration` |
| CronJob | `cj/nightly` |
| ReplicationController | `rc/worker` |

A workload selects
one Pod, preferring non-terminating, running, ready Pods, then breaking ties by name.
Container selection uses that Pod's default-container annotation or sole regular
container; otherwise specify `container=`. Selection considers every list page.

To combine discovery and streaming across **all matching Pods** of any supported workload,
use the async helper:

```python
from cloudcoil import logs

async def follow_workers():
    async with logs.async_stream(
        "deployment/worker", namespace="jobs", all_pods=True,
        tail_lines=100, match=logs.LogFilter(contains="error", ignore_case=True),
    ) as records:
        async for record in records:
            print(record.pod, record.container, record.message)
```

`all_pods=True` selects one container per Pod, or the named `container=` on Pods that
contain it. Records arrive as each stream produces them, preserving order within each
source, with no global timestamp sort. `max_streams=10` bounds concurrent requests and
tasks; buffering is bounded too. Following more sources than this limit raises before
opening any log streams: increase the limit explicitly. With `follow=False`, larger
selections are processed in batches. A source error propagates and closes the other
streams; exiting the block, a failing filter, and cancellation also close all responses.

For more control, `logs.discover("deployment/worker", namespace="jobs")` (or a Deployment
object) returns containers across its matching Pods for use with `read()` / `stream()`.
Discovery uses the full `spec.selector`, including `matchExpressions`, and ANDs any
additional `label_selector=` for built-in workloads; it does not guess from workload metadata
or template labels. ReplicationControllers use their flat label maps. Job references fetch
the server-generated selector when it is missing. Empty selectors are rejected. Workload
discovery requires Pod-list permission, and a name or metadata-only reference also requires
permission to get that workload. Log reads additionally require `pods/log`.
An empty workload returns no discovered sources;
read/stream raise `ResourceNotFound` if no Pods match. Built-in workload selectors retain
Kubernetes label-selector semantics.

**Custom resources:** pass a generated `Resource` instance or `Unstructured` object.
If its `spec.selector` describes its Pods, both the standard `matchLabels`/`matchExpressions`
shape and a flat label map work automatically. This is a convention, not a universal CRD
guarantee: some operators use selectors for other resources. If the selector is absent or
has another shape, discovery automatically traverses `ownerReferences` back from Pods.
This supports chains such as custom resource → StatefulSet → Pod, as well as CronJob →
Job → Pod. Pass a fetched resource with `metadata.uid` so ownership can be matched to
the exact object; names alone are insufficient when an object has been recreated.

Supply `label_selector=` to explicitly define the Pod association when the convention
does not apply or the operator does not set ownership links. For custom
resources this replaces the convention; for built-in workloads it narrows their selector.
It works on `discover`, `read`, `stream`, and their async equivalents:

```python
from cloudcoil import logs
from cloudcoil.resources import Resource

async def follow_custom_resource(resource: Resource, pod_labels: str):
    async with logs.async_stream(
        resource, label_selector=pod_labels, all_pods=True, tail_lines=100
    ) as records:
        async for record in records:
            print(record.pod, record.container, record.message)
```

Use the operator's actual Pod labels. Custom kinds do not have string shortcuts or an
automatic resource GET; the supplied object provides its selector and namespace. Use
`namespace=` to select the Pod namespace for cluster-scoped or cross-namespace operators.
The ownership fallback lists Pods in the selected namespace, then reads only referenced
ancestors, caching lookups for that discovery call. It requests metadata where supported
and uses API discovery for unfamiliar owner kinds. It respects namespaced/cluster-scoped
ownership rules, skips deleted/recreated ancestors, and stops cycles. It requires permission
to read intermediate owners and their API discovery endpoints; permission errors propagate
instead of producing a silently incomplete result. Use `label_selector=` if those reads
are unavailable. Resources without selectors or ownership links still need explicit Pod labels.

Discover containers by Kubernetes selectors, then filter their log records:

```python
from cloudcoil import logs

errors = logs.LogFilter(regex=r"error|exception", ignore_case=True)
for source in logs.discover(all_namespaces=True, label_selector="app=worker"):
    # Sources include regular, init, and ephemeral containers. Select before reading.
    if source.container_type != "regular":
        continue
    with logs.stream(source, follow=False, tail_lines=100, timestamps=True, match=errors) as records:
        for record in records:
            print(record.namespace, record.pod, record.container, record.message)
```

`discover()` uses the active namespace by default and follows every list page. It returns
metadata without downloading logs: labels, pod UID, owner references, node, phase,
container type/state, and restart count. Selectors run on the server; `container="app"`
selects an exact container name. A discovered source retains its configuration so it can
be passed directly to `read()` or `stream()` outside the original context. Discovery is
a snapshot of potential sources; a waiting container may not have logs, and discovery
permissions do not imply permission to read them. API errors propagate to the caller.

```python
# Read text with original line endings, or follow structured records.
print(logs.read("worker", namespace="jobs", tail_lines=50))
with logs.stream("worker", namespace="jobs", match=logs.LogFilter(contains="failed")) as records:
    for record in records:
        print(record.timestamp, record.message)

# The same operations are available asynchronously.
async for source in logs.async_discover(label_selector="app=worker", container="app"):
    async with logs.async_stream(source, follow=False, match=errors) as records:
        async for record in records:
            print(record.pod, record.message)
```

A supplied Pod provides its namespace, labels, and sole regular container (or the valid
`kubectl.kubernetes.io/default-container` annotation). Ambiguous Pods require `container=`.
A pod name alone needs only log-read permissions and leaves container selection to the
server; labels and the selected container may then be unknown. Records expose `raw`,
`message`, `timestamp`, `pod`, `namespace`, `container`, `previous`, `labels`, and, when discovered,
`source`. Metadata is a snapshot; timestamps preserve nanosecond precision as strings.
Use `match=lambda record: ...` for custom text or metadata filtering.

`stream()` follows by default and requests timestamps; `follow=False` reads a finite
snapshot and defaults timestamps off. Both accept `timestamps=` explicitly. Always use
`with` / `async with` so breaking, errors, and cancellation close the HTTP response.
Following disables only the response read timeout. Deployment membership and source
metadata are snapshots: streams do not reconnect, switch Pods, or discover new replicas
during a rollout. For manually discovered live sources, run async consumers concurrently
under your own concurrency limit; a sequential follow loop stays on its first live source.

All operations reuse the active configuration's authenticated HTTP client, or accept
`config=` explicitly. Reusable `LogOptions` and typed keywords support `previous`,
`tail_lines`, `since_seconds` **or** timezone-aware `since_time`, and `limit_bytes`.
Direct keywords override options. Time/tail/byte limits apply on the server before
client-side matching; byte limits may truncate a line. Kubernetes log access cannot
recover deleted Pods or logs that the node has already rotated away.

### Reading Resources

```python
from cloudcoil.client import Config
import cloudcoil.models.kubernetes as k8s

# Get a resource - as simple as that!
service = k8s.core.v1.Service.get("kubernetes")

# List resources with elegant pagination
for pod in k8s.core.v1.Pod.list(namespace="default"):
    print(f"Found pod: {pod.metadata.name}")

# Async support out of the box
async for pod in await k8s.core.v1.Pod.async_list():
    print(f"Found pod: {pod.metadata.name}")
```
### Building resources

#### Using Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.kubernetes.core.v1 as k8score
import cloudcoil.models.kubernetes.apps.v1 as k8sapps

# Create a Deployment
deployment = k8sapps.Deployment(
    metadata=apimachinery.ObjectMeta(name="nginx"),
    spec=k8sapps.DeploymentSpec(
        replicas=3,
        selector=apimachinery.LabelSelector(
            match_labels={"app": "nginx"}
        ),
        template=k8score.PodTemplateSpec(
            metadata=apimachinery.ObjectMeta(
                labels={"app": "nginx"}
            ),
            spec=k8score.PodSpec(
                containers=[
                    k8score.Container(
                        name="nginx",
                        image="nginx:latest",
                        ports=[k8score.ContainerPort(container_port=80)]
                    )
                ]
            )
        )
    )
).create()

# Create a Service
service = k8score.Service(
    metadata=apimachinery.ObjectMeta(name="nginx"),
    spec=k8score.ServiceSpec(
        selector={"app": "nginx"},
        ports=[k8score.ServicePort(port=80, target_port=80)]
    )
).create()

# List Deployments
for deploy in k8sapps.Deployment.list():
    print(f"Found deployment: {deploy.metadata.name}")

# Update a Deployment
deployment.spec.replicas = 5
deployment.save()

# Delete resources
k8score.Service.delete("nginx")
k8sapps.Deployment.delete("nginx")
```

#### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Kubernetes resources with full IDE support and rich autocomplete capabilities:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import Service

# Create a Deployment using the fluent builder
# The fluent style is great for one-liners and simple configurations
nginx_deployment = (
    Deployment.builder()
    # Metadata can be configured in a single chain for simple objects
    .metadata(lambda metadata: metadata
        .name("nginx")
        .namespace("default")
    )
    # Complex nested structures can be built using nested lambda functions
    .spec(lambda deployment_spec: deployment_spec
        .replicas(3)
        # Each level of nesting gets its own lambda for clarity
        .selector(lambda label_selector: label_selector
            .match_labels({"app": "nginx"})
        )
        .template(lambda pod_template: pod_template
            .metadata(lambda pod_metadata: pod_metadata
                .labels({"app": "nginx"})
            )
            .spec(lambda pod_spec: pod_spec
                # Lists can be built using array literals with lambda items
                .containers([
                    lambda container: container
                    .name("nginx")
                    .image("nginx:latest")
                    # Nested collections can use the add() helper
                    .ports(lambda port_list: port_list.add(
                        lambda port: port.container_port(80)
                    ))
                ])
            )
        )
    )
    .build()
)

# Create a Service using the builder
service = (
    Service.builder()
    .metadata(lambda m: m
        .name("nginx")
        .namespace("default")
    )
    .spec(lambda s: s
        .selector({"app": "nginx"})
        .ports(lambda ports: ports.add(lambda p: p.container_port(80)))
    )
    .build()
)
```

The fluent builder provides:
- ✨ Full IDE support with detailed type information
- 🔍 Rich autocomplete for all fields and nested objects
- ⚡ Compile-time validation of your configuration
- 🎯 Clear and chainable API that guides you through resource creation

#### Using the Context Manager Builder API

For complex nested resources, Cloudcoil also provides a context manager-based builder pattern that can make the structure more clear:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import Service

# Create a deployment using context managers
# Context managers are ideal for deeply nested structures
with Deployment.new() as nginx_deployment:
    # Each context creates a clear visual scope
    with nginx_deployment.metadata() as deployment_metadata:
        deployment_metadata.name("nginx")
        deployment_metadata.namespace("default")
    
    with nginx_deployment.spec() as deployment_spec:
        # Simple fields can be set directly
        deployment_spec.replicas(3)
        
        # Each nested object gets its own context
        with deployment_spec.selector() as label_selector:
            label_selector.match_labels({"app": "nginx"})
        
        with deployment_spec.template() as pod_template:
            with pod_template.metadata() as pod_metadata:
                pod_metadata.labels({"app": "nginx"})
            
            with pod_template.spec() as pod_spec:
                # Collections use a parent context for the list
                with pod_spec.containers() as container_list:
                    # And child contexts for each item
                    with container_list.add() as nginx_container:
                        nginx_container.name("nginx")
                        nginx_container.image("nginx:latest")
                        # Ports can be added one by one
                        with nginx_container.add_port() as container_port:
                            container_port.container_port(80)

final_deployment = nginx_deployment.build()

# Create a service using context managers
with Service.new() as nginx_service:
    # Context managers make the structure very clear
    with nginx_service.metadata() as service_metadata:
        service_metadata.name("nginx")
        service_metadata.namespace("default")
    
    with nginx_service.spec() as service_spec:
        # Simple fields can still be set directly
        service_spec.selector({"app": "nginx"})
        # Port configuration is more readable with contexts
        with service_spec.add_port() as service_port:
            service_port.port(80)
            service_port.target_port(80)

final_service = nginx_service.build()
```

The context manager builder provides:
- 🎭 Clear visual nesting of resource structure
- 🔒 Automatic resource cleanup
- 🎯 Familiar Python context manager pattern
- ✨ Same great IDE support as the fluent builder

#### Mixing Builder Styles

CloudCoil's intelligent builder system automatically detects which style you're using and provides appropriate IDE support:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil import apimachinery

# Mixing styles lets you choose the best approach for each part
# The IDE automatically adapts to your chosen style at each level
with Deployment.new() as nginx_deployment:
    # Direct object initialization with full type checking
    nginx_deployment.metadata(apimachinery.ObjectMeta(
        name="nginx",
        namespace="default",
        labels={"app": "nginx"}
    ))
    
    with nginx_deployment.spec() as deployment_spec:
        # IDE shows all available fields with types
        deployment_spec.replicas(3)
        # Fluent style with rich autocomplete
        deployment_spec.selector(lambda sel: sel.match_labels({"app": "nginx"}))
        
        # Context manager style with full type hints
        with deployment_spec.template() as pod_template:
            # Mix and match freely - IDE adjusts automatically
            pod_template.metadata(apimachinery.ObjectMeta(labels={"app": "nginx"}))
            with pod_template.spec() as pod_spec:
                with pod_spec.containers() as container_list:
                    with container_list.add() as nginx_container:
                        # Complete IDE support regardless of style
                        nginx_container.name("nginx")
                        nginx_container.image("nginx:latest")
                        # Switch styles any time
                        nginx_container.ports(lambda ports: ports
                            .add(lambda p: p.container_port(80))
                            .add(lambda p: p.container_port(443))
                        )

final_deployment = nginx_deployment.build()
```

This flexibility allows you to:
- 🔀 Choose the most appropriate style for each part of your configuration
- 📖 Maximize readability for both simple and complex structures
- 🎨 Format your code according to your team's preferences
- 🧠 Get full IDE support with automatic style detection
- ✨ Enjoy rich autocomplete in all styles
- ⚡ Benefit from type checking across mixed styles
- 🎯 Receive immediate feedback on type errors
- 🔍 See documentation for all fields regardless of style


### Creating Resources

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

### Modifying Resources

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

### Deleting Resources

```python
# Delete by name
k8s.core.v1.Pod.delete("nginx", namespace="default")

# Or remove the resource instance
pod = k8s.core.v1.Pod.get("nginx")
pod.remove()
```

### Watching Resources

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

### Waiting for Resources

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

### Dynamic Resources

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

# Update fields
created["spec"]["template"]["spec"]["containers"][0]["image"] = "alpine"
updated = created.update()

# Get raw dictionary representation
raw_dict = updated.raw
```

### Resource Parsing

```python
from cloudcoil import resources

# Parse YAML files
deployment = resources.parse_file("deployment.yaml")

# Parse multiple resources
resources = resources.parse_file("k8s-manifests.yaml", load_all=True)

# Get resource class by GVK if its an existing resource model class
Job = resources.get_model("Job", api_version="batch/v1")
```

### Context Management

```python
# Temporarily switch namespace
with Config(namespace="kube-system"):
    pods = k8s.core.v1.Pod.list()

# Custom configs
with Config(kubeconfig="dev-cluster.yaml"):
    services = k8s.core.v1.Service.list()
```

### ⚡ High Performance with Caching

Cloudcoil provides powerful client-side caching and real-time resource synchronization, delivering 100-200x performance improvements on read operations:

```python
from cloudcoil.client import Config
from cloudcoil.caching import Cache
import cloudcoil.models.kubernetes as k8s

# Simple caching - just add cache=True!
config = Config(cache=True)

with config:
    # First call hits API and populates cache (~50ms)
    deployment = k8s.apps.v1.Deployment.get("my-app")
    
    # Subsequent calls served from cache (<1ms)
    deployment = k8s.apps.v1.Deployment.get("my-app")
    
    # Lists are also cached
    pods = k8s.core.v1.Pod.list()  # <5ms from cache
    
    # Writes go through API, cache updates automatically
    deployment.spec.replicas = 5
    deployment.update()  # Updates API and cache
```

#### Event Handlers with Informers

```python
from cloudcoil.client import Config
from cloudcoil.caching import Cache
import cloudcoil.models.kubernetes as k8s

# Enable caching with custom settings
config = Config(
    cache=Cache(resync_period=600)  # Resync every 10 minutes
)

with config:
    # Get informer for Deployments through the cache
    deployment_informer = config.cache.get_informer(k8s.apps.v1.Deployment)
    
    # Register event handlers
    @deployment_informer.on_add
    def handle_new_deployment(deployment):
        print(f"New deployment: {deployment.metadata.name}")
    
    @deployment_informer.on_update
    def handle_update(old_deployment, new_deployment):
        if old_deployment.spec.replicas != new_deployment.spec.replicas:
            print(f"Deployment {new_deployment.metadata.name} scaled")
    
    @deployment_informer.on_delete
    def handle_delete(deployment):
        print(f"Deployment deleted: {deployment.metadata.name}")
    
    # Access the local cache store
    store = deployment_informer.get_store()
    all_deployments = store.list()  # Instant, no API call
    specific = store.get("my-app")  # Instant lookup
    
    # The informer lifecycle is managed by Config context
```

#### Async Event Handlers

```python
from cloudcoil.client import Config
from cloudcoil.caching import Cache
import cloudcoil.models.kubernetes as k8s

# Async context for high-performance applications
config = Config(cache=True)

async def monitor_pods():
    async with config:
        # Get async informer for Pods
        pod_informer = config.cache.get_informer(
            k8s.core.v1.Pod,
            sync=False  # Get async informer
        )
        
        # Async event handlers
        @pod_informer.on_add
        async def handle_new_pod(pod):
            print(f"New pod: {pod.metadata.name}")
            # Can perform async operations here
            await notify_external_system(pod)
        
        @pod_informer.on_update
        async def handle_pod_update(old_pod, new_pod):
            if old_pod.status.phase != new_pod.status.phase:
                print(f"Pod {new_pod.metadata.name} phase changed")
        
        # Access cache asynchronously
        store = pod_informer.get_store()
        all_pods = await store.async_list()  # Instant from cache
        
        # Keep running to process events
        await asyncio.sleep(3600)  # Run for 1 hour

# Run the async monitor
import asyncio
asyncio.run(monitor_pods())
```

#### Cache Configuration

```python
# Advanced caching with custom settings
config = Config(
    cache=Cache(
        resync_period=600,  # 10 minutes
        mode="strict",      # Cache-only mode (no API fallback)
        resources=[         # Cache specific resource types
            k8s.apps.v1.Deployment,
            k8s.core.v1.Service,
        ],
        max_items_per_resource=5000,  # Memory limit per resource type
    )
)

with config:
    # All operations use cache - no unexpected API calls
    deployment = k8s.apps.v1.Deployment.get("my-app")  # From cache or None
    services = k8s.core.v1.Service.list()  # From cache only
    
    # Temporarily disable cache for fresh data
    with config.cache.pause():
        fresh_data = k8s.apps.v1.Deployment.get("my-app")  # Direct API call
    
    # Check cache status
    informer = config.cache.get_informer(k8s.apps.v1.Deployment)
    if informer.has_synced():
        print("Cache is fully synchronized")
```

#### Resource Filtering

```python
from cloudcoil.client import Config
from cloudcoil.caching import Cache
import cloudcoil.models.kubernetes as k8s

# Cache only specific resource types for memory efficiency
config = Config(
    cache=Cache(
        resources=[  # Only cache these types
            k8s.apps.v1.Deployment,
            k8s.core.v1.Service,
            k8s.core.v1.ConfigMap,
        ],
        max_items_per_resource=1000  # Limit items per type
    )
)

with config:
    # These use cache (instant)
    deployment = k8s.apps.v1.Deployment.get("my-app")
    service = k8s.core.v1.Service.get("my-service")
    
    # This bypasses cache (not in resources list)
    pod = k8s.core.v1.Pod.get("my-pod")  # Direct API call
```

**Performance Benefits:**
- **Get operations**: 100-200x faster (50ms → <1ms)
- **List operations**: 50-100x faster (100ms → <5ms)  
- **Real-time updates**: Watch events keep cache fresh
- **Memory efficient**: Configurable limits and automatic cleanup
- **Reduced API load**: Shared informers minimize watch connections
- **Event-driven**: React to changes in real-time without polling


## 🧪 Testing Integration

Cloudcoil provides powerful pytest fixtures for Kubernetes integration testing:

### Installation

> uv add cloudcoil[test]

### Basic Usage

```python
import pytest
from cloudcoil.models.kubernetes import core, apps

@pytest.mark.configure_test_cluster
def test_deployment(test_config):
    with test_config:
        # Creates a fresh kind cluster for testing
        deployment = apps.v1.Deployment.get("app")
        assert deployment.spec.replicas == 3
```

### Advanced Configuration

```python
@pytest.mark.configure_test_cluster(
    cluster_name="my-test-cluster",     # Custom cluster name
    provider="k3d",                     # Use k3d rather than kind
    k3d_version="v5.9.0",              # Specific k3d version
    k8s_version="v1.36.4",             # Published k3s version
    k8s_image="custom/k3s:latest",     # Custom K3s image
    remove=True                         # Auto-remove cluster after tests
)
async def test_advanced(test_config):
    with test_config:
        # Async operations work too!
        service = await core.v1.Service.async_get("kubernetes")
        assert service.spec.type == "ClusterIP"
```

### Shared Clusters

Reuse clusters across tests for better performance:

```python
@pytest.mark.configure_test_cluster(
    cluster_name="shared-cluster",
    remove=False  # Keep cluster after tests
)
def test_first(test_config):
    with test_config:
        # Uses existing cluster if available
        namespace = core.v1.Namespace.get("default")
        assert namespace.status.phase == "Active"

@pytest.mark.configure_test_cluster(
    cluster_name="shared-cluster",  # Same cluster name
    remove=True   # Last test removes the cluster
)
def test_second(test_config):
    with test_config:
        # Uses same cluster as previous test
        pods = core.v1.Pod.list(namespace="kube-system")
        assert len(pods) > 0
```

### Parallel Testing

The fixtures are compatible with pytest-xdist for parallel testing:

```bash
# Run tests in parallel
pytest -n auto tests/

# Or specify number of workers
pytest -n 4 tests/
```

### Testing Fixtures API

The testing module provides two main fixtures:

- `test_cluster`: Creates and manages k3d clusters
  - Returns path to kubeconfig file
  - Handles cluster lifecycle
  - Supports cluster reuse
  - Compatible with parallel testing

- `test_config`: Provides configured `Config` instance
  - Uses test cluster kubeconfig
  - Manages client connections
  - Handles cleanup automatically
  - Context manager support

## IDE typing

Cloudcoil targets Python 3.14 and uses standard Python annotations understood by
Pyright/Pylance and mypy. No Cloudcoil or Pydantic mypy plugin is required.
Direct imports provide the clearest completions:

```python
from hello.v1 import Widget

widget = Widget.builder().metadata(lambda meta: meta.name("example")).build()
```

Generated packages also include their own typed lookup. Literal names and API
versions resolve to the concrete class in both type checkers:

```python
from hello import get_model

Widget = get_model("Widget", api_version="widgets.example.com/v1")
widget = Widget.builder().metadata(lambda meta: meta.name("example")).build()
```

A kind name alone works when it is unique in that package. If several versions
exist, specify `api_version`. The global `cloudcoil.resources.get_model()` remains
available for runtime discovery and returns `type[Resource]`; use a direct import
or the generated package lookup when you need static completion of specific fields.

## Model generation

Install Python 3.14 and the codegen extra:

```shell
pip install 'cloudcoil[codegen]'
cloudcoil-model-codegen --namespace hello --input crds.yaml --output .
```

That is enough for ordinary CRDs. Inputs can be local paths or URLs, YAML or JSON,
multi-document installation bundles, Kubernetes `List` objects, Swagger/OpenAPI
2 or 3 documents, or JSON Schema definitions. Format detection uses the content,
so download URLs do not need a `.yaml` or `.json` suffix. Multiple inputs work too:

```shell
cloudcoil-model-codegen --namespace hello --input first.yaml second.json --output .
```

For repeatable project generation, put only the package and sources in
`pyproject.toml`, then run `cloudcoil-model-codegen`:

```toml
[[tool.cloudcoil.codegen.models]]
namespace = "hello"
input = ["crds.yaml"]
```

The generator automatically:

- Uses CRD group/version/kind metadata, OpenAPI endpoint references, and unambiguous
  versioned schema families to recognize resources.
- Maps built-in Kubernetes APIs to packages such as `core.v1` and `apps.v1`, and
  reuses Cloudcoil's metadata and scalar types instead of duplicating them.
- Places a single CRD group under its version; separates multiple groups so their
  model names cannot silently collide.
- Gives nested objects names derived from their parent and field path.
- Handles Kubernetes integer-or-string, nullable, embedded-resource, and
  preserve-unknown-fields annotations, including schemas nested inside lists.
- Keeps wire names intact while escaping Python API collisions such as the
  `builder` field (`builder_`) and the `Builder` resource (`BuilderResource`).
- Produces fluent builders, context builders, and package-local typed lookups.

Generation stages and syntax-checks output before copying it to the destination.
Repeat generation replaces generated files and removes stale files recorded in its
manifest, while leaving unrelated files alone. Conflicting definitions and naming
collisions are errors rather than silent overwrites.

### When an override is useful

Hints remain useful for intentionally different public package layouts, genuine
schema errors, or missing/ambiguous resource identity that cannot be established
from the source. Prefer supplying the CRD or complete OpenAPI document over
manually describing its GVK. Generation cannot infer a missing API group from a
Python/Go type name alone, and does not implement Kubernetes admission or CEL
validation locally.

Explicit `transformations`, `updates`, and `aliases` remain available. Updates
accept JSON values, including booleans, numbers, lists, objects, and null; string
updates support regex substitutions. Explicit transformations take precedence
over inferred names. `crd-namespace` is an optional layout override, not a
requirement. Set `infer = false` (CLI: `--no-infer`) to retain manual control.
`exclude-unknown` discards unmatched definitions and their dependents.

The checked-in regression corpus covers complete HelmRelease, Certificate, and
Prometheus CRDs plus the complete kpack OpenAPI schema, without schema hints.
The cookiecutter template remains available for packaging and publishing models.

### Migrating from 0.4 / earlier 0.5 development builds

- Upgrade to Python 3.14 and regenerate your models with the current codegen extra.
- Remove `cloudcoil.mypy` from type-checker configuration. Use direct imports or a
  generated package's `get_model` for precise static types.
- Inferred module and nested-class names can change; retain explicit
  transformations when you need a particular layout.
- Iterate watches directly: `async for event in Pod.async_watch(): ...` (no `await`
  before the iterable). Async operations perform initial discovery off the event loop;
  explicit clients are available with `await config.async_client_for(Pod)`.
- A bare kind lookup now rejects ambiguous versions instead of selecting one by
  import order.
- Direct client deletion now defaults to performing the operation, matching
  resource methods. Pass `dry_run=True` explicitly to preview a deletion.
- List pagination follows the server's continuation token and stays with its
  originating client. Requesting a nonexistent next page raises `ValueError`.
- `save()` uses the fetched resource version for replacement without mutating the
  caller's model. A caller-supplied version remains authoritative.
- Nested and concurrent cached scopes share a cache until the last scope exits.
  Use separate cached configs for synchronous and asynchronous scopes.

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)

## 🌟 Stargazers over time
[![Stargazers over time](https://starchart.cc/cloudcoil/cloudcoil.svg?variant=adaptive)](https://starchart.cc/cloudcoil/cloudcoil)


`Unstructured` mapping access accepts Python field names and wire aliases and returns
live values, including declared fields on subclasses. For example,
`resource["spec"]["replicas"] = 2` updates the resource directly. Declared nested
models remain typed models: use `resource["metadata"].name` or `resource.metadata.name`.
Use `resource.raw` for a serialized dictionary snapshot. Membership tests include
fields whose value is `None`; serialization may omit those fields.
