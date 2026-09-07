"""A handwritten Resource preserves its type throughout the client API."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_custom_resource_api_typing(tmp_path, checker):
    script = tmp_path / "custom_resource_usage.py"
    script.write_text("""from typing import Literal, Self, assert_type
from pydantic import Field
from cloudcoil.apimachinery import Status
from cloudcoil.client import APIClient, AsyncAPIClient, Config
from cloudcoil.crd import custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource, ResourceList, Unstructured

class Spec(BaseModel):
    message: str

@custom_resource(plural="widgets")
class Widget(Resource):
    api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
    kind: Literal["Widget"] = "Widget"
    spec: Spec
    status: dict[str, str] | None = None

    @classmethod
    async def lookup(cls, config: Config) -> Self:
        return await (await cls.async_client(config)).get("example")

async def use(config: Config, widget: Widget) -> None:
    assert_type(Widget.client(config), APIClient[Widget])
    assert_type(await Widget.async_client(config, namespace="team", cached=False), AsyncAPIClient[Widget])
    assert_type(Widget.get("example"), Widget)
    assert_type(await Widget.async_get("example"), Widget)
    assert_type(Widget.list(), ResourceList[Widget])
    assert_type(await Widget.async_list(), ResourceList[Widget])
    assert_type(widget.create(), Widget)
    assert_type(await widget.async_create(), Widget)
    assert_type(widget.update(), Widget)
    assert_type(await widget.async_update(), Widget)
    assert_type(widget.update_status(), Widget)
    assert_type(await widget.async_update_status(), Widget)
    assert_type(widget.patch([]), Widget)
    assert_type(await widget.async_patch([]), Widget)
    assert_type(widget.save(), Widget)
    assert_type(await widget.async_save(), Widget)
    assert_type(widget.remove(), Widget | Status)
    assert_type(await widget.async_remove(), Widget | Status)
    assert_type(widget.scale(2), Widget)
    assert_type(await widget.async_scale(2), Widget)
    for event, item in Widget.watch():
        assert_type(item, Widget | Unstructured)
    async for event, item in Widget.async_watch():
        assert_type(item, Widget | Unstructured)
    assert_type(Widget.builder().build(), Widget)
    with Widget.new() as builder:
        assert_type(builder.build(), Widget)
    assert_type(Widget.list_builder().add(widget).build(), list[Widget])
""")
    args = (
        ["--cache-dir", str(tmp_path / "mypy-cache")]
        if checker == "mypy"
        else ["--pythonversion", "3.14"]
    )
    result = subprocess.run(
        [checker, *args, str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
