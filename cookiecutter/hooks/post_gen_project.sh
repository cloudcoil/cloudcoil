#!/bin/bash
set -ex
{% if cookiecutter._config_dir %}
[[ -f {{cookiecutter._config_dir}}/Makefile ]] && cat {{cookiecutter._config_dir}}/Makefile >> Makefile
[[ -f {{cookiecutter._config_dir}}/pyproject.toml ]] && cat {{cookiecutter._config_dir}}/pyproject.toml >> pyproject.toml
[[ -f {{cookiecutter._config_dir}}/README.md ]] && cat {{cookiecutter._config_dir}}/README.md >> README.md
[[ -d {{cookiecutter._config_dir}}/schemas ]] && cp -a {{cookiecutter._config_dir}}/schemas .
[[ -d {{cookiecutter._config_dir}}/tests ]] && cp -a {{cookiecutter._config_dir}}/tests/. tests/
{% endif %}
uv lock --upgrade-package cloudcoil
uv sync --locked
# Publish usable models on the default branch, not the empty template package.
make gen-models
