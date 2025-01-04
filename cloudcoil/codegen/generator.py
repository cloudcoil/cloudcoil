import argparse
import sys
from pathlib import Path
from typing import List

from cloudcoil.codegen.parser import ModelConfig, Substitution, generate
from cloudcoil.version import __version__

if sys.version_info > (3, 11):
    import tomllib
else:
    from . import _tomllib as tomllib


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Kubernetes API models for CloudCoil",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"cloudcoil-model-codegen {__version__}"
    )
    parser.add_argument("--name", help="Name of the model package to generate")
    parser.add_argument("--input", help="Input JSON schema file or URL")
    parser.add_argument(
        "--substitution",
        action="append",
        help="Substitution pattern in the format 'from:to'",
        default=[],
    )
    parser.add_argument("--config", help="Path to the configuration file", default="pyproject.toml")
    parser.add_argument("--output", help="Output directory", default=None)
    return parser


def parse_substitutions(substitution_args: List[str]) -> List[Substitution]:
    substitutions = []
    for substitution in substitution_args:
        from_, to = substitution.split(":")
        substitutions.append(Substitution(from_=from_, to=to))
    return substitutions


def process_cli_args(args: argparse.Namespace) -> bool:
    if args.name and args.input:
        substitutions = parse_substitutions(args.substitution)
        config_args = {"name": args.name, "input_": args.input, "substitute": substitutions}
        if args.output:
            config_args["output"] = Path(args.output)
        config = ModelConfig(**config_args)
        generate(config)
        return True
    return False


def process_config_file(config_path: str) -> bool:
    if not Path(config_path).exists():
        return False

    codegen_configs = tomllib.loads(Path(config_path).read_text())
    models = (
        codegen_configs.get("tool", {}).get("cloudcoil", {}).get("codegen", {}).get("models", [])
    )

    if not models:
        return False

    for config in models:
        generate(ModelConfig.model_validate(config))
    return True


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if not process_cli_args(args) and not process_config_file(args.config):
        parser.print_help()
        sys.exit(1)
