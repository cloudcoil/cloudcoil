"""Generate and import real Python, then exercise Kubernetes wire semantics."""

import copy
import importlib
import json
import subprocess
import sys

import pytest
import yaml
from pydantic import ValidationError

from cloudcoil.codegen.generator import (
    ModelConfig,
    Transformation,
    Update,
    convert_crd_to_schema,
    generate,
    get_schema_definitions,
    merge_schemas,
    process_input,
    process_transformations,
    process_updates,
)
from cloudcoil.codegen.schema import SchemaError, normalize_definition


def crd(kind="Widget", group="widgets.example.com"):
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "spec": {
            "group": group,
            "names": {"kind": kind, "plural": kind.lower() + "s"},
            "scope": "Namespaced",
            "versions": [
                {
                    "name": "v1",
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "required": ["port"],
                                    "properties": {
                                        "port": {
                                            "x-kubernetes-int-or-string": True,
                                            "anyOf": [{"type": "integer"}, {"type": "string"}],
                                        },
                                        "builder": {"type": "string"},
                                        "refreshInterval": {
                                            "type": "integer",
                                            "format": "duration",
                                        },
                                        "settings": {
                                            "type": "object",
                                            "x-kubernetes-preserve-unknown-fields": True,
                                            "properties": {"known": {"type": "string"}},
                                        },
                                        "template": {
                                            "type": "object",
                                            "x-kubernetes-embedded-resource": True,
                                            "x-kubernetes-preserve-unknown-fields": True,
                                        },
                                        "options": {
                                            "type": "object",
                                            "additionalProperties": {"type": "string"},
                                        },
                                        "children": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {"value": {"type": "string"}},
                                            },
                                        },
                                        "nullable": {"type": "string", "nullable": True},
                                    },
                                },
                                "status": {
                                    "type": "object",
                                    "properties": {"ready": {"type": "boolean"}},
                                },
                            },
                        }
                    },
                }
            ],
        },
    }


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("generated")
    source = root / "input.data"
    source.write_text(json.dumps(crd()))
    config = ModelConfig(namespace="inferred_models", input_=str(source), output=root)
    before = config.model_dump()
    generate(config)
    assert config.model_dump() == before
    sys.path.insert(0, str(root))
    module = importlib.import_module("inferred_models.v1")
    yield module, config, root
    sys.path.remove(str(root))
    for name in list(sys.modules):
        if name == "inferred_models" or name.startswith("inferred_models."):
            del sys.modules[name]


def test_generated_crd_works_without_hints(generated):
    module, _, _ = generated
    data = {
        "metadata": {"name": "sample", "labels": {"app": "test"}},
        "spec": {
            "port": "http",
            "builder": "build-image",
            "refreshInterval": 10,
            "settings": {"known": "yes", "custom": {"arbitrary": [1, "two"]}},
            "template": {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": "nested"},
                "spec": {"containers": []},
            },
            "options": {"key": "value"},
            "nullable": None,
        },
    }
    widget = module.Widget.model_validate(data)
    assert widget.name == "sample"
    assert widget.gvk().api_version == "widgets.example.com/v1"
    assert widget.spec.builder_ == "build-image"
    wire = widget.model_dump(by_alias=True, exclude_unset=True)
    assert wire["spec"] == data["spec"]
    assert module.Widget(spec={"port": 8080}).spec.port == 8080
    with pytest.raises(ValidationError):
        module.Widget(spec={"port": []})


def test_generated_builder_keeps_fluent_and_context_ergonomics(generated):
    module, _, _ = generated
    widget = (
        module.Widget.builder()
        .metadata(lambda m: m.name("sample"))
        .spec(lambda s: s.port(80).builder_("image"))
        .build()
    )
    assert widget.spec.port == 80
    assert widget.name == "sample"
    with module.Widget.new() as builder:
        with builder.spec() as spec:
            spec.port("http")
            spec.children(lambda children: children.add(lambda child: child.value("first")))
        builder.status(None)  # Explicit None must not open a context.
    assert builder.build().spec.children[0].value == "first"
    assert builder.build().status is None


def test_repeat_generation_is_identical_and_importable(generated):
    _, config, root = generated
    package = root / "inferred_models"
    before = {p.relative_to(package): p.read_bytes() for p in package.rglob("*.py")}
    generate(config)
    after = {p.relative_to(package): p.read_bytes() for p in package.rglob("*.py")}
    assert before == after
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from inferred_models.v1 import Widget; assert Widget(spec={'port': 80}).spec.port == 80",
        ],
        cwd=root,
        check=True,
    )


def test_crd_conversion_does_not_mutate_source():
    source = crd()
    before = copy.deepcopy(source)
    assert convert_crd_to_schema(source) == convert_crd_to_schema(source)
    assert source == before


@pytest.mark.parametrize("wrapper", [lambda doc: doc, lambda doc: {"kind": "List", "items": [doc]}])
@pytest.mark.parametrize("serialize", [json.dumps, yaml.safe_dump])
def test_format_is_detected_from_content(tmp_path, wrapper, serialize):
    source = tmp_path / "download?raw=true"
    source.write_text(serialize(wrapper(crd())))
    output, _ = process_input(ModelConfig(namespace="models", input_=str(source)), tmp_path)
    assert "models.v1.Widget" in get_schema_definitions(json.loads(output.read_text()))


def test_schema_updates_accept_non_string_values():
    schema = {"definitions": {"Widget": {}}}
    for value in (True, 12, None, ["one"], {"key": "value"}):
        process_updates([Update(match=".*", jsonpath="default", value=value)], schema)
        assert schema["definitions"]["Widget"]["default"] == value


def test_renames_cannot_silently_overwrite():
    schema = {"definitions": {"A": {"type": "string"}, "B": {"type": "integer"}}}
    with pytest.raises(SchemaError, match="both map"):
        process_transformations(
            [Transformation(match=".*", replace="Same", namespace="models")], schema
        )
    assert list(schema["definitions"]) == ["A", "B"]


def test_mixed_schema_dialects_merge_refs():
    merged = merge_schemas(
        [
            {"definitions": {"A": {"type": "string"}}},
            {"$defs": {"B": {"$ref": "#/$defs/A"}}},
        ]
    )
    # Referenced definitions can originate in another input document.
    assert get_schema_definitions(merged)["B"]["$ref"] == "#/components/schemas/A"


def test_merge_conflicts_are_reported():
    with pytest.raises(SchemaError, match="Conflicting definitions"):
        merge_schemas(
            [
                {"definitions": {"A": {"type": "string"}}},
                {"definitions": {"A": {"type": "integer"}}},
            ]
        )


def test_annotations_inside_arrays_are_normalized_without_touching_defaults():
    schema = {
        "type": "array",
        "items": {"anyOf": [{"type": "string", "format": "int-or-string"}]},
        "default": [{"format": "int-or-string"}],
    }
    normalize_definition(schema)
    assert schema["items"]["anyOf"][0]["type"] == ["integer", "string"]
    assert schema["default"] == [{"format": "int-or-string"}]


def test_yaml_loader_does_not_change_application_loader():
    assert "=" in yaml.SafeLoader.yaml_implicit_resolvers
