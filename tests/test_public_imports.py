"""Import order must not depend on pytest's plugin preloading Config."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "first",
    [
        "cloudcoil",
        "cloudcoil.application",
        "cloudcoil.controller",
        "cloudcoil.caching",
        "cloudcoil.crd",
        "cloudcoil.admission",
        "cloudcoil.resources",
        "cloudcoil.client",
    ],
)
def test_fresh_public_import_order(first):
    code = f"""import {first}
from cloudcoil.application import Application
from cloudcoil.application._application import Application as DirectApplication
from cloudcoil.models.kubernetes.core.v1 import Pod
assert Application is DirectApplication
assert Pod.gvk().kind == "Pod"
from cloudcoil.client import Config, APIClient, AsyncAPIClient
from cloudcoil.client._config import Config as DirectConfig
from cloudcoil.caching import Cache, AsyncInformer
from cloudcoil.controller import Controller, Manager
from cloudcoil.crd import CRD
from cloudcoil.admission import AdmissionWebhook
assert Config is DirectConfig
import cloudcoil.client
assert cloudcoil.client.Config is Config
try:
    cloudcoil.client.missing_name
except AttributeError:
    pass
else:
    raise AssertionError("Unknown attributes must raise AttributeError")
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
