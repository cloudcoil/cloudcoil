import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from cloudcoil.client import Config
from cloudcoil.controller import (
    Cases,
    Controller,
    Request,
    ResourceKey,
    Stage,
    Stages,
    TerminalError,
    Wait,
    get_condition,
)
from tests.test_controller_status import Widget, widget


def request(obj=None):
    return Request(ResourceKey("a", "ns"), obj or widget())


async def test_stages_wait_then_recheck_all_work_and_repair_drift():
    calls = []
    ready = False

    async def config(req):
        calls.append("config")

    async def workload(req):
        calls.append("workload")
        req.set_status(ready_replicas=int(ready))
        if not ready:
            return Wait("RollingOut", "Waiting for replicas", requeue_after=5)

    async def service(req):
        calls.append("service")

    stages = Stages(
        Stage("ConfigurationReady", config),
        Stage("WorkloadReady", workload),
        Stage("ServiceReady", service),
    )
    req = request()
    result = await stages(req)
    assert calls == ["config", "workload"]
    assert result.requeue_after == 5
    assert get_condition(req.object, "WorkloadReady").status == "False"
    assert get_condition(req.object, "ServiceReady").status == "Unknown"
    ready = True
    calls.clear()
    next_req = request(req.object.model_copy(deep=True))
    await stages(next_req)
    assert calls == ["config", "workload", "service"]
    assert get_condition(next_req.object, "Ready").status == "True"
    stable = next_req.object.model_copy(deep=True)
    await stages(request(next_req.object))
    assert next_req.object == stable
    ready = False  # Drift despite a previously completed condition.
    await stages(request(next_req.object))
    assert get_condition(next_req.object, "Ready").status == "False"
    assert get_condition(next_req.object, "ServiceReady").status == "Unknown"


async def test_cases_lazy_first_match_priority_and_fallback():
    cases = Cases[Widget]()
    calls = []

    @cases.case("Low", when=lambda req: calls.append("low predicate") or True, priority=1)
    async def low(req):
        calls.append("low")

    @cases.case("High", when=lambda req: True, priority=20)
    async def high(req):
        calls.append("high")
        return Wait("WaitingForInput")

    @cases.otherwise("Fallback")
    async def fallback(req):
        calls.append("fallback")

    req = request()
    result = await cases(req)
    assert calls == ["high"]
    assert result.requeue_after == 30
    assert get_condition(req.object, "Low").reason == "NotSelected"
    with pytest.raises(RuntimeError, match="before running"):
        cases.case("Late", when=lambda req: True)(low)

    other = Cases[Widget]()
    other.case("Miss", when=lambda req: False)(low)
    other.otherwise("Fallback")(fallback)
    await other(request())
    assert calls == ["high", "fallback"]


async def test_cases_registration_order_and_reject_ambiguous_configuration():
    calls = []

    async def first(req):
        calls.append("first")

    async def second(req):
        calls.append("second")

    cases = Cases[Widget]()
    cases.case("First", when=lambda req: True)(first)
    cases.case("Second", when=lambda req: True)(second)
    await cases(request())
    assert calls == ["first"]
    tied = Cases[Widget]()
    tied.case("One", when=lambda req: True, priority=1)(first)
    with pytest.raises(ValueError, match="priorities must be unique"):
        tied.case("Two", when=lambda req: True, priority=1)(second)
    tied.case("Three", when=lambda req: True)(second)
    with pytest.raises(ValueError, match="every case"):
        tied._freeze(Widget)
    with pytest.raises(ValueError, match="names must be unique"):
        Stages(Stage("Duplicate", first), Stage("Duplicate", second))
    with pytest.raises(ValueError, match="reserved"):
        Stage("Ready", first)


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_wait_rejects_busy_loops_and_invalid_delays(invalid):
    with pytest.raises(ValueError):
        Wait("Waiting", requeue_after=invalid)


async def test_invalid_predicate_and_stage_returns_fail_obviously():
    async def noop(req):
        return None

    async def predicate(req):
        return True

    cases = Cases[Widget]()
    cases.case("Bad", when=predicate)(noop)
    with pytest.raises(TypeError, match="return bool"):
        await cases(request())

    async def bad(req):
        return req.object

    with pytest.raises(TypeError, match="stage must return"):
        await Stages(Stage("Bad", bad))(request())


