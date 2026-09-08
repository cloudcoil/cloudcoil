# cloudcoil.models.{{ cookiecutter.module_name }}

Typed {{ cookiecutter.model_name }} resources for the Cloudcoil Kubernetes client.

[![PyPI](https://img.shields.io/pypi/v/cloudcoil.models.{{ cookiecutter.module_name }}.svg)](https://pypi.org/project/cloudcoil.models.{{ cookiecutter.module_name }}/)
[![CI](https://github.com/cloudcoil/models-{{ cookiecutter.model_name }}/actions/workflows/ci.yml/badge.svg)](https://github.com/cloudcoil/models-{{ cookiecutter.model_name }}/actions/workflows/ci.yml)

## Install a published release

Requires Python 3.14+:

```sh
uv add cloudcoil.models.{{ cookiecutter.module_name }}
# Or:
pip install cloudcoil.models.{{ cookiecutter.module_name }}
```

Select a version matching the upstream APIs you use and pin a compatible Cloudcoil
minor. The [versioning guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md)
explains the upstream version and packaging revision. Model installation does not
install Kubernetes or an upstream operator.

Use the [Cloudcoil documentation](https://cloudcoil.github.io/cloudcoil/) for client
operations, controllers and admission. Report generation or packaging problems in
[cloudcoil/cloudcoil](https://github.com/cloudcoil/cloudcoil/issues).

Licensed under [Apache-2.0](https://github.com/cloudcoil/cloudcoil/blob/main/LICENSE).
