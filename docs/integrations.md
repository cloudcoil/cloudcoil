# Model integrations

Discover more Cloudcoil model integrations for popular Kubernetes operators and CRDs at [cloudcoil-models on GitHub](https://github.com/topics/cloudcoil-models).

Current first-class integrations include:

| Name | Github | PyPI |
| ------- | ------- | -------  |
| [cert-manager](https://github.com/cert-manager/cert-manager) | [models-cert-manager](https://github.com/cloudcoil/models-cert-manager) | [cloudcoil.models.cert_manager](https://pypi.org/project/cloudcoil.models.cert-manager) |
| [fluxcd](https://github.com/fluxcd/flux2) | [models-fluxcd](https://github.com/cloudcoil/models-fluxcd) | [cloudcoil.models.fluxcd](https://pypi.org/project/cloudcoil.models.fluxcd) |
| [istio](https://github.com/istio/istio) | [models-istio](https://github.com/cloudcoil/models-istio) | [cloudcoil.models.istio](https://pypi.org/project/cloudcoil.models.istio) |
| [keda](https://github.com/kedacore/keda) | [models-keda](https://github.com/cloudcoil/models-keda) | [cloudcoil.models.keda](https://pypi.org/project/cloudcoil.models.keda) |
| [knative-serving](https://github.com/knative/serving) | [models-knative-serving](https://github.com/cloudcoil/models-knative-serving) | [cloudcoil.models.knative_serving](https://pypi.org/project/cloudcoil.models.knative-serving) |
| [knative-eventing](https://github.com/knative/eventing) | [models-knative-eventing](https://github.com/cloudcoil/models-knative-eventing) | [cloudcoil.models.knative_eventing](https://pypi.org/project/cloudcoil.models.knative-eventing) |
| [kpack](https://github.com/pivotal/kpack) | [models-kpack](https://github.com/cloudcoil/models-kpack) | [cloudcoil.models.kpack](https://pypi.org/project/cloudcoil.models.kpack) |
| [kyverno](https://github.com/kyverno/kyverno) | [models-kyverno](https://github.com/cloudcoil/models-kyverno) | [cloudcoil.models.kyverno](https://pypi.org/project/cloudcoil.models.kyverno) |
| [prometheus-operator](https://github.com/prometheus-operator/prometheus-operator) | [models-prometheus-operator](https://github.com/cloudcoil/models-prometheus-operator) | [cloudcoil.models.prometheus_operator](https://pypi.org/project/cloudcoil.models.prometheus_operator) |
| [sealed-secrets](https://github.com/bitnami-labs/sealed-secrets) | [models-sealed-secrets](https://github.com/cloudcoil/models-sealed-secrets) | [cloudcoil.models.sealed_secrets](https://pypi.org/project/cloudcoil.models.sealed_secrets) |
| [velero](https://github.com/vmware-tanzu/velero) | [models-velero](https://github.com/cloudcoil/models-velero) | [cloudcoil.models.velero](https://pypi.org/project/cloudcoil.models.velero) |

You can install these integrations using

```bash
uv add cloudcoil[kyverno]
# You can also install multiple dependencies at once
uv add cloudcoil[cert-manager,fluxcd,kyverno]
# You can also install all available models in cloudcoil using
uv add cloudcoil[all-models]
```

> Missing an integration you need? [Open a model request](https://github.com/cloudcoil/cloudcoil/issues/new?template=%F0%9F%94%8C-model-request.md) to suggest a new integration!

## New integration sources

Generation configs and resource round-trip tests are available for the following
projects. These packages are awaiting their initial PyPI publishing setup; generate
from the checkout with `make gen-repo-<name>` in the meantime.

| Integration | Initially validated upstream version | Generation target |
| --- | --- | --- |
| Argo CD | 3.5.2 | `make gen-repo-argocd` |
| Contour | 1.33.7 | `make gen-repo-contour` |
| Crossplane | 2.4.0 | `make gen-repo-crossplane` |
| Tekton Pipelines | 1.15.1 | `make gen-repo-tekton` |

After rendering, run `make gen-models lint test` inside `output/models-<name>`.
For version update PRs and publishing, see [Maintaining model packages](model-releases.md).
