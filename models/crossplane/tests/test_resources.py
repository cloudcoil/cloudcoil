import pytest
from cloudcoil.models.crossplane import get_model

from cloudcoil.resources import Resource


@pytest.mark.parametrize(
    "kind,api_version,spec",
    [
        (
            "Provider",
            "pkg.crossplane.io/v1",
            {"package": "xpkg.upbound.io/crossplane-contrib/provider-aws:v0.54.2"},
        ),
        (
            "Composition",
            "apiextensions.crossplane.io/v1",
            {
                "compositeTypeRef": {"apiVersion": "example.org/v1", "kind": "Database"},
                "mode": "Pipeline",
                "pipeline": [{"step": "compose", "functionRef": {"name": "function-auto-ready"}}],
            },
        ),
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


def test_runtime_config_defaults_are_typed_and_independent():
    provider = get_model("Provider", api_version="pkg.crossplane.io/v1")
    first = provider.model_validate({"spec": {"package": "example.com/provider:v1"}})
    second = provider.model_validate({"spec": {"package": "example.com/provider:v1"}})
    assert first.spec.runtime_config_ref.name == "default"
    first.spec.runtime_config_ref.name = "custom"
    assert second.spec.runtime_config_ref.name == "default"
