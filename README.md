# cloudcoil

Typed Kubernetes clients, controllers and admission policies for Python 3.14.

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.svg)](https://pypi.org/project/cloudcoil/)
[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Use Pydantic resource classes for typed API calls. Build controllers that return
changed resources, define CRDs from Python models, and add admission policies to
built-in or custom resources.

## Installation

```sh
uv add 'cloudcoil[kubernetes]'
# Include HTTPS hosting for admission:
uv add 'cloudcoil[operator,kubernetes]'
```

The Kubernetes extra currently installs published 1.32 models. Until supported
model packages are released, follow the [checkout installation instructions](docs/getting-started.md#install)
to generate matching models. See [VERSIONING.md](VERSIONING.md) for Kubernetes support
and migration details.

## Read resources

```python
from cloudcoil.models.kubernetes.core.v1 import Pod

for pod in Pod.list(namespace="default").items:
    print(pod.name)
```

Async applications use `await Pod.async_list(...)`. Cloudcoil uses your kubeconfig
locally and ServiceAccount credentials in a Pod.

## Write a controller

```python
from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from cloudcoil.application import Application

app = Application("configmap-labeler")
configs = app.controller(ConfigMap, label_selector="example.com/manage=true")

@configs.reconcile()
async def reconcile(config: ConfigMap) -> ConfigMap:
    config.data = {**(config.data or {}), "managed-by": "cloudcoil"}
    return config

if __name__ == "__main__":
    app.main()
```

Save as `app.py`. Run `python app.py manifests` to review generated permissions,
or `python app.py run` to start reconciliation. Cloudcoil handles watch recovery,
retries, guarded main/status patches and shutdown. Unchanged returns cause no write.
See the [quickstart](docs/getting-started.md) to try it against a cluster.

## Documentation

The [documentation site](https://cloudcoil.github.io/cloudcoil/) contains the full guides.
The same pages are available in this checkout:

| Task | Guide |
| --- | --- |
| Install and run your first controller | [Getting started](docs/getting-started.md) |
| API operations and builders | [Resources](docs/resources.md) |
| Workload logs | [Logs](docs/logs.md) |
| CRD/OpenAPI model generation and typing | [Models](docs/models.md) |
| Define CRDs from Python | [Custom resources](docs/custom-resources.md) |
| Reconcile, manage children and write status | [Controllers](docs/controllers.md) |
| Live clients and informer reads | [Reads](docs/reads.md) |
| Admission on built-in and custom resources | [Admission](docs/admission.md) |
| Manifests, RBAC, TLS and deployment | [Applications](docs/operators.md) |
| Executable controller/operator examples | [Patterns](docs/patterns.md) |
| Caching, leadership and observability | [Caching](docs/caching.md), [runtime](docs/runtime.md) |
| Kubernetes integration tests | [Testing](docs/testing.md) |
| Existing model packages | [Integrations](docs/integrations.md) |

The [Widget demo](examples/widgets/README.md) builds and deploys a complete operator
with a CRD, ConfigMap, Deployment, Service, readiness and HTTPS admission.

Licensed under [Apache-2.0](LICENSE).

