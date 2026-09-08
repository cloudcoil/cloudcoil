# Model package template

This template creates a versioned Cloudcoil model repository. For ordinary local
model generation, use `cloudcoil-model-codegen` directly; see the
[model generation guide](../docs/models.md).

## Render a maintained integration

From the Cloudcoil repository root, with Python 3.14 and uv installed:

```sh
make gen-repo-cert-manager
make -C output/models-cert-manager lint test check-artifacts
```

`models/<name>/cookiecutter.yaml` supplies the template values. The generation hook
appends that directory's optional `pyproject.toml`, README and Makefile overlays,
copies schema supplements and tests, installs dependencies and generates models.
The rendered repository contains usable Python modules on its default branch.

The template README owns common installation guidance; integration READMEs add
resource examples and source-specific notes. Keep shared client and builder
instructions in the main guides instead of duplicating them in each package.

## Change or add a package

Edit the template for shared packaging changes. Edit `models/<name>` for one
integration's schemas, configuration or tests. Render into `output/` and inspect
the generated result; output is reproducible and should not be edited as source.

The [maintainer guide](../docs/model-releases.md) describes upstream update PRs,
validation, release branches, version allocation and PyPI publishing. Rendering and
validation do not publish a package.
