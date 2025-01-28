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
