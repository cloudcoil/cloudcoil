from cloudcoil.resources import Resource

from cloudcoil.models.kpack import get_model


def test_resource_lookup_and_roundtrip():
    model = get_model("Image", api_version="kpack.io/v1alpha2")
    assert issubclass(model, Resource)
    resource = model.model_validate(
        {
            "metadata": {"name": "example"},
            "spec": {
                "tag": "example.com/app:latest",
                "builder": {"name": "builder", "kind": "ClusterBuilder"},
                "source": {"git": {"url": "https://example.com/repo", "revision": "main"}},
            },
        }
    )
    payload = resource.model_dump(by_alias=True, exclude_none=True)
    assert payload["kind"] == "Image"
    assert payload["apiVersion"] == "kpack.io/v1alpha2"
    assert model.model_validate(payload) == resource
    assert (
        model.builder().metadata(lambda meta: meta.name("built")).spec(resource.spec).build().name
        == "built"
    )


def test_lifecycle_api_schema():
    lifecycle = get_model("ClusterLifecycle", api_version="kpack.io/v1alpha2")
    resource = lifecycle.model_validate(
        {
            "metadata": {"name": "default-lifecycle"},
            "spec": {"image": "example.com/lifecycle:latest"},
            "status": {
                "apis": {
                    "buildpack": {"deprecated": [], "supported": ["0.10"]},
                    "platform": {"deprecated": [], "supported": ["0.12"]},
                }
            },
        }
    )
    assert resource.status.apis.buildpack.supported == ["0.10"]
    assert resource.status.apis.platform.supported == ["0.12"]
