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

Select a Kubernetes model version for your cluster, following the
[support and versioning policy](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).
Installing models supplies Python types; it does not install a cluster or CRDs.

## Run the checkout

This guide follows repository source, including APIs that may not yet be published.
From the repository root, install the development environment and matching models:

```sh
uv sync --group dev --extra codegen --extra kubernetes
uv run --no-sync python tools/generate_kubernetes.py \
  --version 1.37.0 --output .build/kubernetes-models
uv pip install --no-deps .build/kubernetes-models
```

The checked-in development lockfile has a bootstrap model dependency. Use
`uv run --no-sync` after installing generated models so uv does not restore it.
For an application using published releases, install a compatible model package
normally; local generation is only needed when developing against this checkout.

Use your existing kubeconfig locally; applications in Kubernetes use their
ServiceAccount. The commands below target the `default` namespace.

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
2. [Controllers](controllers.md): reconcile, manage children and finalize objects.
3. [Stages and reporting](staged-controllers.md): structure work, status and Events.
4. [Live clients and informer reads](reads.md): read related resources explicitly.
5. [Admission](admission.md): default or validate writes, with or without a controller.
6. [Deployment](operators.md): generate manifests, install and run.

The [Widget demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)
is a complete CRD and operator with three child kinds, readiness, TLS and admission.
The [pattern guide](patterns.md) covers shared dependencies, existing resources,
pruning, finalizers and multiple controllers.
