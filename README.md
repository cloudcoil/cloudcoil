# cloudcoil

Typed Kubernetes clients, controllers and admission webhooks for Python 3.14+.

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.svg)](https://pypi.org/project/cloudcoil/)
[![CI](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/cloudcoil/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Use Pydantic models to read and write Kubernetes resources. Register controllers,
webhooks and lifecycle hooks with decorators; Cloudcoil supplies watches, retries,
status persistence, Events and generated deployment manifests.

## Install

```sh
uv add 'cloudcoil[kubernetes]'
# Include HTTPS admission hosting when needed:
uv add 'cloudcoil[operator,kubernetes]'
```

Choose a model version that matches your cluster; see [versioning](VERSIONING.md).
These docs track repository source and can describe APIs ahead of the published
release. To run the examples here, use the [source checkout quickstart](docs/getting-started.md#run-the-checkout).

## Read resources

```python
from cloudcoil.models.kubernetes.core.v1 import Pod

for pod in Pod.list(namespace="default"):
    print(pod.name)
```

Async code uses `await Pod.async_list(...)`. Configuration comes from your
kubeconfig locally or the Pod's ServiceAccount in a cluster.

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

Save this as `app.py`. `python app.py manifests` generates RBAC offline;
`python app.py run` starts the controller. Returning a changed resource saves a
guarded patch; unchanged returns cause no write. Exceptions retry with backoff.

For an operator with several responsibilities, register named stages with
`@controller.stage(condition=..., depends=...)`. A stage can hold one handler or
first-match cases. `raise Wait("RollingOut", after=10)` pauses the pass and retries
later. A status derived from `ReconcileStatus` gets automatic Ready conditions.
See the [stage and case guide](docs/staged-controllers.md).

## Choose a guide

| Task | Start here |
| --- | --- |
| Install and run a first controller | [Getting started](docs/getting-started.md) |
| Read, write, build, watch or stream logs | [Resources](docs/resources.md), [logs](docs/logs.md) |
| Define or generate typed models | [Custom resources](docs/custom-resources.md), [model generation](docs/models.md) |
| Reconcile, own children and finalize objects | [Controllers](docs/controllers.md) |
| Structure stages, cases, status and Events | [Stages and reporting](docs/staged-controllers.md) |
| Read dependencies and register watches | [Live and cached reads](docs/reads.md) |
| Default and validate API requests | [Admission](docs/admission.md) |
| Package an application and generate RBAC/TLS manifests | [Deployment](docs/operators.md) |
| Handle process startup and leadership changes | [Lifespans](docs/lifespan.md) |
| Find a complete implementation | [Patterns](docs/patterns.md), [Widget demo](examples/widgets/README.md) |
| Test or embed the runtime | [Testing](docs/testing.md), [runtime](docs/runtime.md) |

The [documentation site](https://cloudcoil.github.io/cloudcoil/) also includes the
[API reference](docs/api.md), [model integrations](docs/integrations.md) and
[release workflow](docs/model-releases.md).

Licensed under [Apache-2.0](LICENSE).
