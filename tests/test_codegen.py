import re

import pytest

from cloudcoil.codegen.parser import ModelConfig, Substitution, generate, process_definitions

K8S_OPENAPI_URL = (
    "https://raw.githubusercontent.com/kubernetes/kubernetes/master/api/openapi-spec/swagger.json"
)


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
        name="k8s",
        input_=K8S_OPENAPI_URL,
        output=tmp_path,
        substitute=[
            Substitution(from_="io.k8s.api.(.+)", to="k8s.\\1"),
        ],
    )


def test_substitution():
    subs = Substitution(from_="io.k8s.api.(.+)", to="k8s.\\1")
    assert isinstance(subs.from_, re.Pattern)
    assert subs.to == "k8s.\\1"


def test_model_config_validation():
    config = ModelConfig(
        name="test",
        input_="test.json",
        substitute=[
            Substitution(from_="test", to="replaced"),
        ],
    )
    assert config.name == "test"
    assert config.input_ == "test.json"
    assert len(config.substitute) == 1
    assert config.substitute[0].to == "models.replaced"


def test_process_definitions(sample_schema):
    process_definitions(sample_schema)
    deployment = sample_schema["definitions"]["io.k8s.api.apps.v1.Deployment"]
    assert deployment["properties"]["apiVersion"]["enum"] == ["apps/v1"]
    assert deployment["properties"]["kind"]["enum"] == ["Deployment"]
    assert "metadata" not in deployment.get("required", [])


@pytest.mark.integration
def test_generate_k8s_models(model_config, tmp_path):
    generate(model_config)
    output_dir = tmp_path / "k8s"

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

    # Clean up to avoid interfering with other tests
    import shutil

    shutil.rmtree(output_dir)


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
