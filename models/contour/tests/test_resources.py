import pytest
from cloudcoil.models.contour import get_model

from cloudcoil.resources import Resource


@pytest.mark.parametrize(
    "kind,api_version,spec",
    [
        (
            "HTTPProxy",
            "projectcontour.io/v1",
            {
                "virtualhost": {"fqdn": "example.com"},
                "routes": [{"services": [{"name": "app", "port": 8080}]}],
            },
        )
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


@pytest.mark.parametrize("name", ["session_id", "__Host-session", "token.v2"])
def test_cookie_names_accept_http_tokens(name):
    proxy = get_model("HTTPProxy", api_version="projectcontour.io/v1")
    resource = proxy.model_validate(
        {
            "spec": {
                "routes": [
                    {
                        "services": [{"name": "app", "port": 80}],
                        "cookieRewritePolicies": [{"name": name}],
                    }
                ]
            }
        }
    )
    assert resource.spec.routes[0].cookie_rewrite_policies[0].name == name


@pytest.mark.parametrize("name", ["bad name", "bad;name", "bad[name", "bad\\name", "bad\tname", ""])
def test_cookie_names_reject_separators(name):
    from pydantic import ValidationError

    proxy = get_model("HTTPProxy", api_version="projectcontour.io/v1")
    with pytest.raises(ValidationError):
        proxy.model_validate(
            {
                "spec": {
                    "routes": [
                        {
                            "services": [{"name": "app", "port": 80}],
                            "cookieRewritePolicies": [{"name": name}],
                        }
                    ]
                }
            }
        )
