"""Operator startup, admission availability, and cleanup ownership."""

import asyncio
import socket
import subprocess
from typing import Literal, Self
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from pydantic import Field

from cloudcoil.admission import AdmissionRequest, validating
from cloudcoil.client import AsyncAPIClient, Config
from cloudcoil.controller import Controller, LeaderElection
from cloudcoil.crd import custom_resource
from cloudcoil.operator import Operator, WebhookServer
from cloudcoil.operator._server import _HTTPS
from cloudcoil.resources import Resource


@custom_resource(plural="widgets")
class Widget(Resource):
    api_version: Literal["operators.example/v1"] = Field(
        default="operators.example/v1", alias="apiVersion"
    )
    kind: Literal["Widget"] = "Widget"


@custom_resource(plural="policies")
class Policy(Widget):
    kind: Literal["Policy"] = "Policy"

    @classmethod
    @validating()
    async def validate_resource(
        cls, request: AdmissionRequest[Self], client: AsyncAPIClient[Self]
    ) -> None:
        pass


async def reconcile(request):
    pass


@pytest.fixture
def config(monkeypatch):
    value = Config(server="https://example.invalid", namespace="operators")
    monkeypatch.setattr(value, "async_initialize", AsyncMock())
    yield value
    value.client.close()
    asyncio.run(value.async_client.aclose())


@pytest.fixture
def components(monkeypatch):
    events = []

    class Manager:
        ready = True
        healthy = False

        def __init__(self, *controllers, **kwargs):
            self.options = kwargs

        async def run(self, *, stop):
            self.healthy = True
            events.append("manager-start")
            try:
                await stop.wait()
            finally:
                self.healthy = False
                events.append("manager-stop")

        def metrics(self):
            return "metric 1\n"

    class HTTPS:
        def __init__(self, app, options):
            self.app = app
            self.task = None

        async def start(self):
            events.append("server-start")
            self.task = asyncio.create_task(asyncio.Event().wait())

        async def close(self):
            events.append("server-stop")
            if self.task:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)

    monkeypatch.setattr("cloudcoil.operator._operator.Manager", Manager)
    monkeypatch.setattr("cloudcoil.operator._operator._HTTPS", HTTPS)
    return events, Manager, HTTPS


def test_manifests_and_cli_need_no_config_or_tls_files(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline generation must not load credentials")

    monkeypatch.setattr("cloudcoil.operator._operator.Config", forbidden)
    app = Operator(
        "widgets",
        Controller(Policy, reconcile),
        namespace="operators",
        webhook=WebhookServer(ca_bundle=b"-----BEGIN CERTIFICATE-----\npublic"),
    )
    app.main(["manifests", "--image", "example/operator:v1", "--command", "python", "app.py"])
    documents = list(yaml.safe_load_all(capsys.readouterr().out))
    assert documents[0]["kind"] == "CustomResourceDefinition"
    assert documents[-1]["kind"] == "ValidatingWebhookConfiguration"
    deployment = next(d for d in documents if d["kind"] == "Deployment")
    assert deployment["spec"]["template"]["spec"]["containers"][0]["args"] == ["run"]
    assert app.config is None


def test_shared_config_and_policy_configuration_are_explicit(config):
    with pytest.raises(ValueError, match="Config.namespace"):
        Operator("widgets", Controller(Widget, reconcile), config=config, namespace="other")
    with pytest.raises(ValueError, match="share the operator Config"):
        Operator("widgets", Controller(Widget, reconcile, config=config))
    with pytest.raises(ValueError, match="require webhook"):
        Operator("widgets", Controller(Policy, reconcile))


async def test_lifecycle_stops_components_before_closing_owned_config(
    config, components, monkeypatch
):
    events, _, _ = components
    monkeypatch.setattr("cloudcoil.operator._operator.Config", lambda **kwargs: config)
    original_exit = Config.__aexit__

    async def exit_scope(self, *args):
        events.append("config-exit")
        await original_exit(self, *args)

    monkeypatch.setattr(Config, "__aexit__", exit_scope)
    app = Operator(
        "widgets", Controller(Policy, reconcile), namespace="operators", webhook=WebhookServer()
    )
    stop = asyncio.Event()
    task = asyncio.create_task(app.run(stop=stop))
    await app.wait_ready()
    stop.set()
    await task
    assert events.index("server-stop") < events.index("config-exit")
    assert events.index("manager-stop") < events.index("config-exit")
    assert config.client.is_closed and config.async_client.is_closed
    assert not app.ready and not app.healthy
    with pytest.raises(RuntimeError, match="only run once"):
        await app.run()


async def test_borrowed_config_stays_open_and_embedded_run_keeps_signals(
    config, components, monkeypatch
):
    monkeypatch.setattr(
        asyncio.get_running_loop(), "add_signal_handler", lambda *args: pytest.fail("signals")
    )
    app = Operator("widgets", Controller(Widget, reconcile), namespace="operators", config=config)
    task = asyncio.create_task(app.run())
    await app.wait_ready()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not config.client.is_closed and not config.async_client.is_closed
    assert not app.healthy


async def test_standby_replica_serves_webhooks(config, components):
    _, manager, _ = components
    manager.ready = False
    app = Operator(
        "widgets",
        Controller(Policy, reconcile),
        namespace="operators",
        config=config,
        webhook=WebhookServer(),
        leader_election=LeaderElection("widgets"),
    )
    stop = asyncio.Event()
    task = asyncio.create_task(app.run(stop=stop))
    await app.wait_ready()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app._application(app._admission(config))),
        base_url="https://operator",
    ) as client:
        assert (await client.get("/readyz")).status_code == 200
        assert (await client.get("/controllers/readyz")).status_code == 503
    stop.set()
    await task


