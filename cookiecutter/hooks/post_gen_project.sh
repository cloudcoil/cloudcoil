#!/bin/bash
set -ex
uv sync
uv add cloudcoil -U
{% if cookiecutter._config_dir %}
[[ -f {{cookiecutter._config_dir}}/Makefile ]] && cat {{cookiecutter._config_dir}}/Makefile >> Makefile
[[ -f {{cookiecutter._config_dir}}/pyproject.toml ]] && cat {{cookiecutter._config_dir}}/pyproject.toml >> pyproject.toml
[[ -f {{cookiecutter._config_dir}}/README.md ]] && cat {{cookiecutter._config_dir}}/README.md >> README.md
{% endif %}
make fix-lint