async def test_primary_status_filter_preserves_spec_metadata_deletion_and_resync():
    async def noop(req):
        return None

    controller = Controller(Widget, Stages(Stage("Configured", noop)), events=False)
    old = widget()
    old.metadata.resource_version = "1"
    status_only = old.model_copy(deep=True)
    status_only.metadata.resource_version = "2"
    from cloudcoil.controller import update_status

    update_status(status_only, endpoint="changed")
    await controller._update_primary(old, status_only)
    assert controller._queue.depth == 0
    await controller._update_primary(status_only, status_only.model_copy(deep=True))
    assert controller._queue.depth == 1  # periodic resync is not filtered
    key = await controller._queue.get()
    controller._queue.done(key)
    changed = status_only.model_copy(deep=True)
    changed.metadata.annotations = {"input": "changed"}
    changed.metadata.resource_version = "3"
    await controller._update_primary(status_only, changed)
    assert controller._queue.depth == 1
    key = await controller._queue.get()
    controller._queue.done(key)
    changed.metadata.deletion_timestamp = "2026-01-01T00:00:00Z"
    await controller._update_primary(status_only, changed)
    assert controller._queue.depth == 1


@pytest.mark.parametrize("failure", ["transient", "terminal", "timeout", "conflict"])
async def test_worker_persists_failure_status_only_and_respects_backoff(failure):
    obj = widget()
    obj.metadata.resource_version = "1"
    config = Config(server="https://cluster", namespace="ns")
    config._rest_mapping[Widget.gvk()] = {
        "resource": "widgets",
        "namespaced": True,
        "subresources": ["status"],
    }
    calls = 0
    patches = []
    completed = asyncio.Event()

    async def step(req):
        nonlocal calls
        calls += 1
        req.object.metadata.annotations = {"must-not-save": "partial"}
        req.set_status(endpoint="intentional status")
        if failure == "timeout":
            await asyncio.Future()
        if failure in ("terminal", "conflict"):
            raise TerminalError("invalid spec")
        raise RuntimeError("secret must stay out of Kubernetes status")

    controller = Controller(
        Widget,
        Stages(Stage("Provisioned", step)),
        config=config,
        events=False,
        reconcile_timeout=0.01 if failure == "timeout" else None,
    )
    controller._primary = SimpleNamespace(get=lambda *args: obj.model_copy(deep=True))

    async def handle(req):
        nonlocal obj
        assert req.method == "PATCH"
        assert req.url.path.endswith("/status")
        operations = json.loads(req.content)
        patches.append(operations)
        assert operations[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": "u"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "1"},
        ]
        assert all(op["path"].startswith("/status") for op in operations[2:])
        if failure == "conflict":
            return httpx.Response(409, json={"message": "stale version"})
        status = next(op["value"] for op in operations if op["path"] == "/status")
        previous = obj.model_copy(deep=True)
        obj.status = status
        obj.metadata.resource_version = "2"
        # Deliver the watch echo before PATCH returns, as can happen on a real server.
        await controller._update_primary(previous, obj)
        return httpx.Response(200, json=obj.model_dump(mode="json", by_alias=True))

    config.async_client._mounts.clear()
    config.async_client._transport = httpx.MockTransport(handle)
    original_observe = controller._metrics.observe

    def observe(*args):
        original_observe(*args)
        completed.set()

    controller._metrics.observe = observe
    try:
        async with config:
            controller.enqueue(ResourceKey("a", "ns"))
            worker = asyncio.create_task(controller._worker())
            try:
                await asyncio.wait_for(completed.wait(), 2)
                assert calls == 1
                assert len(patches) == 1
                assert controller._queue.depth == 0
                assert controller._queue.delayed == (0 if failure == "terminal" else 1)
                if failure != "conflict":
                    assert obj.status.endpoint == "intentional status"
                    ready = get_condition(obj, "Ready")
                    assert ready.status == "False"
                    assert "secret" not in ready.message
                    assert get_condition(obj, "Provisioned").status == "False"
                assert not obj.metadata.annotations
            finally:
                controller._queue.shutdown(immediate=True)
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
    finally:
        config.client.close()
        await config.async_client.aclose()
