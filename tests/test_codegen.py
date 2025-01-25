from pathlib import Path
from typing import Any

import pytest

from cloudcoil.codegen.generator import (
    ModelConfig,
    Transformation,
    delete_value_at_path,
    generate,
    process_definitions,
    set_value_at_path,
)

K8S_OPENAPI_URL = str(Path(__file__).parent / "data" / "k8s-swagger.json")


@pytest.fixture
def sample_schema():
    return {
        "definitions": {
            "io.k8s.api.apps.v1.Deployment": {
                "x-kubernetes-group-version-kind": [
                    {"group": "apps", "kind": "Deployment", "version": "v1"}
                ],
                "properties": {
                    "apiVersion": {"type": "string"},
                    "kind": {"type": "string"},
                    "metadata": {
                        "$ref": "#/definitions/io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta"
                    },
                },
            }
        }
    }


@pytest.fixture
def model_config(tmp_path):
    return ModelConfig(
        namespace="test.k8s",
        input_=K8S_OPENAPI_URL,
        transformations=[
            Transformation(
                match_=r"^io\.k8s\.apimachinery\..*\.(.+)",
                replace=r"apimachinery.\g<1>",
                namespace="cloudcoil",
            ),
            Transformation(match_=r"^io\.k8s\.api\.(core|apps.*)$", replace=r"\g<1>"),
            Transformation(match_=r"^,*$", exclude=True),
        ],
    )


def test_model_config_validation():
    config = ModelConfig(
        namespace="test",
        input_="test.json",
        transformations=[
            Transformation(match_="test", replace="replaced"),
        ],
    )
    assert config.namespace == "test"
    assert config.input_ == "test.json"
    assert len(config.transformations) == 2
    assert config.transformations[0].match_.pattern == "test"
    assert config.transformations[0].replace == "replaced"
    assert config.transformations[0].namespace == "test"
    assert config.transformations[1].match_.pattern == "^(.*)$"
    assert config.transformations[1].replace == r"\g<1>"
    assert config.transformations[1].namespace == "test"


def test_process_definitions(sample_schema):
    process_definitions(sample_schema)
    deployment = sample_schema["definitions"]["io.k8s.api.apps.v1.Deployment"]
    assert deployment["properties"]["apiVersion"]["enum"] == ["apps/v1"]
    assert deployment["properties"]["kind"]["enum"] == ["Deployment"]
    assert "metadata" not in deployment.get("required", [])


def test_generate_k8s_models(model_config, tmp_path):
    model_config.output = tmp_path
    generate(model_config)
    output_dir = tmp_path / "test" / "k8s"

    # Check if output directory exists and contains py.typed file
    assert output_dir.exists()
    assert (output_dir / "py.typed").exists()

    # Verify generated Python files
    python_files = list(output_dir.glob("**/*.py"))
    assert python_files, "No Python files were generated"

    # Check for specific model files and their content
    apps_v1_file = next((f for f in python_files if "apps/v1" in str(f)), None)
    assert apps_v1_file is not None, "apps/v1 models not found"

    # Verify file content
    content = apps_v1_file.read_text()
    assert "class Deployment(" in content, "Deployment model not found"
    assert "from cloudcoil.resources import Resource" in content, "Base class import missing"
    assert "from cloudcoil import apimachinery" in content, "Apimachinery import missing"

    # Verify imports are correct (no relative imports for apimachinery)
    assert "from .. import apimachinery" not in content
    assert "from ... import apimachinery" not in content


def test_int_or_string_conversion(sample_schema):
    sample_schema["definitions"]["TestType"] = {
        "properties": {"value": {"type": "string", "format": "int-or-string"}}
    }
    process_definitions(sample_schema)
    assert sample_schema["definitions"]["TestType"]["properties"]["value"]["type"] == [
        "integer",
        "string",
    ]
    assert "format" not in sample_schema["definitions"]["TestType"]["properties"]["value"]


def test_process_definitions_with_lists(sample_schema):
    sample_schema["definitions"]["io.k8s.api.apps.v1.DeploymentList"] = {
        "properties": {
            "apiVersion": {"type": "string"},
            "kind": {"type": "string"},
            "metadata": {"$ref": "#/definitions/io.k8s.apimachinery.pkg.apis.meta.v1.ListMeta"},
            "items": {
                "type": "array",
                "items": {"$ref": "#/definitions/io.k8s.api.apps.v1.Deployment"},
            },
        }
    }
    process_definitions(sample_schema)
    deployment_list = sample_schema["definitions"]["io.k8s.api.apps.v1.DeploymentList"]
    assert "metadata" not in deployment_list.get("required", [])
    assert "items" in deployment_list["properties"]


def test_generate_with_exclusions(tmp_path):
    config = ModelConfig(
        namespace="test.k8s",
        input_=K8S_OPENAPI_URL,
        output=tmp_path,
        transformations=[
            {"match": r"io\.k8s\.api\.apps\.v1\.DaemonSet.*", "exclude": True},
            {"match": r"io\.k8s\.api\.(.+)", "replace": r"\1"},
        ],
    )
    generate(config)

    output_dir = tmp_path / "test" / "k8s"
    assert output_dir.exists()

    # Check that DaemonSet is excluded
    for py_file in output_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "class DaemonSet(" not in content
        assert "class DaemonSetList(" not in content


