from types import ModuleType

import cloudcoil.models.kyverno as kyverno


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), kyverno.__dict__.values()))
    assert modules, "No modules found in kyverno"


def test_resource_identity():
    from cloudcoil.models.kyverno.v1 import ClusterPolicy

    assert ClusterPolicy.gvk().api_version == "kyverno.io/v1"
    assert ClusterPolicy.gvk().kind == "ClusterPolicy"


def test_go_duration_round_trip():
    from cloudcoil.models.kyverno.v2alpha1 import GlobalContextEntrySpecApiCall

    call = GlobalContextEntrySpecApiCall(refresh_interval="10m")
    assert call.model_dump(by_alias=True)["refreshInterval"] == "10m"
