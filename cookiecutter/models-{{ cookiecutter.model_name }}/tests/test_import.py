import pytest
import cloudcoil.models.{{cookiecutter.model_name}} as {{cookiecutter.model_name}}
from types import ModuleType


def test_has_modules():
    modules = list(filter(lambda x: isinstance(x, ModuleType), {{cookiecutter.model_name}}.__dict__.values()))
    assert modules, "No modules found in {{cookiecutter.model_name}}"
