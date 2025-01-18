# cloudcoil

🚀 Cloud native operations made beautifully simple with Python

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.svg)](https://pypi.python.org/pypi/cloudcoil)
[![Downloads](https://static.pepy.tech/badge/cloudcoil)](https://pepy.tech/project/cloudcoil)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/license/apache-2-0/)
[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)

> Modern, async-first Kubernetes client with elegant Pythonic syntax and full type safety

## ✨ Features

- 🔥 **Elegant, Pythonic API** - Feels natural to Python developers
- ⚡ **Async First** - Native async/await support for high performance
- 🛡️ **Type Safe** - Full mypy support and runtime validation
- 🧪 **Testing Ready** - Built-in pytest fixtures for K8s integration tests
- 📦 **Zero Config** - Works with your existing kubeconfig
- 🪶 **Minimal Dependencies** - Only requires httpx, pydantic, and pyyaml

## 🔧 Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Kubernetes support
uv add cloudcoil[kubernetes]

# Install with specific Kubernetes version compatibility
uv add cloudcoil[kubernetes-1-29]
uv add cloudcoil[kubernetes-1-30]
uv add cloudcoil[kubernetes-1-31]
uv add cloudcoil[kubernetes-1-32]
```

Using pip:

```bash
pip install cloudcoil[kubernetes]
```


## 💡 Examples

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
async for event_type, resource in await k8s.core.v1.Pod.async_watch(field_selector="metadata.name=mypod"):
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
        # Creates a fresh k3d cluster for testing
        deployment = apps.v1.Deployment.get("app")
        assert deployment.spec.replicas == 3
```

### Advanced Configuration

```python
@pytest.mark.configure_test_cluster(
    cluster_name="my-test-cluster",     # Custom cluster name
    k3d_version="v5.7.5",              # Specific k3d version
    k8s_version="v1.31.4",             # Specific K8s version
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

## 🛡️ MyPy Integration

cloudcoil provides a mypy plugin that enables type checking for dynamically loaded kinds from the scheme. To enable the plugin, add this to your pyproject.toml:

```toml
# pyproject.toml
[tool.mypy]
plugins = ['cloudcoil.mypy']
```

This plugin enables full type checking for scheme.get() calls when the kind name is a string literal:

```py
from cloudcoil import resources

# This will be correctly typed as k8s.batch.v1.Job
job_class = resources.get_model("Job")

# Type checking works on the returned class
job = job_class(
    metadata={"name": "test"},  # type checked!
    spec={
        "template": {
            "spec": {
                "containers": [{"name": "test", "image": "test"}],
                "restartPolicy": "Never"
            }
        }
    }
)
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
