import argparse
import ast
import json
import keyword
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any, Dict, Iterator, List, Literal, Set, Tuple

import httpx
import yaml
from cloudcoil.codegen.import_rewriter import rewrite_imports
from cloudcoil.codegen.schema import (
    SchemaError,
    infer_resource_identities,
    inferred_name,
    iter_refs,
    lift_inline_objects,
    normalize_definition,
    pointer_name,
    resolve_relative_refs,
    rewrite_refs,
)
from cloudcoil.codegen.typing import generate_lookup
from cloudcoil.version import __version__
from datamodel_code_generator.__main__ import (
    main as generate_code,
)
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class SchemaLoader(yaml.SafeLoader):
    """Kubernetes YAML loader without PyYAML's special '=' value resolver."""


SchemaLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items() if key != "="
}


class Update(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
    )
    match_: Annotated[str | re.Pattern, Field(alias="match"), BeforeValidator(re.compile)]
    jsonpath: str
    value: Any | None = None
    delete: bool = False


class Alias(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
    )
    from_: Annotated[str, Field(alias="from")]
    to: str


class Transformation(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
    )
    match_: Annotated[str | re.Pattern, Field(alias="match"), BeforeValidator(re.compile)]
    replace: str | None = None
    namespace: str | None = None
    exclude: bool = False

    @model_validator(mode="after")
    def validate_transformation_mode(self):
        if self.exclude:
            if self.replace or self.namespace:
                raise ValueError(
                    "Exclusion transformations cannot have replace or namespace values"
                )
        else:
            if not self.replace:
                raise ValueError("replace is required for non-exclusion transformations")
        return self


class ModelConfig(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        validate_default=True,
    )
    infer: bool = True
    crd_namespace: Annotated[str | None, Field(alias="crd-namespace")] = None
    namespace: str
    input_: Annotated[list[str] | str, Field(alias="input")]
    output: Path | None = None
    mode: Literal["resource", "base"] = "resource"
    transformations: list[Transformation] = []
    updates: list[Update] = []
    generate_init: Annotated[bool, Field(alias="generate-init")] = True
    generate_py_typed: Annotated[bool, Field(alias="generate-py-typed")] = True
    exclude_unknown: Annotated[bool, Field(alias="exclude-unknown")] = False
    additional_datamodel_codegen_args: Annotated[
        list[str], Field(alias="additional-datamodel-codegen-args")
    ] = []
    aliases: list[Alias] = []
    log_level: Annotated[str, Field(alias="log-level")] = "INFO"

    @model_validator(mode="after")
    def _add_namespace(self):
        if not self.namespace or any(
            not part.isidentifier() or keyword.iskeyword(part) for part in self.namespace.split(".")
        ):
            raise ValueError("namespace must be a dotted Python package name")
        self.transformations = [item.model_copy(deep=True) for item in self.transformations]
        for transformation in self.transformations:
            if transformation.exclude:
                if transformation.replace or transformation.namespace:
                    raise ValueError(
                        "Exclusion transformations cannot have replace or namespace values"
                    )
            else:
                if not transformation.replace:
                    raise ValueError(f"replace is required for non-exclusion {transformation=}")
                if not transformation.namespace:
                    transformation.namespace = self.namespace
        return self


def detect_schema_type(schema: dict) -> Literal["openapi", "jsonschema"]:
    """Detect if the schema is OpenAPI v3 or JSONSchema."""
    if "openapi" in schema and schema["openapi"].startswith("3."):
        return "openapi"
    return "jsonschema"


def get_schema_definitions(schema: dict) -> dict:
    """Get the definitions section based on schema type."""
    if detect_schema_type(schema) == "openapi":
        return schema.get("components", {}).get("schemas", {})
    return schema.get("definitions", schema.get("$defs", {}))


def set_schema_definitions(schema: dict, definitions: dict) -> None:
    """Set the definitions section based on schema type."""
    if detect_schema_type(schema) == "openapi":
        if "components" not in schema:
            schema["components"] = {}
        schema["components"]["schemas"] = definitions
    elif "$defs" in schema and "definitions" not in schema:
        schema["$defs"] = definitions
    else:
        schema["definitions"] = definitions


