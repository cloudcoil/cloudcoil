# cloudcoil

Cloudcoil combines typed Kubernetes API clients with a controller and admission
runtime for Python 3.14+. The same Pydantic resource types work in API calls,
controller handlers, CRD definitions and admission requests.

Start with [Getting started](getting-started.md) to run a controller. The guides
follow this repository's source; use a matching checkout when trying unreleased APIs.

## Build an application

| You need to… | Guide |
| --- | --- |
| Read and write Kubernetes objects | [Resources](resources.md) |
| Define a custom resource and its status | [Custom resources](custom-resources.md) |
| Repair desired state and manage child objects | [Controllers](controllers.md) |
| Split work into stages or choose a case | [Stages, cases and reporting](staged-controllers.md) |
| Read dependencies through API clients or informers | [Live and cached reads](reads.md) |
| Default or validate writes | [Admission](admission.md) |
| Generate permissions, install CRDs and deploy | [Application deployment](operators.md) |
| Manage startup, shutdown and leadership changes | [Lifespans](lifespan.md) |
| Check behavior locally and against Kubernetes | [Testing](testing.md) |

The [Widget demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)
combines a CRD, ordered stages, three child kinds, status and admission. The
[pattern catalog](patterns.md) covers dependency watches, nested cases, variable
children, finalizers, reusable controller groups and standalone policies.

## Use the client and models

[Resource operations](resources.md) and [logs](logs.md) work independently of the
controller runtime. Use a [published model package](integrations.md), or
[generate models](models.md) from a CRD or OpenAPI document.

For embedding and tuning, see [client caching](caching.md),
[runtime and observability](runtime.md) and the [API reference](api.md).
Maintainers can follow the [model release guide](model-releases.md).

[Source and issues](https://github.com/cloudcoil/cloudcoil) ·
[Versioning and support](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md) ·
[Apache-2.0 license](https://github.com/cloudcoil/cloudcoil/blob/main/LICENSE)
