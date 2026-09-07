import pytest
from cloudcoil.models.tekton import get_model

from cloudcoil.resources import Resource


@pytest.mark.parametrize(
    "kind,api_version,spec",
    [
        (
            "Task",
            "tekton.dev/v1",
            {"steps": [{"name": "hello", "image": "busybox", "script": "echo hello"}]},
        ),
        ("Pipeline", "tekton.dev/v1", {"tasks": [{"name": "hello", "taskRef": {"name": "hello"}}]}),
    ],
)
def test_resource_round_trip(kind, api_version, spec):
    model = get_model(kind, api_version=api_version)
    assert issubclass(model, Resource)
    resource = model.model_validate({"metadata": {"name": "example"}, "spec": spec})
    payload = resource.model_dump(by_alias=True, exclude_none=True)
    assert payload["apiVersion"] == api_version
    assert payload["kind"] == kind
    assert model.model_validate(payload) == resource
    built = model.builder().metadata(lambda meta: meta.name("built")).spec(resource.spec).build()
    assert built.name == "built"
