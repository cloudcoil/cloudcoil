import pytest
from cloudcoil.models.argocd import get_model

from cloudcoil.resources import Resource


@pytest.mark.parametrize(
    "kind,api_version,spec",
    [
        (
            "Application",
            "argoproj.io/v1alpha1",
            {
                "project": "default",
                "source": {
                    "repoURL": "https://github.com/example/repo",
                    "path": "apps",
                    "targetRevision": "main",
                },
                "destination": {"server": "https://kubernetes.default.svc", "namespace": "default"},
            },
        ),
        ("AppProject", "argoproj.io/v1alpha1", {}),
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
