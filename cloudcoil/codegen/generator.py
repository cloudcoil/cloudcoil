import sys
from pathlib import Path

from cloudcoil.codegen.parser import ModelConfig, generate

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomlkit as tomllib


def main():
    codegen_configs = tomllib.loads(Path("pyproject.toml").read_text())
    for config in (
        codegen_configs.get("tool", {}).get("cloudcoil", {}).get("codegen", {}).get("models", [])
    ):
        generate(ModelConfig.model_validate(config))