def delete_value_at_path(obj: dict, path: str) -> None:
    """Delete a value at a specified JSON path with support for array indices.

    Empty path segments are skipped. Multiple dots are treated as a single dot.
    Array indices can be used at any level including root.

    Examples:
        delete_value_at_path(obj, "foo.bar")  # {"foo": {}}
        delete_value_at_path(obj, "foo..bar") # {"foo": {}}
        delete_value_at_path(obj, "[0].foo")  # [{}]
    """
    # Handle empty path
    if not path:
        return

    # Split by dots and handle array indices
    segments = []
    current_segment = ""
    i = 0
    while i < len(path):
        if path[i] == ".":
            if current_segment:
                segments.append(current_segment)
            current_segment = ""
        elif path[i] == "[":
            if current_segment:
                segments.append(current_segment)
            current_segment = "["
        else:
            current_segment += path[i]
        i += 1

    if current_segment:
        segments.append(current_segment)

    segments = [s for s in segments if s]

    if not segments:
        return

    def parse_segment(segment: str):
        """Parse a path segment to determine if it's an array index."""
        if segment.startswith("[") and segment.endswith("]"):
            try:
                return int(segment[1:-1])
            except ValueError:
                return segment
        return segment

    # Start with the full object
    current = obj

    # Navigate through all but the last segment
    for segment in segments[:-1]:
        key = parse_segment(segment)

        # Handle array index
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                return
            current = current[key]
        # Handle dict key
        else:
            if not isinstance(current, dict) or key not in current:
                return
            current = current[key]

    # Handle the final segment
    final_segment = parse_segment(segments[-1])

    # Handle array index for final segment
    if isinstance(final_segment, int):
        if not isinstance(current, list) or final_segment >= len(current):
            return
        current.pop(final_segment)
    # Handle dict key for final segment
    elif isinstance(current, dict) and final_segment in current:
        del current[final_segment]


def set_value_at_path(obj: dict, path: str, value: Any) -> None:
    """Set a value at a specified JSON path with support for array indices.

    Empty path segments are skipped. Multiple dots are treated as a single dot.
    Array indices can be used at any level including root.
    Empty array slots are filled with None.

    Examples:
        set_value_at_path(obj, "foo.bar", "value")  # {"foo": {"bar": "value"}}
        set_value_at_path(obj, "foo..bar", "value") # {"foo": {"bar": "value"}}
        set_value_at_path(obj, "[0].foo", "value")  # [{"foo": "value"}]
    """
    if not path:
        return
    segments = []
    current_segment = ""
    i = 0
    while i < len(path):
        if path[i] == ".":
            if current_segment:
                segments.append(current_segment)
            current_segment = ""
        elif path[i] == "[":
            if current_segment:
                segments.append(current_segment)
            current_segment = "["
        else:
            current_segment += path[i]
        i += 1

    if current_segment:
        segments.append(current_segment)

    segments = [s for s in segments if s]

    if not segments:
        return

    def parse_segment(segment: str):
        """Parse a path segment to determine if it's an array index."""
        if segment.startswith("[") and segment.endswith("]"):
            try:
                return int(segment[1:-1])
            except ValueError:
                return segment
        return segment

    current = obj

    for i, segment in enumerate(segments[:-1]):
        key = parse_segment(segment)
        next_segment = parse_segment(segments[i + 1])

        if isinstance(key, int):
            if not isinstance(current, list):
                return
            while len(current) <= key:
                current.append(None)
            if current[key] is None:
                current[key] = {} if not isinstance(next_segment, int) else []
            current = current[key]
        else:
            if not isinstance(current, dict):
                return
            if key not in current:
                current[key] = {} if not isinstance(next_segment, int) else []
            current = current[key]

    final_segment = parse_segment(segments[-1])

    if isinstance(final_segment, int):
        if not isinstance(current, list):
            return
        while len(current) <= final_segment:
            current.append(None)
        current[final_segment] = value
    elif isinstance(current, dict):
        current[final_segment] = value


