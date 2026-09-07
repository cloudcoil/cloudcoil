from types import ModuleType

import cloudcoil.models.sealed_secrets as sealed_secrets


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), sealed_secrets.__dict__.values()))
    assert modules, "No modules found in sealed_secrets"


def test_sealed_secret_round_trip():
    from cloudcoil.models.sealed_secrets.v1alpha1 import SealedSecret

    resource = SealedSecret.model_validate(
        {"metadata": {"name": "example"}, "spec": {"encryptedData": {"token": "encrypted"}}}
    )
    payload = resource.model_dump(by_alias=True, exclude_none=True)
    assert payload["apiVersion"] == "bitnami.com/v1alpha1"
    assert payload["kind"] == "SealedSecret"
    assert payload["spec"]["encryptedData"] == {"token": "encrypted"}
    assert SealedSecret.model_validate(payload) == resource
