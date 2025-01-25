import pytest
import cloudcoil.models.{{cookiecutter.module_name}} as {{cookiecutter.module_name}}
from types import ModuleType


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), {{cookiecutter.module_name}}.__dict__.values()))
    assert modules, "No modules found in {{cookiecutter.module_name}}"
