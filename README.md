# cloudcoil

[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/cloudcoil.svg)](https://badge.fury.io/py/cloudcoil)
[![Python Versions](https://img.shields.io/pypi/pyversions/cloudcoil.svg)](https://pypi.org/project/cloudcoil/)
[![codecov](https://codecov.io/gh/cloudcoil/cloudcoil/branch/main/graph/badge.svg)](https://codecov.io/gh/cloudcoil/cloudcoil)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Cloud native made easy with Python

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
```

## Documentation

For full documentation, please visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.
