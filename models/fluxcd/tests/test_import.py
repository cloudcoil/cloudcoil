from types import ModuleType

import cloudcoil.models.fluxcd as fluxcd


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), fluxcd.__dict__.values()))
    assert modules, "No modules found in fluxcd"


def test_resource_identity():
    from cloudcoil.models.fluxcd.source.v1 import GitRepository

    assert GitRepository.gvk().api_version == "source.toolkit.fluxcd.io/v1"
    assert GitRepository.gvk().kind == "GitRepository"
