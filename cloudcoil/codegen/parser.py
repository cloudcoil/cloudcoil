import ast
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import httpx
from cloudcoil._pydantic import BaseModel
from cloudcoil.codegen.import_rewriter import rewrite_imports
from cloudcoil.version import __version__
from datamodel_code_generator.__main__ import (
    main as generate_code,
)
from pydantic import BeforeValidator, Field, model_validator


class Substitution(BaseModel):
    from_: Annotated[str | re.Pattern, Field(alias="from"), BeforeValidator(re.compile)]
    to: str
    namespace: str | None = None


class ModelConfig(BaseModel):
    namespace: str
    input_: Annotated[str, Field(alias="input")]
    output: Path | None = None
    substitutions: list[Substitution] = []

    @model_validator(mode="after")
    def _add_namespace(self):
        for substitution in self.substitutions:
            if not substitution.namespace:
                substitution.namespace = self.namespace
        self.substitutions.append(
            Substitution(from_=re.compile(r"^(.*)$"), to=r"\g<1>", namespace=self.namespace)
        )
        return self


def process_definitions(schema):
    for definition in schema["definitions"].values():
        if "x-kubernetes-group-version-kind" in definition:
            gvk = definition["x-kubernetes-group-version-kind"][0]
            group = gvk.get("group", "")
            version = gvk["version"]
            kind = gvk["kind"]

            # Construct apiVersion
            if group:
                api_version = f"{group}/{version}"
            else:
                api_version = version

            # Replace apiVersion and kind with constants
            if "properties" in definition:
                required = definition.setdefault("required", [])
                if "apiVersion" in definition["properties"]:
                    definition["properties"]["apiVersion"]["enum"] = [api_version]
                    definition["properties"]["apiVersion"]["default"] = api_version
                    if "apiVersion" not in required:
                        required.append("apiVersion")
                if "kind" in definition["properties"]:
                    definition["properties"]["kind"]["enum"] = [kind]
                    definition["properties"]["kind"]["default"] = kind
                    if "kind" not in required:
                        required.append("kind")
                if "metadata" in required:
                    required.remove("metadata")
        # Convert int-or-string to string
        if "properties" in definition:
            for prop in definition["properties"].values():
                if prop.get("format") == "int-or-string":
                    prop["type"] = ["integer", "string"]
                    prop.pop("format")
        if "format" in definition:
            if definition["format"] == "int-or-string":
                definition["type"] = ["integer", "string"]
                definition.pop("format")


def process_substitutions(substitutions: list[Substitution], schema: dict) -> dict:
    renames = {}

    def _new_name(definition_name):
        for substitution in substitutions:
            if substitution.from_.match(definition_name):
                return substitution.from_.sub(
                    f"{substitution.namespace}.{substitution.to}", definition_name
                )
        return definition_name

    for definition_name in schema["definitions"]:
        new_name = _new_name(definition_name)
        renames[definition_name] = new_name
    for old_name, new_name in renames.items():
        schema["definitions"][new_name] = schema["definitions"].pop(old_name)

    raw_schema = json.dumps(schema, indent=2)
    for old_name, new_name in renames.items():
        raw_schema = raw_schema.replace(
            f'"#/definitions/{old_name}"', f'"#/definitions/{new_name}"'
        )
    return json.loads(raw_schema)


def process_input(config: ModelConfig, workdir: Path):
    schema_file = workdir / "schema.json"
    extra_data_file = workdir / "extra_data.json"

    if config.input_.startswith("http"):
        response = httpx.get(config.input_, follow_redirects=True)
        if response.status_code != 200:
            raise ValueError(f"Failed to fetch {config.input_}")
        schema = response.json()
    else:
        with open(config.input_, "r") as f:
            content = f.read()
        schema = json.loads(content)
    schema = process_substitutions(config.substitutions, schema)
    process_definitions(schema)
    extra_data = generate_extra_data(schema)
    schema_file.write_text(json.dumps(schema, indent=2))
    extra_data_file.write_text(json.dumps(extra_data, indent=2))
    return schema_file, extra_data_file


def generate_extra_data(schema: dict) -> dict:
    extra_data = {}
    for prop_name, prop in schema["definitions"].items():
        extra_prop_data = {
            "is_gvk": False,
            "is_list": False,
        }
        if "x-kubernetes-group-version-kind" in prop:
            extra_prop_data["is_gvk"] = True
        if prop_name.endswith("List") and set(prop["properties"]) == {
            "metadata",
            "items",
            "apiVersion",
            "kind",
        }:
            extra_prop_data["is_list"] = True
        extra_data[prop_name] = extra_prop_data
    return extra_data


