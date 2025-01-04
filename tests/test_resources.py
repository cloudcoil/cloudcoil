import pytest
import yaml
from pydantic import ValidationError

from cloudcoil.apimachinery import ListMeta, ObjectMeta
from cloudcoil.resources import GVK, Resource, ResourceList, _Scheme, get_model, parse, parse_file


def test_gvk():
    gvk = GVK(apiVersion="apps/v1", kind="Deployment")
    assert gvk.group == "apps"
    assert gvk.version == "v1"
    assert gvk.api_version == "apps/v1"
    assert gvk.kind == "Deployment"

    with pytest.raises(ValueError):
        GVK(apiVersion=None, kind="Deployment")

    with pytest.raises(ValueError):
        GVK(apiVersion=None, kind="Deployment")


def test_base_resource():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    assert TestResource.gvk() == GVK(apiVersion="test/v1", kind="Test")

    class InvalidResource(Resource):
        pass

    with pytest.raises(ValueError):
        InvalidResource.gvk()


def test_resource_metadata():
    r = Resource(apiVersion="v1", kind="Pod")
    assert r.name is None
    assert r.namespace is None

    r.name = "test"
    assert r.name == "test"
    assert r.metadata.name == "test"

    r.namespace = "default"
    assert r.namespace == "default"
    assert r.metadata.namespace == "default"

    r = Resource(apiVersion="v1", kind="Pod", metadata=ObjectMeta(name="test", namespace="default"))
    assert r.name == "test"
    assert r.namespace == "default"


def test_resource_list():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    items = [TestResource(metadata=ObjectMeta(name=f"test-{i}")) for i in range(3)]

    resource_list = ResourceList[TestResource](
        apiVersion="test/v1",
        kind="TestList",
        metadata=ListMeta(continue_="token", remaining_item_count=2),
        items=items,
    )

    assert resource_list.resource_class == TestResource
    assert resource_list.has_next_page()
    assert len(resource_list.items) == 3
    assert len(resource_list) == 5  # includes remaining items

    # Test validation
    with pytest.raises(ValidationError):
        ResourceList[TestResource](apiVersion="wrong/v1", kind="TestList", items=[])


def test_scheme():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    _Scheme._register(TestResource)

    assert _Scheme.get("Test", "test/v1") == TestResource
    assert get_model("Test", api_version="test/v1") == TestResource

    with pytest.raises(KeyError):
        _Scheme.get("NonExistent")


def test_parse():
    yaml_data = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "test-pod"}}

    resource = parse(yaml_data)
    assert isinstance(resource, Resource)
    assert resource.api_version == "v1"
    assert resource.kind == "Pod"
    assert resource.name == "test-pod"

    # Test list parsing
    resources = parse([yaml_data, yaml_data])
    assert len(resources) == 2
    assert all(isinstance(r, Resource) for r in resources)

    # Test invalid data
    with pytest.raises(ValueError):
        parse({"metadata": {"name": "test"}})


def test_parse_file(tmp_path):
    yaml_content = """
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
---
apiVersion: v1
kind: Service
metadata:
  name: test-service
"""
    test_file = tmp_path / "test.yaml"
    test_file.write_text(yaml_content)

    resources = parse_file(test_file, load_all=True)
    assert isinstance(resources, list)
    assert len(resources) == 2
    assert resources[0].kind == "Pod"
    assert resources[1].kind == "Service"


@pytest.mark.asyncio
async def test_resource_list_iteration():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    items = [TestResource(metadata=ObjectMeta(name=f"test-{i}")) for i in range(2)]

    resource_list = ResourceList[TestResource](
        apiVersion="test/v1",
        kind="TestList",
        metadata=ListMeta(continue_="token", remaining_item_count=0),
        items=items,
    )

    # Test sync iteration
    count = 0
    for item in resource_list:
        assert isinstance(item, TestResource)
        count += 1
    assert count == 2

    # Test async iteration
    count = 0
    async for item in resource_list:
        assert isinstance(item, TestResource)
        count += 1
    assert count == 2


