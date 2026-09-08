"""Application composition, scoped admission and typed leadership lifespans."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.autoscaling.v1 import Scale

from cloudcoil.admission import AdmissionRequest
from cloudcoil.application import Application, LifecycleEvent, LifecycleType, WebhookServer
from cloudcoil.controller import LeaderElection, LeadershipLost, Manager
from tests.test_operator import Widget


def test_empty_application_can_be_populated_by_decorators_and_generate_offline():
    app = Application(
        "widgets",
        webhook=WebhookServer(tls_secret="tls", ca_bundle=b"-----BEGIN CERTIFICATE-----\ntest"),
    )
    widgets = app.controller(Widget, owns=(Deployment,))

    @widgets.reconcile()
    async def reconcile(obj):
        pass

    @widgets.validate()
    async def validate(request: AdmissionRequest[Widget]):
        pass

    @app.validate(Scale, target=Deployment, subresource="scale", operations=("UPDATE",))
    async def scaling(request: AdmissionRequest[Scale]):
        pass

    @app.lifespan()
    async def never_enter():
        raise AssertionError("Offline manifests must not enter lifespan")
        yield

    documents = app.manifests()
    assert len(app.controllers) == 1
    assert [crd.resource for crd in app.crds] == [Widget]
    rules = [
        r
        for doc in documents
        if doc["kind"] == "ValidatingWebhookConfiguration"
        for hook in doc["webhooks"]
        for r in hook["rules"]
    ]
    assert any("deployments/scale" in r["resources"] for r in rules)
    assert any("widgets" in r["resources"] for r in rules)
    assert app.manifests() == documents
    app._validate(freeze=True)
    with pytest.raises(RuntimeError, match="before running"):
        app.controller(Deployment)
    with pytest.raises(RuntimeError, match="before running"):
        widgets.mutate()(validate)


def test_existing_resource_admission_does_not_install_crds_or_controllers():
    app = Application(
        "policy",
        webhook=WebhookServer(tls_secret="tls", ca_bundle=b"-----BEGIN CERTIFICATE-----\ntest"),
    )

    @app.validate(Deployment)
    async def validate(request):
        pass

    docs = app.manifests()
    assert not app.controllers
    assert not any(doc["kind"] == "CustomResourceDefinition" for doc in docs)


def test_cross_group_path_collisions_and_duplicate_inclusion_are_errors():
    app = Application(
        "policy",
        webhook=WebhookServer(tls_secret="tls", ca_bundle=b"-----BEGIN CERTIFICATE-----\ntest"),
    )
    widgets = app.controller(Widget)

    @widgets.reconcile()
    async def reconcile(obj):
        pass

    @widgets.validate(path="/same")
    async def first(request):
        pass

    @app.validate(Deployment, path="/same")
    async def second(request):
        pass

    with pytest.raises(ValueError, match="unique"):
        app.manifests()
    with pytest.raises(ValueError, match="twice"):
        app.include(widgets)


@pytest.mark.parametrize("scope", ["process", "leader"])
@pytest.mark.parametrize("failure", [False, True])
async def test_lifespan_event_type_updated_before_cleanup(scope, failure):
    app = Application("example")
    events = []

    @app.lifespan(scope=scope)
    async def lifecycle(event: LifecycleEvent) -> AsyncIterator[None]:
        events.append(event.type)
        try:
            yield
        finally:
            events.append(event.type)
            assert isinstance(event.error, RuntimeError) if failure else event.error is None

    async def run():
        async with app._lifespans.enter(scope):
            events.append("work")
            if failure:
                raise RuntimeError("failure")

    if failure:
        with pytest.raises(RuntimeError):
            await run()
    else:
        await run()
    assert events == [
        LifecycleType.STARTUP if scope == "process" else LifecycleType.LEADERSHIP_ACQUIRED,
        "work",
        LifecycleType.FAILURE if failure else LifecycleType.SHUTDOWN,
    ]


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_leadership_loss_stops_workers_then_cleans_up_before_release(
    monkeypatch, cleanup_failure
):
    events = []
    started = asyncio.Event()
    lost = LeadershipLost("ownership changed")
    leader = LeaderElection("example", identity="replica-a")
    app = Application("example", leader_election=leader)
    controller = app.controller(Widget)

    @controller.reconcile()
    async def reconcile(obj):
        pass

    @app.lifespan(scope="leader")
    async def leadership(event):
        assert event.identity == "replica-a"
        events.append(event.type)
        try:
            yield
        finally:
            assert event.error is lost
            events.append(event.type)
            if cleanup_failure:
                raise RuntimeError("cleanup failed")

    async def attempt(config):
        return True

    async def renew(config):
        await started.wait()
        raise lost

    async def release(config):
        events.append("release")

    async def prepare():
        pass

    async def work(*, stop):
        events.append("workers started")
        started.set()
        try:
            await asyncio.Future()
        finally:
            events.append("workers stopped")

    monkeypatch.setattr(leader, "_attempt", attempt)
    monkeypatch.setattr(leader, "_renew", renew)
    monkeypatch.setattr(leader, "_release", release)
    monkeypatch.setattr(controller, "run", work)
    manager = Manager(
        controller,
        leader_election=leader,
        leader_lifespan=lambda: app._lifespans.enter("leader", leader),
    )
    monkeypatch.setattr(manager, "_prepare", prepare)
    if cleanup_failure:
        with pytest.raises(BaseExceptionGroup) as raised:
            await manager.run()
        assert any(isinstance(error, LeadershipLost) for error in raised.value.exceptions)
        assert any(isinstance(error, RuntimeError) for error in raised.value.exceptions)
    else:
        with pytest.raises(LeadershipLost):
            await manager.run()
    assert events == [
        LifecycleType.LEADERSHIP_ACQUIRED,
        "workers started",
        "workers stopped",
        LifecycleType.LEADERSHIP_LOST,
        "release",
    ]


def test_lifespan_registration_errors_and_leader_scope_requires_election():
    app = Application("example")
    controller = app.controller(Widget)

    @controller.reconcile()
    async def reconcile(obj):
        pass

    async def invalid():
        pass

    with pytest.raises(TypeError, match="async generator"):
        app.lifespan()(invalid)

    @app.lifespan(scope="leader")
    async def leader():
        yield

    with pytest.raises(ValueError, match="leader election"):
        app.manifests()
    with pytest.raises(ValueError, match="Only one"):
        app.lifespan(scope="leader")(leader)
