# Upstream generation regression fixtures

These gzip files contain complete, unmodified schemas serialized as JSON. CRDs
were extracted from their release bundles; compression keeps the fixtures small.
Tests generate and import these schemas without transformations, updates, aliases,
or a CRD namespace hint.

| Fixture | Resource / source | Upstream release |
|---|---|---|
| `flux.json.gz` | HelmRelease CRD | https://github.com/fluxcd/flux2/releases/download/v2.4.0/install.yaml |
| `cert_manager.json.gz` | Certificate CRD | https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.crds.yaml |
| `prometheus.json.gz` | Prometheus CRD | https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.79.2/bundle.yaml |
| `kpack.json.gz` | Complete kpack OpenAPI schema | https://raw.githubusercontent.com/buildpacks-community/kpack/refs/tags/v0.16.1/api/openapi-spec/swagger.json |

Upstream projects distribute these schemas under Apache-2.0. The Kubernetes
OpenAPI fixture in the parent directory is Kubernetes v1.30.2; Cloudcoil's bundled
`apimachinery.py` is generated from the v1.31.4 source configured in pyproject.toml.