def test_resource_edge_cases():
    with pytest.raises(ValidationError, match="apiVersion"):
        GVK(apiVersion=None, kind="Test")

    with pytest.raises(ValueError, match="Field required"):
        parse({"metadata": {"name": "test"}})

    with pytest.raises(KeyError):
        parse({"apiVersion": "invalid/v1", "kind": "NonExistent"})


def test_resource_metadata_manipulation():
    r = Resource(apiVersion="v1", kind="Pod")

    # Test namespace operations
    r.namespace = "test-ns"
    assert r.metadata.namespace == "test-ns"
    assert r.namespace == "test-ns"

    # Test name operations with existing metadata
    r.name = "test-name"
    assert r.metadata.name == "test-name"
    assert r.name == "test-name"

    # Test metadata overwrite
    r.metadata = ObjectMeta(name="new-name", namespace="new-ns")
    assert r.name == "new-name"
    assert r.namespace == "new-ns"


def test_parse_multiple_resources():
    yaml_docs = """
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
---
apiVersion: v1
kind: Service
metadata:
  name: test-service
"""
    resources = parse(list(yaml.safe_load_all(yaml_docs)))
    assert len(resources) == 2
    assert resources[0].kind == "Pod"
    assert resources[1].kind == "Service"


def test_resource_list_validation():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    # Test invalid apiVersion
    with pytest.raises(ValueError, match="api_version must be test/v1"):
        ResourceList[TestResource](apiVersion="wrong/v1", kind="TestList", items=[])

    # Test invalid kind
    with pytest.raises(ValueError, match="kind must be TestList"):
        ResourceList[TestResource](apiVersion="test/v1", kind="WrongList", items=[])


def test_gvk_edge_cases():
    # Test complex group/version combinations
    gvk = GVK(apiVersion="custom.example.com/v1alpha1", kind="Test")
    assert gvk.group == "custom.example.com"
    assert gvk.version == "v1alpha1"


async def test_resource_list_iteration_empty():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"

    resource_list = ResourceList[TestResource](apiVersion="test/v1", kind="TestList", items=[])

    # Test empty list iteration
    items = [item async for item in resource_list]
    assert len(items) == 0

    items = [item for item in resource_list]
    assert len(items) == 0


def test_parse_file_variants(tmp_path):
    # Test single document
    single_doc = tmp_path / "single.yaml"
    single_doc.write_text("""
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
""")

    # Test parsing single document
    resource = parse_file(single_doc)
    assert isinstance(resource, Resource)
    assert resource.kind == "Pod"

    # Test multiple documents
    multi_doc = tmp_path / "multi.yaml"
    multi_doc.write_text("""
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-1
---
apiVersion: v1
kind: Pod
metadata:
  name: test-pod-2
""")

    # Test parsing multiple documents
    resources = parse_file(multi_doc, load_all=True)
    assert isinstance(resources, list)
    assert len(resources) == 2
    assert all(r.kind == "Pod" for r in resources)
    assert resources[0].name == "test-pod-1"
    assert resources[1].name == "test-pod-2"


def test_scheme_registration():
    class CustomResource(Resource):
        api_version: str = "custom.example.com/v1"
        kind: str = "Custom"

    # Register custom resource
    _Scheme._register(CustomResource)

    # Test retrieval
    assert get_model("Custom", api_version="custom.example.com/v1") == CustomResource

    # Test empty api_version
    assert get_model("Custom") == CustomResource

    # Test re-registration
    _Scheme._register(CustomResource)  # Should not raise


def test_resource_validation():
    class TestResource(Resource):
        api_version: str = "test/v1"
        kind: str = "Test"
        spec: dict = {}

    # Test valid resource
    resource = TestResource(spec={"key": "value"})
    assert resource.spec == {"key": "value"}

    # Test invalid resource
    with pytest.raises(ValidationError):
        TestResource(spec="invalid")