def process_definitions(schema: dict) -> None:
    """Process definitions in either JSONSchema or OpenAPI format."""
    definitions = get_schema_definitions(schema)

    for definition in definitions.values():
        normalize_definition(definition)

        # Handle both OpenAPI and JSONSchema GVK metadata
        gvks = definition.get("x-kubernetes-group-version-kind") or []
        if len(gvks) > 1:
            # Shared transport objects (Status, DeleteOptions, WatchEvent) do not
            # have one resource endpoint. Preserve their accepted identities.
            props = definition.get("properties", {})
            for field, values in (
                (
                    "apiVersion",
                    [
                        f"{g['group']}/{g['version']}" if g.get("group") else g["version"]
                        for g in gvks
                    ],
                ),
                ("kind", [g["kind"] for g in gvks]),
            ):
                if field in props:
                    props[field]["enum"] = list(dict.fromkeys(values))
            continue
        gvk = gvks[0] if gvks else {}
        if not gvk:
            continue

        group = gvk.get("group", "")
        version = gvk.get("version")
        kind = gvk.get("kind")

        if not (version and kind):
            continue

        # Construct apiVersion
        api_version = f"{group}/{version}" if group else version

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


def process_updates(updates: list[Update], schema: dict) -> None:
    """Process updates by setting values at specified JSON paths."""
    definitions = get_schema_definitions(schema)

    for definition_name, definition in definitions.items():
        for update in updates:
            assert isinstance(update.match_, re.Pattern)
            if update.match_.match(definition_name):
                if update.delete:
                    delete_value_at_path(definition, update.jsonpath)
                else:
                    value = (
                        update.match_.sub(update.value, definition_name)
                        if isinstance(update.value, str)
                        else deepcopy(update.value)
                    )
                    set_value_at_path(definition, update.jsonpath, value)


def process_transformations(transformations: list[Transformation], schema: dict) -> dict:
    definitions = get_schema_definitions(schema)
    renames: dict[str, str | None] = {}
    for name in definitions:
        renames[name] = name
        for transformation in transformations:
            assert isinstance(transformation.match_, re.Pattern)
            if transformation.match_.match(name):
                renames[name] = (
                    None
                    if transformation.exclude
                    else transformation.match_.sub(
                        f"{transformation.namespace}.{transformation.replace}", name
                    )
                )
                break

    prefix = (
        "#/components/schemas/"
        if detect_schema_type(schema) == "openapi"
        else ("#/$defs/" if "$defs" in schema and "definitions" not in schema else "#/definitions/")
    )
    # Excluding a definition also excludes its dependents. Never emit '#/.../None'.
    changed = True
    while changed:
        changed = False
        excluded = {
            prefix + pointer_name(name) for name, target in renames.items() if target is None
        }
        for name, definition in definitions.items():
            if renames[name] is not None and any(ref in excluded for ref in iter_refs(definition)):
                renames[name] = None
                changed = True

    output = {}
    origins: dict[str, str] = {}
    for name, target in renames.items():
        if target is None:
            continue
        if target in output:
            raise SchemaError(
                f"Definitions {origins[target]!r} and {name!r} both map to {target!r}"
            )
        output[target] = definitions[name]
        origins[target] = name
    result = deepcopy(schema)
    set_schema_definitions(result, output)
    return rewrite_refs(
        result,
        {
            prefix + pointer_name(name): prefix + pointer_name(target)
            for name, target in renames.items()
            if target is not None
        },
    )


def load_yaml_documents(file_path: str) -> Iterator[dict]:
    """Load YAML documents from a file."""
    with open(file_path, "r") as f:
        try:
            yield from yaml.load_all(f, Loader=SchemaLoader)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML file: {e}")


def is_crd(doc: dict) -> bool:
    """Check if a document is a CustomResourceDefinition."""
    return (
        isinstance(doc, dict)
        and doc.get("apiVersion") in {"apiextensions.k8s.io/v1", "apiextensions.k8s.io/v1beta1"}
        and doc.get("kind") == "CustomResourceDefinition"
    )


