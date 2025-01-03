import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Literal

import httpx
from cloudcoil._pydantic import BaseModel
from cloudcoil.version import __version__
from datamodel_code_generator.__main__ import (
    main as generate_code,
)
from pydantic import AfterValidator, BeforeValidator, Field


class Substitution(BaseModel):
    from_: Annotated[str | re.Pattern, Field(alias="from"), BeforeValidator(re.compile)]
    to: str


class ModelConfig(BaseModel):
    name: str
    input_: Annotated[str, Field(alias="input")]
    mode: Literal["basemodel", "resource"] = "resource"
    substitute: Annotated[
        list[Substitution],
        AfterValidator(
            lambda value: list(
                map(
                    lambda subs: Substitution(from_=subs.from_, to="models." + subs.to),
                    value,
                )
            )
        ),
    ] = []


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
    for definition_name in schema["definitions"]:
        new_name = definition_name
        for substitution in substitutions:
            new_name = re.sub(substitution.from_, substitution.to, new_name)
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
    apimachinery_substitution = Substitution(
        from_=re.compile(r"io\.k8s\.apimachinery\..*\.(.+)"), to=r"apimachinery.\g<1>"
    )
    schema = process_substitutions([apimachinery_substitution] + config.substitute, schema)
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


def generate(config: ModelConfig):
    output_dir = Path("cloudcoil") / "models" / config.name
    if output_dir.exists():
        raise ValueError(f"Output directory {output_dir} already exists")
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
            "--use-annotated",
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
    # For every file in the models directory
    # rename the apimachinery import to import from cloudcoil
    # For eg from ... import apimachinery
    # should be renamed to from cloudcoil import apimachinery
    # Do it for every level of import
    # For eg from ..... import apimachinery
    # For eg from .... import apimachinery
    # For eg from .. import apimachinery
    # For eg from . import apimachinery
    apimachinery_regex = re.compile(r"(from\s+)(\.\.+\s+)?(import\s+)(apimachinery)")
    for file in workdir.glob("models/**/*.py"):
        with open(file, "r") as f:
            content = f.read()
        # Use a regex replace
        content = apimachinery_regex.sub(
            r"from cloudcoil import apimachinery",
            content,
        )
        with open(file, "w") as f:
            f.write(content)

    # Invoke ruff to generate the final code
    # Find the ruff executable
    ruff = shutil.which("ruff")
    if not ruff:
        raise ValueError("ruff executable not found")
    # uv run ruff format cloudcoil tests
    # uv run ruff check --fix --unsafe-fixes cloudcoil tests

    ruff_check_fix_args = [
        ruff,
        "check",
        "--silent",
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
        "--silent",
        str(workdir),
        "--config",
        str(Path(__file__).parent / "ruff.toml"),
    ]
    subprocess.run(ruff_format_args, check=True)
    Path(workdir / "models" / "__init__.py").unlink(missing_ok=True)
    shutil.move(workdir / "models", output_dir)
