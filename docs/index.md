# cloudcoil

Typed Kubernetes clients, controllers and admission policies for Python.
Use ordinary Pydantic resource classes for API calls, then use the same types to
define CRDs and build operators.

[Get started](getting-started.md) with installation, a resource read and a running
controller. Or choose the guide for your task:

| Task | Guide |
| --- | --- |
| Read, write, build or watch Kubernetes objects | [Resources](resources.md) |
| Collect and filter workload logs | [Logs](logs.md) |
| Generate Python models from CRDs or OpenAPI | [Model generation](models.md) |
| Define your own Kubernetes resource | [Custom resources](custom-resources.md) |
| Reconcile resources and manage children | [Controllers](controllers.md) |
| Read dependencies from clients or informers | [Live and cached reads](reads.md) |
| Default or validate incoming writes | [Admission](admission.md) |
| Generate manifests and deploy an operator | [Deployment](operators.md) |
| Find an executable controller/operator pattern | [Patterns](patterns.md) |

`Operator.main()` handles configuration, signals, queues, informers and cleanup.
Start from the [complete Widget example](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)
for a CRD with three child kinds, readiness and admission.

For advanced integrations, see [runtime and observability](runtime.md),
[client caching](caching.md), [testing](testing.md), and the [API reference](api.md).

[Source and issues](https://github.com/cloudcoil/cloudcoil) ·
[Versioning and Kubernetes support](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md) ·
[Apache-2.0 license](https://github.com/cloudcoil/cloudcoil/blob/main/LICENSE)