def get_file_header(content: str) -> tuple[str, str]:
    """
    Extract header (comments and docstrings) from Python file content.
    Returns tuple of (header, rest_of_content)
    """
    # Parse the content into an AST
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # If there's a syntax error, return content as-is
        return "", content

    header_lines = []
    rest_lines = content.split("\n")

    # Get leading comments
    for line in rest_lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            header_lines.append(line)
        elif not stripped:
            header_lines.append(line)
        else:
            break

    # Check for module docstring
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Str):
        # Get the docstring node
        docstring_node = tree.body[0]
        # Find where the docstring ends in the original content
        docstring_end = docstring_node.end_lineno
        # Add all lines up to and including the docstring
        header_lines.extend(rest_lines[len(header_lines) : docstring_end])
        rest_lines = rest_lines[docstring_end:]
    else:
        rest_lines = rest_lines[len(header_lines) :]

    header = "\n".join(header_lines)
    rest = "\n".join(rest_lines)

    return header.strip(), rest.strip()


def generate_init_imports(root_dir: str | Path):
    """
    Recursively process a package directory and update __init__.py files
    with imports of all submodules and subpackages.
    """
    root_dir = Path(root_dir)

    def is_python_file(path: Path) -> bool:
        return path.is_file() and path.suffix == ".py" and path.stem != "__init__"

    def is_package(path: Path) -> bool:
        return path.is_dir() and (path / "__init__.py").exists()

    def process_directory(directory: Path):
        init_file = directory / "__init__.py"
        if not init_file.exists():
            return

        # Get all immediate Python files and subpackages
        contents = []
        for item in directory.iterdir():
            # Skip __pycache__ and other hidden directories
            if item.name.startswith("_"):
                continue

            if is_python_file(item):
                # Add import for Python modules
                contents.append(f"from . import {item.stem} as {item.stem}")
            elif is_package(item):
                # Add import for subpackages
                contents.append(f"from . import {item.name} as {item.name}")
                # Recursively process subpackage
                process_directory(item)

        if contents:
            # Sort imports for consistency
            contents.sort()

            # Read existing content
            existing_content = init_file.read_text() if init_file.exists() else ""

            # Extract header (comments and docstring) and rest of content
            header, rest = get_file_header(existing_content)

            # Prepare new imports
            new_imports = "\n".join(contents) + "\n\n"

            # Combine all parts
            new_content = []
            if header:
                new_content.append(header)
                new_content.append("")  # Empty line after header
            new_content.append(new_imports.rstrip())
            if rest:
                new_content.append(rest)

            # Write the updated content
            init_file.write_text("\n".join(new_content))

    process_directory(root_dir)


def generate(config: ModelConfig):
    ruff = shutil.which("ruff")
    if not ruff:
        raise ValueError("ruff executable not found")
    generated_path = Path(config.namespace.replace(".", "/"))
    if generated_path.exists():
        raise ValueError(f"Output directory {generated_path} already exists")
    workdir = Path(tempfile.mkdtemp())
    workdir.mkdir(parents=True, exist_ok=True)
    input_, extra_template_data = process_input(config, workdir)
    base_class = "cloudcoil.resources.Resource"
    additional_imports = [
        "cloudcoil._pydantic.BaseModel",
        "cloudcoil.resources.ResourceList",
    ]
    header = f"# Generated by cloudcoil-model-codegen v{__version__}\n# DO NOT EDIT"
    generate_code(
        [
            "--input",
            str(input_),
            "--output",
            str(workdir),
            "--snake-case-field",
            "--target-python-version",
            "3.10",
            "--base-class",
            base_class,
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--enum-field-as-literal",
            "all",
            "--input-file-type",
            "jsonschema",
            "--disable-appending-item-suffix",
            "--disable-timestamp",
            "--collapse-root-models",
            "--use-annotated",
            "--wrap-string-literal",
            "--use-default-kwarg",
            "--extra-template-data",
            str(extra_template_data),
            "--additional-imports",
            ",".join(additional_imports),
            "--custom-template-dir",
            str(Path(__file__).parent / "templates"),
            "--use-default",
            "--custom-file-header",
            header,
        ]
    )
    rewrite_imports(config.namespace, workdir)
    ruff_check_fix_args = [
        ruff,
        "check",
        "--fix",
        "--preview",
        str(workdir),
        "--config",
        str(Path(__file__).parent / "ruff.toml"),
    ]
    subprocess.run(ruff_check_fix_args, check=True)
    ruff_format_args = [
        ruff,
        "format",
        str(workdir),
        "--config",
        str(Path(__file__).parent / "ruff.toml"),
    ]
    subprocess.run(ruff_format_args, check=True)
    Path(workdir / generated_path / "py.typed").touch()
    Path(workdir / generated_path / "__init__.py").touch()
    generate_init_imports(workdir / generated_path)
    output_dir = config.output or Path(".")
    shutil.move(workdir / generated_path, output_dir / generated_path)
