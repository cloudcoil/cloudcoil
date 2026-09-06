"""Public admission callbacks retain typed resource inputs and outputs."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_admission_api_typing(tmp_path, checker):
    script = tmp_path / "admission_usage.py"
    script.write_text("""from typing import assert_type
from cloudcoil.admission import AdmissionWebhook, AdmissionRequest, AdmissionDenied, UserInfo
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

app = AdmissionWebhook()

@app.mutating(ConfigMap, resource="configmaps", path="/mutate")
async def defaults(request: AdmissionRequest[ConfigMap]) -> ConfigMap | None:
    assert_type(request.resource, ConfigMap | None)
    assert_type(request.old_resource, ConfigMap | None)
    assert_type(request.user_info, UserInfo)
    assert_type(request.dry_run, bool)
    resource = request.resource
    if resource is not None:
        resource.data = {"default": "value"}
    return resource

@app.validating(ConfigMap, resource="configmaps", path="/validate")
async def validate(request: AdmissionRequest[ConfigMap]) -> None:
    if request.resource is not None and request.resource.data is None:
        raise AdmissionDenied("Data is required")
""")
    with script.open("a") as stream:
        stream.write("""
from typing import Annotated, Literal, Self
from pydantic import Field
from cloudcoil.admission import mutating, validating
from cloudcoil.client import AsyncAPIClient, Config
from cloudcoil.crd import CRD, PrinterColumn, custom_resource
from cloudcoil.resources import Resource

@custom_resource(plural="widgets")
class Widget(Resource):
    api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
    kind: Literal["Widget"] = "Widget"
    replicas: Annotated[int, PrinterColumn(name="Replicas")] = 1

    @classmethod
    @mutating()
    async def defaults(cls, request: AdmissionRequest[Self]) -> Self | None:
        assert_type(request.resource, Self | None)
        return request.resource

    @classmethod
    @validating(operations=("CREATE", "UPDATE", "DELETE"))
    async def check(cls, request: AdmissionRequest[Self], client: AsyncAPIClient[Self]) -> None:
        stored = await client.get("other", request.namespace)
        assert_type(stored, Self)
        assert_type(request.old_resource, Self | None)
        if request.config is not None:
            other = await request.config.async_client_for(ConfigMap, cached=False)
            assert_type(other, AsyncAPIClient[ConfigMap])

    @staticmethod
    @validating()
    async def external(request: AdmissionRequest["Widget"]) -> None:
        assert_type(request.resource, Widget | None)

config = Config()
assert_type(AdmissionWebhook(config=config).register(Widget), AdmissionWebhook)
assert_type(CRD(Widget), CRD)
assert_type(Widget(), Widget)
""")
    args = (
        ["--explicit-package-bases", "--cache-dir", str(tmp_path / "mypy-cache")]
        if checker == "mypy"
        else ["--pythonversion", "3.14"]
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [checker, *args, str(script)],
        cwd=root,
        env={**os.environ, "MYPYPATH": str(root), "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
