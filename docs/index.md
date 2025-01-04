# cloudcoil

Cloud native made easy with Python

### PyPI stats

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.svg)](https://pypi.python.org/pypi/cloudcoil)
[![Versions](https://img.shields.io/pypi/pyversions/cloudcoil.svg)](https://github.com/cloudcoil/cloudcoil)

[![Downloads](https://static.pepy.tech/badge/cloudcoil)](https://pepy.tech/project/cloudcoil)
[![Downloads/month](https://static.pepy.tech/badge/cloudcoil/month)](https://pepy.tech/project/cloudcoil)
[![Downloads/week](https://static.pepy.tech/badge/cloudcoil/week)](https://pepy.tech/project/cloudcoil)

### Repo information

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/license/apache-2-0/)
[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cloudcoil/cloudcoil/branch/main/graph/badge.svg)](https://codecov.io/gh/cloudcoil/cloudcoil)

## Installation

```bash
# Minimal dependencies
# pydantic, httpx and pyyaml
uv add cloudcoil
```

## Quick Start

```python
# Config is the core way to interact with your Kubernetes API Server
from cloudcoil.client import Config
from cloudcoil.client import errors
# All default kubernetes types are neatly arranged
# with appropriate apiversions as module paths
from cloudcoil.models.kubernetes.apps import v1 as apps_v1
from cloudcoil.models.kubernetes.core import v1 as core_v1


# Uses the default config based on KUBECONFIG
# Feels just as natural as kubectl
# But comes with full pydantic validation
kubernetes_service = core_v1.Service.get("kubernetes")

# You can create temporary config contexts
# This is similar to doing kubens kube-system
with Config(namespace="kube-system"):
    # This searches for deployments in the kube-system namespace
    core_dns_deployment = apps_v1.Deployment.get("core-dns")
    # Also comes with async client out of the box!
    kube_dns_service = await core_v1.Service.async_get("kube-dns")

# Create new objects with generate name easily
test_namespace = core_v1.Namespace(metadata=dict(generate_name="test-")).create()

# We can access the output from the APIServer from the create method
# Switch to the new namespace
with Config(namespace=test_namespace.metadata.name):
    try:
        core_dns_deployment = apps_v1.Deployment.get("core-dns")
    except errors.ResourceNotFound:
        pass

# Finally you can remove the namespace
# And also inspect the output to ensure it is terminating
test_namespace.remove().status.phase == "Terminating"
# You can also delete it using the name/namespace if you wish
core_v1.Namespace.delete(name=test_namespace.metadata.name)
```

### Testing Integration

cloudcoil includes pytest fixtures to help you test your Kubernetes applications. Install with test dependencies:

```bash
uv add cloudcoil[test]
```

The testing integration provides two key fixtures:
- `test_cluster`: Creates and manages a k3d cluster for testing
- `test_config`: Provides a Config instance configured for the test cluster

Example usage:

```python
import pytest
from cloudcoil.models.kubernetes.core import v1 as corev1

@pytest.mark.configure_test_cluster(
    cluster_name="my-test-cluster",
    k3d_version="v5.7.5",
    k8s_version="v1.31.4",
    remove=True
)
def test_my_resources(test_config):
    with test_config:
        namespace = corev1.Namespace.get("default")
        assert namespace.metadata.name == "default"
```

#### Test Cluster Configuration

The `configure_test_cluster` mark accepts these arguments:

- `cluster_name`: Name of the test cluster (default: auto-generated)
- `k3d_version`: Version of k3d to use (default: v5.7.5)
- `k8s_version`: Kubernetes version to use (default: v1.31.4)
- `k8s_image`: Custom k3s image (default: rancher/k3s:{k8s_version}-k3s1)
- `remove`: Whether to remove the cluster after tests (default: True)

## Documentation

For full documentation, please visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.
