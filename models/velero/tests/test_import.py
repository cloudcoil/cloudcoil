from types import ModuleType

import cloudcoil.models.velero as velero


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), velero.__dict__.values()))
    assert modules, "No modules found in velero"


def test_backup_round_trip():
    from cloudcoil.models.velero.v1 import Backup
    from cloudcoil.models.velero.v2alpha1 import DataDownload, DataUpload

    resource = Backup.model_validate(
        {"metadata": {"name": "example"}, "spec": {"includedNamespaces": ["default"]}}
    )
    payload = resource.model_dump(by_alias=True, exclude_none=True)
    assert payload["apiVersion"] == "velero.io/v1"
    assert payload["kind"] == "Backup"
    assert payload["spec"]["includedNamespaces"] == ["default"]
    assert Backup.model_validate(payload) == resource
    assert DataDownload.model_fields["api_version"].default == "velero.io/v2alpha1"
    assert DataUpload.model_fields["api_version"].default == "velero.io/v2alpha1"