def convert_crd_to_schema(crd: dict) -> Dict[str, Any]:
    """Convert a CRD to an OpenAPI schema."""
    schema: Dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Generated Schema", "version": "v1"},
        "components": {"schemas": {}},
    }

    spec = crd.get("spec", {})
    versions = spec.get("versions") or [
        {"name": spec.get("version"), "schema": spec.get("validation", {})}
    ]
    group = spec.get("group", "")
    kind = spec.get("names", {}).get("kind", "")
    if not group or not kind:
        raise SchemaError("CRD spec.group and spec.names.kind are required")

    # Add ObjectMeta if not already in components
    schema["components"]["schemas"]["io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta"] = {
        "type": "object",
    }

    for version in versions:
        if not version.get("served", True):
            continue

        version_name = version.get("name", "")
        schema_obj = deepcopy(version.get("schema", {}).get("openAPIV3Schema", {}))

        if not schema_obj or not version_name:
            raise SchemaError(
                f"CRD {group}/{kind} version {version_name!r} has no structural schema"
            )
        schema_obj.setdefault("type", "object")
        schema_obj.setdefault("properties", {})

        # Convert group to reverse domain format
        if group:
            reverse_group = ".".join(reversed(group.split(".")))
            def_name = f"{reverse_group}.{version_name}.{kind}"
        else:
            def_name = f"core.{version_name}.{kind}"

        schema["components"]["schemas"][def_name] = schema_obj

        # Add GVK metadata
        schema["components"]["schemas"][def_name]["x-kubernetes-group-version-kind"] = [
            {
                "group": group,
                "version": version_name,
                "kind": kind,
            }
        ]

        # Handle spec and status properties
        if "properties" in schema_obj:
            properties = schema_obj["properties"]
            properties.setdefault("apiVersion", {"type": "string"})
            properties.setdefault("kind", {"type": "string"})

            # Handle spec property
            if "spec" in properties:
                spec_schema = properties["spec"]
                spec_name = f"{def_name}Spec"
                schema["components"]["schemas"][spec_name] = spec_schema
                properties["spec"] = {"$ref": f"#/components/schemas/{spec_name}"}

            # Handle status property
            if "status" in properties:
                status_schema = properties["status"]
                status_name = f"{def_name}Status"
                schema["components"]["schemas"][status_name] = status_schema
                properties["status"] = {"$ref": f"#/components/schemas/{status_name}"}

            # Set metadata reference
            properties["metadata"] = {
                "$ref": "#/components/schemas/io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta"
            }

    return schema


def merge_schemas(schemas: list[dict[str, Any]]) -> dict:
    """Merge definitions across dialects, rewriting references and rejecting conflicts."""
    merged: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Generated Schema", "version": "v1"},
        "paths": {},
        "components": {"schemas": {}},
    }
    definitions = merged["components"]["schemas"]
    all_names = {name for schema in schemas for name in get_schema_definitions(schema)}
    for schema in schemas:
        source = get_schema_definitions(schema)
        mappings = {
            prefix + pointer_name(name): "#/components/schemas/" + pointer_name(name)
            for name in all_names
            for prefix in ("#/definitions/", "#/$defs/", "#/components/schemas/")
        }
        for name, definition in source.items():
            definition = rewrite_refs(definition, mappings)
            if name in definitions and definitions[name] != definition:
                raise SchemaError(f"Conflicting definitions for {name!r} in input sources")
            definitions[name] = definition
        merged["paths"].update(deepcopy(schema.get("paths", {})))
    return merged


def fetch_remote_content(url: str) -> str:
    """Fetch content from a remote URL."""
    response = httpx.get(url, follow_redirects=True)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch {url}")
    return response.text


def load_yaml_content(content: str) -> Iterator[dict]:
    """Load YAML documents from a string."""
    try:
        yield from yaml.load_all(content, Loader=SchemaLoader)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML content: {e}")


