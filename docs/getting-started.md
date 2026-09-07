# Getting started

Cloudcoil is a typed Kubernetes client and an async controller framework for Python
3.14. Use ordinary resource classes for API calls, then add a `Controller` when
something must continuously converge.

## Install

```sh
uv add 'cloudcoil[kubernetes]'
# Add HTTPS hosting when your operator has admission policies:
uv add 'cloudcoil[operator,kubernetes]'
```

The unversioned Kubernetes extra currently installs published 1.32 models. This
branch's controller and manifest examples use newer generated API metadata. Until
matching model releases are available, run from a checkout:

```sh
uv sync --group dev --extra codegen --extra kubernetes
uv run --no-sync python tools/generate_kubernetes.py \
  --version 1.37.0 --output .build/kubernetes-models
uv pip install --no-deps .build/kubernetes-models
```

Use `uv run --no-sync` after installing these models so uv does not restore the
lockfile's older version. See the [support and versioning policy](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md)
for supported Kubernetes minors. Use your existing kubeconfig locally; in-cluster
applications use their ServiceAccount.

## Read a resource

```python
from cloudcoil.models.kubernetes.core.v1 import Pod

pods = Pod.list(namespace="default")
for pod in pods.items:
    print(pod.name)
```

Async applications use `await Pod.async_list(namespace="default")`. See
[resource operations](resources.md) for writes, watches, pagination and builders,
and [logs](logs.md) for workload log collection.

## Write a controller

Save this as `app.py`:

```python
from cloudcoil.controller import Controller, Request
from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from cloudcoil.application import Application

async def reconcile(request: Request[ConfigMap]) -> ConfigMap | None:
    obj = request.resource
    if obj is None or (obj.metadata and obj.metadata.deletion_timestamp):
        return None
    obj.data = {**(obj.data or {}), "managed-by": "cloudcoil"}
    return obj

app = Application(
    "configmap-labeler",
    Controller(ConfigMap, reconcile, label_selector="example.com/manage=true"),
)

if __name__ == "__main__":
    app.main()
```

Return the changed resource; Cloudcoil patches only differences and skips unchanged
writes. Watches, retries, concurrency and shutdown are managed by the runtime.

```sh
export CLOUDCOIL_NAMESPACE=default
uv run --no-sync python app.py manifests  # Review generated RBAC, without API access.
uv run --no-sync python app.py run
```

In another terminal, create a selected object:

```sh
kubectl -n default create configmap example --from-literal=message=hello
kubectl -n default label configmap example example.com/manage=true
kubectl -n default get configmap example -o yaml
```

Its data gains `managed-by: cloudcoil`. Stop the foreground controller with Ctrl-C.
For deployment, use [operator installation](operators.md) to generate the
ServiceAccount, RBAC and Deployment for your application image.

## Build an operator

Follow these guides in order:

1. [Custom resources](custom-resources.md): define a CRD with Pydantic fields.
2. [Controllers](controllers.md): return status, manage children and handle deletion.
3. [Live clients and informer reads](reads.md): read related resources explicitly.
4. [Admission](admission.md): default or validate writes, with or without a controller.
5. [Deployment](operators.md): generate manifests, install and run.

The [Widget demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)
is a complete CRD and operator with three child kinds, readiness, TLS and admission.
The [pattern guide](patterns.md) covers shared dependencies, existing resources,
pruning, finalizers and multiple controllers.