def test_generate_init_files(tmp_path):
    config = ModelConfig(
        namespace="test.k8s",
        input_=K8S_OPENAPI_URL,
        output=tmp_path,
        transformations=[
            {"match": r"io\.k8s\.api\.(.+)", "replace": r"\1"},
        ],
        generate_init=True,
    )
    generate(config)

    output_dir = tmp_path / "test" / "k8s"
    assert (output_dir / "__init__.py").exists()

    # Check that __init__.py contains appropriate imports
    init_content = (output_dir / "__init__.py").read_text()
    assert "from . import" in init_content
    assert "# Generated by cloudcoil-model-codegen" in init_content


def test_generate_without_init_files(tmp_path):
    config = ModelConfig(
        namespace="test.k8s",
        input_=K8S_OPENAPI_URL,
        output=tmp_path,
        transformations=[
            {"match": r"io\.k8s\.api\.(.+)", "replace": r"\1"},
        ],
        generate_init=False,
    )
    generate(config)

    output_dir = tmp_path / "test" / "k8s"
    assert not (output_dir / "__init__.py").exists()


def test_model_config_validation_errors():
    with pytest.raises(ValueError, match="replace is required"):
        ModelConfig(
            namespace="test",
            input_="test.json",
            transformations=[{"match": "test"}],
        )


def test_model_config_with_additional_args(tmp_path):
    config = ModelConfig(
        namespace="test.k8s",
        input_=K8S_OPENAPI_URL,
        output=tmp_path,
        additional_datamodel_codegen_args=["--collapse-root-models"],
    )
    generate(config)

    output_dir = tmp_path / "test" / "k8s"
    assert output_dir.exists()

    # Verify generated files include field constraints
    for py_file in output_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        assert "RootModel" not in content


def test_generate_fluxcd_models(tmp_path, monkeypatch):
    # Process the config file
    generate(
        ModelConfig(
            namespace="cloudcoil.models.fluxcd",
            input_="https://github.com/fluxcd/flux2/releases/download/v2.4.0/install.yaml",
            crd_namespace="io.fluxcd.toolkit",
            output=tmp_path,
        )
    )

    # Verify generated files
    output_dir = tmp_path / "cloudcoil" / "models" / "fluxcd"
    assert output_dir.exists()

    # Check for some expected FluxCD CRD models
    expected_models = [
        "helmrelease",
        "kustomization",
        "gitrepository",
    ]

    python_files = list(output_dir.rglob("*.py"))
    file_contents = [f.read_text() for f in python_files]
    content = "\n".join(file_contents)

    for model in expected_models:
        assert f"class {model}(resource):" in content.lower(), f"Expected model {model} not found"

    # Verify imports and structure
    assert "from cloudcoil.resources import" in content
    assert "from cloudcoil.pydantic import" in content


def test_basic_dict_deletion():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, "foo.bar")
    assert obj == {"foo": {}}


def test_array_index_deletion():
    obj = [{"foo": 42}]
    delete_value_at_path(obj, "[0].foo")
    assert obj == [{}]


def test_mixed_array_dict_deletion():
    obj = {"foo": [{"bar": 42}]}
    delete_value_at_path(obj, "foo[0].bar")
    assert obj == {"foo": [{}]}


def test_delete_multiple_dots():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, "foo..bar")
    assert obj == {"foo": {}}


def test_delete_empty_path():
    obj = {"foo": 42}
    delete_value_at_path(obj, "")
    assert obj == {"foo": 42}


def test_none_path():
    obj = {"foo": 42}
    delete_value_at_path(obj, None)  # type: ignore
    assert obj == {"foo": 42}


def test_nonexistent_path():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, "foo.baz")
    assert obj == {"foo": {"bar": 42}}


def test_invalid_array_index():
    obj = [{"foo": 42}]
    delete_value_at_path(obj, "[1].foo")  # Index out of range
    assert obj == [{"foo": 42}]


def test_array_index_on_dict():
    obj = {"foo": 42}
    delete_value_at_path(obj, "[0].foo")  # Can't use array index on dict
    assert obj == {"foo": 42}


def test_dict_key_on_array():
    obj = [42]
    delete_value_at_path(obj, "foo[0]")  # Can't use dict key on array
    assert obj == [42]


def test_nested_array_deletion():
    obj = {"foo": [{"bar": [{"baz": 42}]}]}
    delete_value_at_path(obj, "foo[0].bar[0].baz")
    assert obj == {"foo": [{"bar": [{}]}]}


def test_root_array_deletion():
    obj = [{"foo": 42}, {"bar": 24}]
    delete_value_at_path(obj, "[0]")
    assert obj == [{"bar": 24}]