def process_input(config: ModelConfig, workdir: Path) -> tuple[Path, Path]:
    schema_file = workdir / "schema.json"
    extra_data_file = workdir / "extra_data.json"
    inputs = config.input_ if isinstance(config.input_, list) else [config.input_]
    schemas = []
    crd_groups = set()

    def collect(doc, source):
        if not isinstance(doc, dict):
            return
        doc = resolve_relative_refs(doc, source)
        if is_crd(doc):
            crd_groups.add(doc["spec"]["group"])
            schemas.append(convert_crd_to_schema(doc))
        elif doc.get("kind") in {"List", "CustomResourceDefinitionList"}:
            for item in doc.get("items", []):
                collect(item, source)
        elif any(key in doc for key in ("openapi", "swagger", "definitions", "$defs")):
            schemas.append(doc)
        elif "type" in doc or "properties" in doc:
            schemas.append({"definitions": {doc.get("title", "Model"): doc}})

    for input_ in inputs:
        content = (
            fetch_remote_content(input_)
            if input_.startswith(("http://", "https://"))
            else Path(input_).read_text()
        )
        for doc in load_yaml_content(content):
            collect(doc, input_)
    if not schemas:
        raise SchemaError(f"No CRDs, OpenAPI documents, or JSON schemas found in {inputs}")
    schema = deepcopy(schemas[0]) if len(schemas) == 1 else merge_schemas(schemas)

    if config.infer:
        infer_resource_identities(schema, get_schema_definitions(schema))

    transformations = list(config.transformations)
    if config.crd_namespace:
        transformations += [
            Transformation(
                match_=r"^io\.k8s\.apimachinery\..*\.(.+)$",
                replace=r"apimachinery.\g<1>",
                namespace="cloudcoil",
            ),
            Transformation(
                match_=f"^{re.escape(config.crd_namespace)}\\.(.*)$",
                replace=r"\g<1>",
                namespace=config.namespace,
            ),
        ]
    if config.infer:
        # Explicit rules win; inferred rules precede only the automatic catch-all.
        inferred = []
        for name in get_schema_definitions(schema):
            target = inferred_name(name, config.namespace, crd_groups)
            package, _, model = target.rpartition(".")
            if model in {"Builder", "BuilderList"}:
                model = model.replace("Builder", "BuilderResource")
            elif package != "cloudcoil.apimachinery":
                from cloudcoil import apimachinery

                if hasattr(apimachinery, model):
                    parts = name.split(".")[:-1]
                    owner = next(
                        (
                            part
                            for part in reversed(parts)
                            if not re.fullmatch(r"v\d+(?:(?:alpha|beta)\d+)?", part)
                        ),
                        "Custom",
                    )
                    model = owner[:1].upper() + owner[1:] + model
            if not config.exclude_unknown or target != f"{config.namespace}.{name}":
                inferred.append(
                    Transformation(match_=f"^{re.escape(name)}$", replace=model, namespace=package)
                )
        transformations.extend(inferred)
    transformations.append(
        Transformation(match_=r"^(.*)$", exclude=True)
        if config.exclude_unknown
        else Transformation(match_=r"^(.*)$", replace=r"\g<1>", namespace=config.namespace)
    )
    schema = process_transformations(transformations, schema)

    # Then apply any updates
    if config.updates:
        logger.info("Applying %d updates", len(config.updates))
        process_updates(config.updates, schema)

    # Continue with definition processing
    logger.debug("Processing schema definitions")
    process_definitions(schema)

    if config.infer:
        prefix = (
            "#/components/schemas/"
            if detect_schema_type(schema) == "openapi"
            else ("#/$defs/" if "$defs" in schema else "#/definitions/")
        )
        lift_inline_objects(get_schema_definitions(schema), prefix)

    logger.debug("Generating extra data")
    extra_data = generate_extra_data(schema)

    # Write schema and extra data files
    logger.debug("Writing schema to %s", schema_file)
    with open(schema_file, "w") as f:
        json.dump(schema, f, indent=2)
    logger.debug("Writing extra data to %s", extra_data_file)
    with open(extra_data_file, "w") as f:
        json.dump(extra_data, f, indent=2)

    return schema_file, extra_data_file


def generate_extra_data(schema: dict) -> dict:
    """Generate extra data for both OpenAPI and JSONSchema formats."""
    extra_data = {}
    definitions = get_schema_definitions(schema)

    for prop_name, prop in definitions.items():
        extra_prop_data = {
            "is_gvk": False,
            "is_list": False,
            "preserve_unknown": bool(prop.get("x-kubernetes-preserve-unknown-fields")),
        }

        # Check for GVK
        if len(prop.get("x-kubernetes-group-version-kind", [])) == 1:
            extra_prop_data["is_gvk"] = True

        # Check for List type
        if prop_name.endswith("List") and "properties" in prop:
            required_list_props = {"metadata", "items", "apiVersion", "kind"}
            item_ref = prop["properties"].get("items", {}).get("items", {}).get("$ref", "")
            item_name = item_ref.rsplit("/", 1)[-1]
            # Use a generic alias only when the referenced resource is the conventional
            # sibling. Unusual list shapes stay ordinary generated resource models.
            if (
                set(prop["properties"]) == required_list_props
                and item_name == prop_name[:-4]
                and definitions.get(item_name, {}).get("x-kubernetes-group-version-kind")
            ):
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
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
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


