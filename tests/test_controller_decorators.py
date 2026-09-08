"""Execution contracts for decorated controllers and cases inside stages."""

from types import SimpleNamespace

import pytest

from cloudcoil.controller import Context, Controller, Request, ResourceKey, Wait, get_condition
from cloudcoil.errors import ResourceConflict
from tests.test_controller_status import Widget, widget


def request(obj=None):
    return Request(ResourceKey("a", "ns"), obj or widget())


async def test_nested_cases_wait_and_retry_all_stages_without_branch_conditions():
    controller = Controller(Widget)
    configuration = controller.stage("configuration", condition="ConfigurationReady")
    calls = []
    missing = True

    @configuration.case(when=lambda obj: missing)
    async def no_input(obj):
        calls.append("missing")
        raise Wait("InputMissing", after=7)

    @configuration.otherwise()
    async def configure(obj, ctx):
        calls.append("configure")
        ctx.set_status(endpoint="configured")

    @controller.stage(depends=configuration, condition="DeploymentApplied")
    async def deploy(obj):
        calls.append("deploy")

    req = request()
    result = await controller.reconcile(req)
    assert result.requeue_after == 7
    assert calls == ["missing"]
    assert get_condition(req.object, "ConfigurationReady").reason == "InputMissing"
    assert get_condition(req.object, "DeploymentApplied").status == "Unknown"
    assert {c.type for c in req.object.status.conditions} == {
        "ConfigurationReady",
        "DeploymentApplied",
        "Ready",
    }
    missing = False
    calls.clear()
    await controller.reconcile(request(req.object))
    assert calls == ["configure", "deploy"]
    assert get_condition(req.object, "ConfigurationReady").reason == "configure"
    calls.clear()
    await controller.reconcile(request(req.object))
    assert calls == ["configure", "deploy"]
    with pytest.raises(RuntimeError, match="before running"):
        configuration.otherwise()(configure)


async def test_reconcile_context_reports_wait_and_preserves_signature():
    controller = Controller(Widget)

    @controller.reconcile(every=60)
    async def reconcile(obj: Widget, ctx: Context[Widget]):
        ctx.set_status(endpoint="observed")
        ctx.event("Observed", "Read the input")
        raise Wait("Pending", after=5)

    req = request()
    result = await controller.reconcile(req)
    assert result.requeue_after == 5
    assert result.resource is None
    assert req._report.status.endpoint == "observed"
    assert get_condition(req.object, "Ready").status == "False"
    assert req._report.events[0][:2] == ("Observed", "Read the input")
    assert reconcile.__name__ == "reconcile"


async def test_periodic_returned_resource_and_absent_or_deleting_primary():
    controller = Controller(Widget)
    calls = []

    @controller.reconcile(every=60)
    async def reconcile(obj):
        calls.append(obj)
        return obj

    assert await controller.reconcile(Request(ResourceKey("a"), None)) is None
    obj = widget()
    obj.metadata.deletion_timestamp = "2026-09-08T00:00:00Z"
    assert await controller.reconcile(request(obj)) is None
    assert not calls
    req = request()
    result = await controller.reconcile(req)
    assert result.resource is req.object
    assert result.requeue_after == 60


async def test_root_cases_are_lazy_and_after_orders_predicates():
    controller = Controller(Widget)
    calls = []

    async def later(obj):
        calls.append("later")

    async def first(obj):
        calls.append("first")

    controller.case(when=lambda obj: calls.append("later predicate") or True, after=first)(later)
    controller.case(when=lambda obj: True)(first)
    controller.otherwise()(later)
    await controller.reconcile(request())
    assert calls == ["first"]


@pytest.mark.parametrize("mode", ["ambiguous", "cycle", "missing", "mixed", "fallback", "empty"])
def test_registration_rejects_ambiguous_or_incomplete_definitions(mode):
    controller = Controller(Widget)

    async def first(obj):
        pass

    async def second(obj):
        pass

    if mode == "ambiguous":
        controller.stage(condition="First")(first)
        controller.stage(condition="Second")(second)
    elif mode == "cycle":
        controller.stage(condition="First", depends=second)(first)
        controller.stage(condition="Second", depends=first)(second)
    elif mode == "missing":
        controller.stage(condition="First", depends=second)(first)
    elif mode == "mixed":
        controller.stage(condition="First")(first)
        controller.reconcile()(second)
    elif mode == "fallback":
        controller.case(when=lambda obj: True)(first)
    with pytest.raises(ValueError):
        controller._validate()


def test_sync_handlers_async_predicates_invalid_signatures_and_reserved_conditions():
    controller = Controller(Widget)
    with pytest.raises(TypeError, match="async"):
        controller.reconcile()(lambda obj: None)

    async def predicate(obj):
        return True

    with pytest.raises(TypeError, match="synchronous"):
        controller.case(when=predicate)

    async def invalid(obj, *, unexpected):
        pass

    with pytest.raises(TypeError, match="resource"):
        controller.reconcile()(invalid)
    with pytest.raises(ValueError, match="Ready"):
        controller.stage(condition="Ready")


@pytest.mark.parametrize("failure", ["wait", "error", "success", "delete", "absent", "replaced"])
async def test_finalizer_live_ordering_and_fresh_baseline(monkeypatch, failure):
    import cloudcoil.controller._registry as registry

    calls = []
    controller = Controller(Widget)
    obj = widget()
    obj.metadata.resource_version = "1"
    live = obj.model_copy(deep=True)
    live.metadata.resource_version = "2"
    live.metadata.finalizers = ["example.com/cleanup"]
    if failure == "delete":
        live.metadata.deletion_timestamp = "2026-09-08T00:00:00Z"
    if failure == "replaced":
        live.metadata.uid = "replacement"

    @controller.reconcile()
    async def reconcile(resource, ctx):
        calls.append("provision")
        assert resource.resource_version == "3"
        ctx.set_status(endpoint="new")
        if failure == "error":
            raise RuntimeError("failed")
        if failure == "wait":
            raise Wait("Pending")

    @controller.finalize("example.com/cleanup")
    async def cleanup(resource):
        calls.append("cleanup")

    async def get(*args):
        calls.append("get")
        if failure == "absent":
            from cloudcoil.errors import ResourceNotFound

            raise ResourceNotFound("gone", status_code=404)
        return live

    async def client(*args):
        return SimpleNamespace(get=get)

    monkeypatch.setattr(Request, "client", client)

    async def ensure(resource, key, **kwargs):
        calls.append("persist finalizer")
        resource.metadata.resource_version = "3"
        return resource

    async def remove(*args, **kwargs):
        calls.append("remove finalizer")

    monkeypatch.setattr(registry, "ensure_finalizer", ensure)
    monkeypatch.setattr(registry, "remove_finalizer", remove)
    req = request(obj)
    if failure in ("error", "replaced"):
        with pytest.raises(RuntimeError if failure == "error" else ResourceConflict):
            await controller.reconcile(req)
    else:
        await controller.reconcile(req)
    if failure == "delete":
        assert calls == ["get", "cleanup", "remove finalizer"]
    elif failure in ("absent", "replaced"):
        assert calls == ["get"]
    else:
        assert calls == ["get", "persist finalizer", "provision"]
        assert req._report.baseline.resource_version == "3"
        assert req._report.baseline.status is None
        assert req.object.status.endpoint == "new"