def test_multiple_empty_segments():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, "foo...bar")
    assert obj == {"foo": {}}


def test_path_with_spaces():
    obj = {"foo bar": {"baz": 42}}
    delete_value_at_path(obj, "foo bar.baz")
    assert obj == {"foo bar": {}}


@pytest.mark.parametrize(
    "obj,path,expected",
    [
        ({"a": 1}, "a", {}),
        ([1, 2, 3], "[1]", [1, 3]),
        ({"a": [1, 2]}, "a[1]", {"a": [1]}),
        ({"a": {"b": {"c": 1}}}, "a.b.c", {"a": {"b": {}}}),
        ([{"a": 1}, {"b": 2}], "[0].a", [{}, {"b": 2}]),
    ],
)
def test_delete_parametrized_cases(obj: Any, path: str, expected: Any):
    delete_value_at_path(obj, path)
    assert obj == expected


def test_delete_nested_empty_dict():
    obj = {"foo": {"bar": {}}}
    delete_value_at_path(obj, "foo.bar")
    assert obj == {"foo": {}}


def test_delete_nested_empty_list():
    obj = {"foo": {"bar": []}}
    delete_value_at_path(obj, "foo.bar")
    assert obj == {"foo": {}}


def test_delete_invalid_array_syntax():
    obj = {"foo": [42]}
    delete_value_at_path(obj, "foo[abc]")  # Invalid array index
    assert obj == {"foo": [42]}


def test_delete_trailing_dot():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, "foo.bar.")
    assert obj == {"foo": {}}


def test_delete_leading_dot():
    obj = {"foo": {"bar": 42}}
    delete_value_at_path(obj, ".foo.bar")
    assert obj == {"foo": {}}


def test_basic_dict_setting():
    obj = {}
    set_value_at_path(obj, "foo.bar", 42)
    assert obj == {"foo": {"bar": 42}}


def test_array_index_setting():
    obj = [{}]
    set_value_at_path(obj, "[0].foo", 42)
    assert obj == [{"foo": 42}]


def test_array_extension():
    obj = []
    set_value_at_path(obj, "[2].foo", 42)
    assert obj == [None, None, {"foo": 42}]


def test_mixed_array_dict_setting():
    obj = {"foo": []}
    set_value_at_path(obj, "foo[1].bar", 42)
    assert obj == {"foo": [None, {"bar": 42}]}


def test_multiple_dots():
    obj = {}
    set_value_at_path(obj, "foo..bar", 42)
    assert obj == {"foo": {"bar": 42}}


def test_empty_path():
    obj = {"foo": 42}
    set_value_at_path(obj, "", "value")
    assert obj == {"foo": 42}


def test_overwrite_existing_value():
    obj = {"foo": {"bar": 42}}
    set_value_at_path(obj, "foo.bar", "new_value")
    assert obj == {"foo": {"bar": "new_value"}}


def test_create_nested_structure():
    obj = {}
    set_value_at_path(obj, "a.b.c.d", 42)
    assert obj == {"a": {"b": {"c": {"d": 42}}}}


def test_array_index_without_dot():
    obj = {"a": [1, 2]}
    set_value_at_path(obj, "a[1]", 42)
    assert obj == {"a": [1, 42]}


def test_array_nested_in_array():
    obj = []
    set_value_at_path(obj, "[0][1]", 42)
    assert obj == [[None, 42]]


def test_create_array_in_dict():
    obj = {}
    set_value_at_path(obj, "foo[1]", 42)
    assert obj == {"foo": [None, 42]}


@pytest.mark.parametrize(
    "obj,path,value,expected",
    [
        ({}, "a", 1, {"a": 1}),
        ([], "[1]", 2, [None, 2]),
        ({}, "a[1]", 3, {"a": [None, 3]}),
        ({}, "a.b.c", 4, {"a": {"b": {"c": 4}}}),
        ([None], "[0].a", 5, [{"a": 5}]),
    ],
)
def test_parametrized_cases(obj: Any, path: str, value: Any, expected: Any):
    set_value_at_path(obj, path, value)
    assert obj == expected


def test_invalid_array_syntax():
    obj = {"foo": [42]}
    set_value_at_path(obj, "foo[abc]", "value")
    assert obj == {"foo": [42]}


def test_array_index_on_non_array():
    obj = {"foo": 42}
    set_value_at_path(obj, "foo[0]", "value")
    assert obj == {"foo": 42}


def test_dict_key_on_non_dict():
    obj = [42]
    set_value_at_path(obj, "[0].foo", "value")
    assert obj == [42]


def test_nested_array_creation():
    obj = {}
    set_value_at_path(obj, "foo[0][1][2]", 42)
    assert obj == {"foo": [[None, [None, None, 42]]]}


def test_trailing_dot():
    obj = {}
    set_value_at_path(obj, "foo.bar.", 42)
    assert obj == {"foo": {"bar": 42}}


def test_leading_dot():
    obj = {}
    set_value_at_path(obj, ".foo.bar", 42)
    assert obj == {"foo": {"bar": 42}}