def parse_model_fields(content: str) -> Dict[str, List[Tuple]]:
    """Parse Python file content and extract Pydantic model fields."""
    models = {}
    tree = ast.parse(content)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if it's a Pydantic model
        if not any(
            base.id in ("BaseModel", "Resource")
            for base in node.bases
            if isinstance(base, ast.Name)
        ):
            continue

        fields = []
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue

            assert isinstance(stmt.target, ast.Name)
            field_name = stmt.target.id
            type_annotation = ast.unparse(stmt.annotation)
            default_value = ast.unparse(stmt.value) if stmt.value else None

            fields.append((field_name, type_annotation, default_value))

        if fields:
            models[node.name] = fields

    return models


def find_duplicate_models(workdir: Path) -> Dict[str, Set[str]]:
    """Find models with identical fields across all Python files."""
    model_fields: Dict[Tuple[Tuple[str, str, str], ...], Set[str]] = {}
    model_locations: Dict[str, str] = {}

    for file in workdir.rglob("*.py"):
        if file.name == "__init__.py":
            continue

        content = file.read_text()
        file_models = parse_model_fields(content)

        for model_name, fields in file_models.items():
            fields_tuple = tuple(sorted(fields, key=lambda f: f[0]))
            model_locations[model_name] = str(file.relative_to(workdir))
            if fields_tuple in model_fields:
                model_fields[fields_tuple].add(model_name)
            else:
                model_fields[fields_tuple] = {model_name}

    return {
        sorted(models)[0]: models - {sorted(models)[0]}
        for models in model_fields.values()
        if len(models) > 1
    }


def generate(config: ModelConfig):
    """Generate into an isolated staging directory, then publish validated output."""
    with tempfile.TemporaryDirectory(prefix="cloudcoil_codegen_") as directory:
        _generate(config, Path(directory))


