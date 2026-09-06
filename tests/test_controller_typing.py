"""Check inference and mutation return types at the public controller interface."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_controller_api_typing(tmp_path, checker):
    script = tmp_path / "controller_usage.py"
    script.write_text("""from typing import assert_type
from cloudcoil.controller import Controller, ControllerStatus, HealthServer, LeaderElection, Manager, Request, ResourceKey, Result, mutate, ensure_finalizer
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Secret
from cloudcoil import patches
from cloudcoil.client import AsyncAPIClient

async def reconcile(request: Request[ConfigMap]) -> ConfigMap | Result | None:
    assert_type(request.resource, ConfigMap | None)
    assert_type(await request.client(Secret), AsyncAPIClient[Secret])
    assert_type(await request.ensure(Secret()), Secret)
    assert_type(request.name, str)
    if request.resource is None:
        return None
    def change(current: ConfigMap) -> None:
        current.data = {"key": "value"}
    assert_type(await mutate(request.resource, change), ConfigMap)
    assert_type(await ensure_finalizer(request.resource, "example.com/cleanup"), ConfigMap)
    desired = request.resource.model_copy(deep=True)
    assert_type(await request.resource.async_patch(patches.diff(request.resource, desired)), ConfigMap)
    return Result(resource=request.resource, requeue_after=60)

async def return_resource(request: Request[ConfigMap]) -> ConfigMap | None:
    return request.resource

assert_type(Controller(ConfigMap, return_resource), Controller[ConfigMap])
controller = Controller(ConfigMap, reconcile, workers=4).owns(Secret)
assert_type(controller, Controller[ConfigMap])
controller.watch(Secret, mapper=lambda secret: [ResourceKey("settings", secret.namespace)])
manager = Manager(controller, health=HealthServer(port=0), leader_election=LeaderElection("example"))
assert_type(controller.status, ControllerStatus)
assert_type(manager.metrics(), str)
assert_type(manager.healthy, bool)
assert_type(manager.informer_count, int)
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
