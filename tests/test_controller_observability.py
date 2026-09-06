"""Metrics reflect real worker outcomes; diagnostics follow manager lifecycle."""

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.controller import (
    Controller,
    HealthServer,
    Manager,
    ResourceKey,
    Result,
    TerminalError,
)
from tests.test_controllers import Cluster, cm, running, wait


@pytest.fixture
async def cluster():
    instance = Cluster()
    try:
        yield instance
    finally:
        instance.config.client.close()
        await instance.config.async_client.aclose()


async def request(address, path="/healthz", *, raw=None):
    reader, writer = await asyncio.open_connection(*address)
    try:
        writer.write(raw or f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        header, body = response.split(b"\r\n\r\n", 1)
        assert f"Content-Length: {len(body)}".encode() in header
        assert b"Connection: close" in header
        return int(header.split()[1]), body.decode(), header
    finally:
        writer.close()
        await writer.wait_closed()


async def test_queue_snapshots_outcomes_and_prometheus_histogram(cluster):
    entered = asyncio.Queue()
    release = asyncio.Event()

    async def reconcile(req):
        entered.put_nowait(req.name)
        await release.wait()
        if req.name == "error":
            raise ValueError("transient")
        if req.name == "terminal":
            raise TerminalError("invalid")
        return Result(requeue_after=60)

    controller = Controller(ConfigMap, reconcile, name='mirror"\\\n', config=cluster.config)
    manager = Manager(controller)
    assert not manager.healthy and not manager.ready
    for name in ("success", "error", "terminal"):
        controller.enqueue(ResourceKey(name, "ns"))
    before = controller.status
    assert before.queued == 3 and before.processing == 0
    with pytest.raises(FrozenInstanceError):
        before.queued = 0
    async with running(manager):
        assert await wait(entered.get()) == "success"
        assert controller.status.queued == 2 and controller.status.processing == 1
        release.set()
        assert await wait(entered.get()) == "error"
        assert await wait(entered.get()) == "terminal"
        # Let the last worker complete before inspecting counters.
        async with asyncio.timeout(2):
            while controller.status.processing:
                await asyncio.sleep(0)
        status = controller.status
        assert (status.successes, status.errors, status.terminal_errors) == (1, 1, 1)
        assert status.queued == status.processing == status.cancellations == 0
        assert status.delayed == 2
        assert status.duration_seconds > 0
        assert before.queued == 3  # Snapshots do not change under callers.
        metrics = manager.metrics()
        escaped = 'controller="mirror\\"\\\\\\n"'
        assert f'cloudcoil_controller_reconciles_total{{{escaped},result="error"}} 1\n' in metrics
        assert f"cloudcoil_controller_reconcile_duration_seconds_count{{{escaped}}} 3\n" in metrics
        assert (
            f'cloudcoil_controller_reconcile_duration_seconds_bucket{{{escaped},le="+Inf"}} 3\n'
            in metrics
        )
        assert (
            f"cloudcoil_controller_reconcile_duration_seconds_sum{{{escaped}}} {status.duration_seconds}\n"
            in metrics
        )
        counts = [
            int(line.rsplit(" ", 1)[1]) for line in metrics.splitlines() if "_bucket{" in line
        ]
        assert counts == sorted(counts) and counts[-1] == 3
    assert controller.status.delayed == 0
    assert controller.status.errors == 1
    assert "cloudcoil_manager_healthy 0\n" in manager.metrics()


async def test_cancelled_attempt_is_counted_and_worker_released(cluster):
    cluster.items["configmaps"] = [cm()]
    started = asyncio.Event()

    async def reconcile(req):
        started.set()
        await asyncio.Event().wait()

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    task = asyncio.create_task(controller.run())
    try:
        await wait(started.wait())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert controller.status.cancellations == 1
        assert controller.status.processing == controller.status.successes == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_probe_states_http_bounds_and_cleanup(cluster):
    gate = cluster.gates["configmaps"] = asyncio.Event()
    server = HealthServer(port=0)

    async def reconcile(req):
        pass

    manager = Manager(Controller(ConfigMap, reconcile), config=cluster.config, health=server)
    task = asyncio.create_task(manager.run())
    slow_writer = None
    try:
        async with asyncio.timeout(2):
            while server.address is None:
                await asyncio.sleep(0)
        address = server.address
        assert (await request(address))[0:2] == (200, "ok\n")
        assert (await request(address, "/readyz"))[0:2] == (503, "not ready\n")
        gate.set()
        await manager.wait_ready(timeout=2)
        assert (await request(address, "/readyz"))[0:2] == (200, "ok\n")
        code, body, header = await request(address, "/metrics")
        assert code == 200 and "cloudcoil_manager_ready 1\n" in body
        assert b"version=0.0.4" in header
        assert (await request(address, "/missing"))[0] == 404
        assert (await request(address, raw=b"POST /healthz HTTP/1.1\r\n\r\n"))[0] == 405
        assert (await request(address, raw=b"broken\r\n\r\n"))[0] == 400
        assert (await request(address, raw=b"GET / HTTP/1.1\r\nX: " + b"a" * 9000 + b"\r\n\r\n"))[
            0
        ] == 431
        slow_reader, slow_writer = await asyncio.open_connection(*address)
        slow_writer.write(b"GET /healthz HTTP/1.1\r\n")
        await slow_writer.drain()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait(task)
        assert await wait(slow_reader.read()) == b""
        assert server.address is None and not server._tasks
        assert not manager.healthy and not manager.ready
        with pytest.raises(OSError):
            await asyncio.open_connection(*address)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if slow_writer:
            slow_writer.close()
            await slow_writer.wait_closed()


async def test_bind_failure_prevents_start_and_surfaces_to_wait_ready(cluster):
    blocker = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = blocker.sockets[0].getsockname()[1]

    async def reconcile(req):
        pass

    manager = Manager(
        Controller(ConfigMap, reconcile), config=cluster.config, health=HealthServer(port=port)
    )
    try:
        with pytest.raises(OSError):
            await manager.run()
        with pytest.raises(OSError):
            await manager.wait_ready(timeout=1)
        assert not manager.healthy and manager.informer_count == 0
    finally:
        blocker.close()
        await blocker.wait_closed()


def test_metrics_names_are_local_and_unique():
    async def reconcile(req):
        pass

    manager = Manager(Controller(ConfigMap, reconcile), Controller(ConfigMap, reconcile))
    assert 'controller="configmap-1"' in manager.metrics()
    assert 'controller="configmap-2"' in manager.metrics()
    with pytest.raises(ValueError, match="distinct"):
        Manager(
            Controller(ConfigMap, reconcile, name="same"),
            Controller(ConfigMap, reconcile, name="same"),
        )
    with pytest.raises(ValueError, match="empty"):
        Controller(ConfigMap, reconcile, name=" ")
    for port in (-1, 65536, True, 1.5):
        with pytest.raises(ValueError):
            HealthServer(port=port)