def _generate(config: ModelConfig, workdir: Path):
    logger.debug("Starting code generation with config: %s", config.model_dump())

    ruff = shutil.which("ruff")
    if not ruff:
        logger.error("ruff executable not found in PATH")
        raise ValueError("ruff executable not found")

    logger.info("Using ruff from: %s", ruff)
    config = config.model_copy(deep=True)
    generated_path = Path(config.namespace.replace(".", "/"))
    logger.debug("Created temporary working directory: %s", workdir)

    logger.info("Processing input files...")
    input_file, extra_data_file = process_input(config, workdir)
    logger.debug("Generated schema file: %s", input_file)
    logger.debug("Generated extra data file: %s", extra_data_file)

    args = []
    # Reuse external model packages as imports, rather than generating throwaway
    # copies that can form cross-package cycles with the requested output.
    schema = json.loads(input_file.read_text())
    definitions = get_schema_definitions(schema)
    prefix = (
        "#/components/schemas/"
        if detect_schema_type(schema) == "openapi"
        else ("#/$defs/" if "$defs" in schema else "#/definitions/")
    )
    external: dict[str, dict] = {}
    references = {}
    for name in list(definitions):
        if name.startswith(config.namespace + "."):
            continue
        package, _, model = name.rpartition(".")
        external.setdefault(package, {})[model] = definitions.pop(name)
    external_mappings = []
    for index, (package, models) in enumerate(sorted(external.items())):
        external_file = workdir / f"external_{index}.json"
        external_file.write_text(json.dumps({"definitions": models}))
        for model in models:
            references[prefix + pointer_name(f"{package}.{model}")] = (
                f"{external_file}#/definitions/{pointer_name(model)}"
            )
        external_mappings.append(f"{external_file}={package}")
    if external_mappings:
        args += ["--external-ref-mapping", *external_mappings]
    schema = rewrite_refs(schema, references)
    input_file.write_text(json.dumps(schema))
    extra = json.loads(extra_data_file.read_text())
    if config.mode == "base":
        for model_data in extra.values():
            model_data.update(is_gvk=False, is_list=False)
    extra["#all#"] = {"external_packages": list(external)}
    extra_data_file.write_text(json.dumps(extra))
    args.append(f"--extra-template-data={extra_data_file}")
    base_class = "cloudcoil.pydantic.BaseModel"
    additional_imports = [
        "typing.Callable",
        "typing.Union",
        "typing.Type",
        "typing.cast",
        "typing.overload",
        "cloudcoil.pydantic.BaseBuilder",
        "cloudcoil.pydantic.BaseModel",
        "cloudcoil.pydantic.BaseModelBuilder",
        "cloudcoil.pydantic.GenericListBuilder",
        "cloudcoil.pydantic.BuilderContextBase",
        "cloudcoil.pydantic.ListBuilderContext",
        "cloudcoil.pydantic.Self",
        "cloudcoil.pydantic.Never",
        "cloudcoil.pydantic.UNSET",
        "pydantic.ConfigDict",
    ]
    if config.mode == "resource":
        logger.debug("Using resource mode with Resource base class")
        base_class = "cloudcoil.resources.Resource"
        additional_imports += [
            "cloudcoil.resources.ResourceList",
        ]

    args.append(f"--additional-imports={','.join(additional_imports)}")
    if config.infer:
        # The wire names remain aliases; Python API methods remain callable.
        reserved = {"builder", "build", "new", "list_builder", "cls"}
        from cloudcoil.resources import Resource

        reserved.update(
            name
            for name in dir(Resource)
            if not name.startswith("_") and callable(getattr(Resource, name))
        )
        explicit = {alias.from_ for alias in config.aliases}
        config.aliases.extend(
            Alias(from_=name, to=name + "_") for name in sorted(reserved - explicit)
        )
    if config.aliases:
        logger.debug("Processing %d aliases", len(config.aliases))
        (workdir / "aliases.json").write_text(
            json.dumps({alias.from_: alias.to for alias in config.aliases}, indent=2)
        )
        args.append(f"--aliases={str(workdir / 'aliases.json')}")
    header = f"# Generated by cloudcoil-model-codegen v{__version__}\n# DO NOT EDIT"

    logger.info("Generating code...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = generate_code(
            [
                "--input",
                str(input_file),
                "--output",
                str(workdir),
                "--snake-case-field",
                "--strict-refs",
                "--target-python-version",
                "3.14",
                "--base-class",
                base_class,
                "--output-model-type",
                "pydantic_v2.BaseModel",
                "--enum-field-as-literal",
                "all",
                "--input-file-type",
                detect_schema_type(json.loads(input_file.read_text())),
                "--disable-appending-item-suffix",
                "--use-title-as-name",
                "--disable-timestamp",
                "--use-annotated",
                "--use-default-kwarg",
                "--use-field-description",
                "--custom-template-dir",
                str(Path(__file__).parent / "templates"),
                "--use-default",
                "--custom-file-header",
                header,
                *args,
                *config.additional_datamodel_codegen_args,
            ]
        )
    if result not in (None, 0):
        raise RuntimeError(f"datamodel-code-generator failed with exit code {result}")
    logger.debug("Code generation completed")

    logger.info("Rewriting imports...")
    rewrite_imports(config.namespace, workdir)

    if config.generate_init:
        logger.debug("Generating __init__.py files")
        Path(workdir / generated_path / "__init__.py").touch()
        generate_init_imports(workdir / generated_path)
        generate_lookup(workdir / generated_path, config.namespace)
    else:
        logger.debug("Skipping __init__.py generation")
        Path(workdir / generated_path / "__init__.py").unlink(missing_ok=True)

    if config.generate_py_typed:
        logger.debug("Generating py.typed marker")
        Path(workdir / generated_path / "py.typed").touch()

    logger.info("Running ruff checks and formatting...")
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

    for file in (workdir / generated_path).rglob("*.py"):
        compile(file.read_text(), str(file), "exec")
    output_dir = config.output or Path(".")
    logger.info("Moving generated files to output directory: %s", output_dir)

    # Copy directory contents, avoiding shutil.move's repeated-generation nesting bug.
    destination = output_dir / generated_path
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / ".cloudcoil-generated.json"
    files = sorted(
        str(path.relative_to(workdir / generated_path))
        for path in (workdir / generated_path).rglob("*")
        if path.is_file()
    )
    previous = json.loads(manifest.read_text()) if manifest.exists() else []
    for relative in previous:
        stale = destination / relative
        if not stale.resolve().is_relative_to(destination.resolve()):
            raise SchemaError("Generated-file manifest contains a path outside the output package")
    shutil.copytree(workdir / generated_path, destination, dirs_exist_ok=True)
    for relative in set(previous) - set(files):
        (destination / relative).unlink(missing_ok=True)
    manifest.write_text(json.dumps(files, indent=2) + "\n")

    logger.info("Code generation completed successfully")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Kubernetes API models for CloudCoil",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"cloudcoil-model-codegen {__version__}"
    )
    parser.add_argument("--namespace", help="Namespace for the model package")
    parser.add_argument("--input", nargs="+", help="CRD, OpenAPI, or JSON schema files/URLs")
    parser.add_argument(
        "--no-infer", action="store_true", help="Disable automatic schema naming and inference"
    )
    parser.add_argument("--output", help="Output directory", type=Path, default=None)
    parser.add_argument(
        "--mode",
        choices=["resource", "base"],
        default="resource",
        help="Generation mode",
    )
    parser.add_argument(
        "--transformation",
        action="append",
        help=(
            "Transformation pattern in format 'match:replace[:namespace]' or 'match!' for exclusions. "
            "Exclusions cannot have replace or namespace values."
        ),
        default=[],
    )
    parser.add_argument("--config", help="Path to the configuration file", default="pyproject.toml")
    parser.add_argument(
        "--no-init",
        action="store_true",
        help="Don't generate __init__.py files",
    )
    parser.add_argument(
        "--exclude-unknown",
        action="store_true",
        help="Exclude unknown definitions",
        default=False,
    )
    parser.add_argument(
        "--no-py-typed",
        action="store_true",
        help="Don't generate py.typed file",
    )
    parser.add_argument(
        "--crd-namespace",
        help="Namespace for CRD resources",
    )
    parser.add_argument(
        "--additional-codegen-arg",
        action="append",
        help="Additional arguments to pass to datamodel-codegen",
        dest="additional_datamodel_codegen_args",
        default=[],
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level",
    )
    return parser