async def test_stop_during_discovery_cancels_startup(config, components):
    started = asyncio.Event()

    async def discover():
        started.set()
        await asyncio.Event().wait()

    config.async_initialize = discover
    app = Operator("widgets", Controller(Widget, reconcile), namespace="operators", config=config)
    stop = asyncio.Event()
    task = asyncio.create_task(app.run(stop=stop))
    await started.wait()
    stop.set()
    await asyncio.wait_for(task, 1)
    assert components[0] == []
    assert not app.healthy


async def test_component_failure_stops_siblings(config, components, monkeypatch):
    events, manager, _ = components

    async def fail(self, *, stop):
        self.healthy = True
        raise ValueError("controller failed")

    monkeypatch.setattr(manager, "run", fail)
    app = Operator(
        "widgets",
        Controller(Policy, reconcile),
        namespace="operators",
        config=config,
        webhook=WebhookServer(),
    )
    with pytest.raises(ValueError, match="controller failed"):
        await app.run()
    assert "server-stop" in events
    with pytest.raises(ValueError, match="controller failed"):
        await app.wait_ready()


async def test_webhook_install_requires_rollout_before_registration(config):
    app = Operator(
        "widgets",
        resources=(Policy,),
        namespace="operators",
        config=config,
        webhook=WebhookServer(),
    )
    with pytest.raises(ValueError, match="requires image"):
        await app.install()


async def test_shutdown_failure_is_reported_on_explicit_stop(config, components, monkeypatch):
    _, _, server = components
    original = server.close

    async def fail_close(self):
        await original(self)
        raise OSError("close failed")

    monkeypatch.setattr(server, "close", fail_close)
    app = Operator("widgets", resources=(Policy,), config=config, webhook=WebhookServer())
    stop = asyncio.Event()
    task = asyncio.create_task(app.run(stop=stop))
    await app.wait_ready()
    stop.set()
    with pytest.raises(OSError, match="close failed"):
        await task


async def test_primary_and_cleanup_failures_both_survive(config, components, monkeypatch):
    _, manager, server = components
    original = server.close

    async def fail_run(self, *, stop):
        raise ValueError("primary failed")

    async def fail_close(self):
        await original(self)
        raise OSError("close failed")

    monkeypatch.setattr(manager, "run", fail_run)
    monkeypatch.setattr(server, "close", fail_close)
    app = Operator("widgets", Controller(Policy, reconcile), config=config, webhook=WebhookServer())
    with pytest.raises(ExceptionGroup) as error:
        await app.run()
    assert {str(item) for item in error.value.exceptions} == {"primary failed", "close failed"}


@pytest.fixture
def tls(tmp_path):
    cert, key = tmp_path / "tls.crt", tmp_path / "tls.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return WebhookServer(certfile=str(cert), keyfile=str(key), host="127.0.0.1", port=port)


async def test_real_https_webhook_server_starts_and_drains(tls):
    from cloudcoil.admission import AdmissionWebhook

    server = _HTTPS(AdmissionWebhook(), tls)
    try:
        await server.start()
        async with httpx.AsyncClient(verify=False, trust_env=False) as client:
            response = await client.get(f"https://127.0.0.1:{tls.port}/healthz")
            assert response.status_code == 200
    finally:
        await server.close()
    assert server.task.done()


async def test_server_system_exit_becomes_startup_error(tls, monkeypatch):
    server = _HTTPS(None, tls)

    async def fail():
        raise SystemExit(1)

    monkeypatch.setattr(server.server, "serve", fail)
    try:
        with pytest.raises(RuntimeError, match="could not start"):
            await server.start()
    finally:
        await server.close()
