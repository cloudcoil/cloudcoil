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

## Pin the runtime and model packages

Pin Cloudcoil to a compatible minor and select model versions matching your target
APIs. Extras are installation conveniences; they do not select the version of a
running cluster or install an operator's CRDs.

```sh
uv add 'cloudcoil~=0.7.1' 'cloudcoil.models.kubernetes~=1.37.0.0'
```

Keep application lockfiles under version control. Regenerate custom model packages
when upgrading across a breaking Cloudcoil minor. Documentation in the repository
tracks its source and may describe APIs ahead of the published release.

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

The unversioned `cloudcoil[kubernetes]` extra selects a published compatible model
package. Cloudcoil 0.7.1 model releases are available for Kubernetes 1.34.11, 1.35.8,
1.36.4, and 1.37.0. Pin the model minor to match the cluster you intend to target:

```sh
uv add 'cloudcoil~=0.7.1' 'cloudcoil.models.kubernetes~=1.37.0.0'
```

The development lockfile still contains a bootstrap model dependency; CI replaces
it with supported generated models before running checks. Upgrade clusters using
the upstream/provider procedure. Generating Python models does not upgrade a
running cluster.

See [Maintaining model packages](docs/model-releases.md) for automated upstream
version PRs, packaging revision allocation, validation, and PyPI publication.

## Migrating older clients and generated models

- Upgrade to Python 3.14 and regenerate your models with the current codegen extra.
- Remove `cloudcoil.mypy` from type-checker configuration. Use direct imports or a
  generated package's `get_model` for precise static types.
- Inferred module and nested-class names can change; retain explicit
  transformations when you need a particular layout.
- Iterate watches directly: `async for event in Pod.async_watch(): ...` (no `await`
  before the iterable). Async operations perform initial discovery off the event loop;
  explicit clients are available with `await config.async_client_for(Pod)`.
- A bare kind lookup now rejects ambiguous versions instead of selecting one by
  import order.
- Direct client deletion now defaults to performing the operation, matching
  resource methods. Pass `dry_run=True` explicitly to preview a deletion.
- List pagination follows the server's continuation token and stays with its
  originating client. Requesting a nonexistent next page raises `ValueError`.
- `save()` uses the fetched resource version for replacement without mutating the
  caller's model. A caller-supplied version remains authoritative.
- Nested and concurrent cached scopes share a cache until the last scope exits.
  Use separate cached configs for synchronous and asynchronous scopes.
