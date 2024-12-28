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
# ClientSet is the core way to interact with your Kubernetes API Server
from cloudcoil.client import ClientSet
from cloudcoil.client import errors
# All default kubernetes types are neatly arranged
# with appropriate apiversions as module paths
from cloudcoil.models.apps import v1 as apps_v1
from cloudcoil.models.core import v1 as core_v1


# Uses the default clientset based on KUBECONFIG
# Feels just as natural as kubectl
# But comes with full pydantic validation
kubernetes_service = core_v1.Service.get("kubernetes")

# You can create temporary clientset contexts
# This is similar to doing kubens kube-system
with ClientSet(namespace="kube-system"):
    # This searches for deployments in the kube-system namespace
    core_dns_deployment = apps_v1.Deployment.get("core-dns")
    # Also comes with async client out of the box!
    kube_dns_service = await core_v1.Service.async_get("kube-dns")

# Create new objects with generate name easily
test_namespace = core_v1.Namespace(metadata=dict(generate_name="test-")).create()

# We can access the output from the APIServer from the create method
# Switch to the new namespace
with ClientSet(namespace=test_namespace.metadata.name):
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

## Documentation

For full documentation, please visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.
