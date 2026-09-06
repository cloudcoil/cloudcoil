"""Build a Kubernetes model source package before its PyPI release is available.

Run from a checkout with the codegen extra installed, then install the output with
``uv pip install --no-deps OUTPUT``. This uses the same transformations as the
published model repository and does not modify the checked-in Cloudcoil package.
"""

import argparse
import re
import tomllib
from pathlib import Path

from cloudcoil.codegen.generator import ModelConfig, generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Upstream version, such as 1.37.0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, help="Use an already downloaded upstream schema")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("--version must be a stable major.minor.patch version")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be an empty or new directory")
    root = Path(__file__).resolve().parents[1]
    settings = tomllib.loads((root / "models/kubernetes/pyproject.toml").read_text())
    settings.update(
        namespace="cloudcoil.models.kubernetes",
        input=str(args.schema)
        if args.schema
        else (
            "https://raw.githubusercontent.com/kubernetes/kubernetes/refs/tags/"
            f"v{args.version}/api/openapi-spec/swagger.json"
        ),
        output=args.output,
    )
    generate(ModelConfig.model_validate(settings))
    (args.output / "pyproject.toml").write_text(
        f'''[project]
name = "cloudcoil.models.kubernetes"
version = "{args.version}.0"
requires-python = ">=3.14"
dependencies = ["cloudcoil>=0.5.0.dev0"]

[build-system]
requires = ["hatchling>=1.18.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
only-include = ["cloudcoil"]
'''
    )


if __name__ == "__main__":
    main()
