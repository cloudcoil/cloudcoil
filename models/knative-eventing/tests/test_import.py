from cloudcoil.resources import Resource

from cloudcoil.models.knative_eventing import get_model


def test_resource_lookup_and_roundtrip():
    model = get_model("Broker", api_version="eventing.knative.dev/v1")
    assert issubclass(model, Resource)
    resource = model.model_validate({"metadata": {"name": "example"}, "spec": {}})
    payload = resource.model_dump(by_alias=True, exclude_none=True)
    assert payload["kind"] == "Broker"
    assert payload["apiVersion"] == "eventing.knative.dev/v1"
    assert model.model_validate(payload) == resource
    assert (
        model.builder().metadata(lambda meta: meta.name("built")).spec(resource.spec).build().name
        == "built"
    )