def parse_transformations(transformation_args: List[str]) -> List[Transformation]:
    transformations = []
    for transformation in transformation_args:
        is_exclusion = transformation.endswith("!")
        if is_exclusion:
            # For exclusions, only accept the match pattern
            match_ = transformation[:-1]
            transformations.append(Transformation(match_=match_, exclude=True))
            continue

        parts = transformation.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(
                "Invalid transformation format. Use 'match:replace[:namespace]' "
                "or 'match!' for exclusions"
            )

        match_, replace = parts[0], parts[1]
        namespace = parts[2] if len(parts) > 2 else None

        transformations.append(
            Transformation(
                match_=match_,
                replace=replace,
                namespace=namespace,
            )
        )
    return transformations


def create_model_config_from_args(args: argparse.Namespace) -> ModelConfig | None:
    if not (args.namespace and args.input):
        return None

    transformations = parse_transformations(args.transformation)

    return ModelConfig(
        namespace=args.namespace,
        input_=args.input,
        infer=not args.no_infer,
        output=args.output,
        mode=args.mode,
        transformations=transformations,
        generate_init=not args.no_init,
        generate_py_typed=not args.no_py_typed,
        crd_namespace=args.crd_namespace,
        additional_datamodel_codegen_args=args.additional_datamodel_codegen_args,
        exclude_unknown=args.exclude_unknown,
        log_level=args.log_level,
    )


def process_cli_args(args: argparse.Namespace) -> bool:
    config = create_model_config_from_args(args)
    if config:
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

    # Configure logging
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.debug("Starting cloudcoil-model-codegen v%s", __version__)

    if not process_cli_args(args) and not process_config_file(args.config):
        logger.error("No valid configuration found")
        parser.print_help()
        sys.exit(1)
