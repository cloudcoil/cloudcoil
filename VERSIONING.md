# Versioning Guide

## Cloudcoil Core Versioning

Cloudcoil is currently in its pre-1.0 development phase (0.x.x). During this phase:
- Breaking changes may occur with each minor version update
- It is strongly recommended to pin to a specific minor version
- Patch versions contain only bug fixes and non-breaking changes

## Model Versioning

Models from integrations follow the versioning scheme:
`<major>.<minor>.<patch>.<packaging>`

where:
- The first three numbers (`major.minor.patch`) are derived from the upstream project version
- The `packaging` version is an incrementally increasing number for cloudcoil-specific changes

For example, if using a model from the FluxCD integration:
- `2.0.1.0` represents FluxCD version 2.0.1 with initial packaging
- `2.0.1.1` represents FluxCD version 2.0.1 with first packaging update

## Installation Recommendations

### Best Practices

1. Always specify both cloudcoil and its integration constraints:
```
cloudcoil[fluxcd]~=0.5.0
```

2. Avoid constraining only the model integration version, as breaking changes in cloudcoil core may affect functionality.

### Examples

Good:
```
cloudcoil[fluxcd]~=0.5.0  # Installs cloudcoil with FluxCD integration
```

Not Recommended:
```
cloudcoil.models.fluxcd>=2.0  # Missing cloudcoil core constraint
```

## Version Compatibility

When using cloudcoil with integrations, ensure that:
1. The cloudcoil core version is pinned to a minor version
2. The integration model version is compatible with your upstream tools
3. Both constraints are specified in your requirements


## Kubernetes Support Policy

Cloudcoil follows the [upstream Kubernetes end-of-life dates](https://kubernetes.io/releases/).
When a minor reaches EOL, Cloudcoil deprecates support for both that cluster version
and its matching model package. Deprecated minors leave the CI matrix and automatic
model generation/release list; they receive no new model releases or compatibility
fixes. Existing distributions remain available, and the client does not refuse
connections to older clusters. Managed-provider extended support does not extend
Cloudcoil's support window.

Support as of **September 6, 2026**:

| Kubernetes minor | Cloudcoil status | Upstream EOL |
| --- | --- | --- |
| 1.37 | Supported; default | October 28, 2027 |
| 1.36 | Supported | June 28, 2027 |
| 1.35 | Supported | February 28, 2027 |
| 1.34 | Supported until EOL | October 27, 2026 |
| 1.33 and older | Deprecated; outside active support | Already reached |

Use the explicit EOL dates, including any overlap after a new minor release, when
updating support. Maintainers must update the CI matrix in `.github/workflows/ci.yml`,
the release list in `models/kubernetes/cookiecutter.yaml`, and this table together.

### Migrating from deprecated models

The `kubernetes-1-29`, `kubernetes-1-30`, `kubernetes-1-31`, and `kubernetes-1-32`
extras are deprecated compatibility aliases. They remain installable during the
transition; remove these extras and any old model pins when upgrading. Their
continued availability does not imply support for EOL Kubernetes versions.

The unversioned `cloudcoil[kubernetes]` extra selects the latest published model
package, which is currently 1.32.1.3. The development lockfile also uses that package
as a bootstrap dependency; CI replaces it with supported generated models before
running checks. We do not require unpublished packages or silently substitute a
new minor for an explicitly pinned old minor.

Until the compatible Cloudcoil core and supported model packages are published,
use the [checkout generation instructions](README.md#-installation) with a matching
supported schema (1.34.11, 1.35.8, 1.36.4, or 1.37.0). Upgrade the cluster following
the upstream/provider upgrade procedure, update the model dependency, and check
your code against APIs available in that Kubernetes version. Generating Python
models does not upgrade a running cluster.
