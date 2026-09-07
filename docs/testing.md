# Testing

Use ordinary unit tests for reconcilers and admission callbacks, then run integration
tests against Kubernetes for API behavior, permissions and deployment wiring.

## Kubernetes fixtures

Install `cloudcoil[test,kubernetes]` and provide a working Docker runtime. The pytest
plugin supplies `test_cluster` (a kubeconfig path) and `test_config` (a Config using it).
kind is the default provider; select k3d explicitly when needed.

A complete test against an object present in a fresh cluster:

```python
import pytest
from cloudcoil.models.kubernetes.core.v1 import Namespace

@pytest.mark.configure_test_cluster(remove=True)
def test_default_namespace(test_config):
    with test_config:
        namespace = Namespace.get("default")
        assert namespace.status.phase == "Active"
```

For async tests, enter the Config asynchronously:

```python
@pytest.mark.configure_test_cluster(remove=True)
async def test_default_namespace_async(test_config):
    async with test_config:
        namespace = await Namespace.async_get("default")
        assert namespace.status.phase == "Active"
```

## Cluster configuration

| Marker option | Purpose |
| --- | --- |
| `cluster_name` | Fixed name for reuse; otherwise generated |
| `provider` | `kind` or `k3d` |
| `kind_version`, `k3d_version` | Provider binary version |
| `k8s_version` | Kubernetes version (`version` is an older alias) |
| `k8s_image` | Explicit node image; overrides the version |
| `remove` | Remove the cluster after the test; defaults to `True` |

`CLUSTER_PROVIDER` selects a default provider. `CLOUDCOIL_K8S_IMAGE` supplies its
node image for CI. An explicit marker provider/image takes precedence. See
[VERSIONING.md](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md)
for supported minors and provider defaults.

For local reuse, choose a fixed cluster name and `remove=False`. Clean up the
cluster explicitly afterward. Avoid relying on test ordering to make a particular
test delete a shared cluster. With pytest-xdist, use isolated names or coordinate
shared-cluster lifetime deliberately.

## Framework examples

The repository includes three levels of checks:

- Callback and mock-API tests cover returned patches, ownership, finalizer ordering,
  informer reads and admission decisions.
- Live Kubernetes tests cover discovery, watches, conflicts, status subresources,
  drift repair and leadership.
- The [packaged Widget demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)
  exercises generated RBAC, TLS, installation order and real API-server admission.

Tests that only call an ASGI handler cannot prove Service routing or runtime RBAC.
Use the packaged demo when changing deployment or webhook registration behavior.
