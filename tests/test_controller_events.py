import asyncio
import json

import httpx
import pytest

from cloudcoil.client import Config
from cloudcoil.controller import EventRecorder
from tests.test_controller_status import widget


@pytest.fixture
async def sink():
    config = Config(server="https://cluster", namespace="events")
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(201, json={})

    config.async_client._mounts.clear()
    config.async_client._transport = httpx.MockTransport(handle)
    yield config, calls
    config.client.close()
    await config.async_client.aclose()


async def test_event_wire_identity_and_repetition(sink):
    config, calls = sink
    recorder = EventRecorder()
    obj = widget()
    assert await recorder.emit(obj, "Ready", "Available", config=config)
    assert not await recorder.emit(obj, "Ready", "Different message", config=config)
    body = json.loads(calls[0].content)
    assert body["apiVersion"] == "events.k8s.io/v1"
    assert body["regarding"]["uid"] == "u"
    assert body["regarding"]["namespace"] == "ns"
    assert calls[0].url.path == "/apis/events.k8s.io/v1/namespaces/ns/events"
    assert body["type"] == "Normal"
    obj.metadata.uid = "replacement"
    assert await recorder.emit(obj, "Ready", "Available", config=config)


async def test_cluster_scope_and_bounded_cache(sink):
    config, calls = sink
    recorder = EventRecorder(max_keys=2, namespace="operator")
    obj = widget()
    obj.metadata.namespace = None
    for reason in ("One", "Two", "Three"):
        assert await recorder.emit(obj, reason, "x", config=config)
    assert len(recorder._recent) == 2
    assert calls[0].url.path == "/apis/events.k8s.io/v1/namespaces/operator/events"
    assert "namespace" not in json.loads(calls[0].content)["regarding"]


@pytest.mark.parametrize("start", [0.0, 7.9, 1_000_000.1])
async def test_global_limit_and_interval(sink, start):
    config, calls = sink
    recorder = EventRecorder(interval=10)
    now = start
    recorder._last_token = now
    recorder._clock = lambda: now
    for i in range(30):
        await recorder.emit(widget(), f"Reason{i}", "x", config=config)
    assert len(calls) == 20
    now = start + 9.5
    assert not await recorder.emit(widget(), "Reason0", "x", config=config)
    now = start + 10
    assert await recorder.emit(widget(), "Reason0", "x", config=config)


@pytest.mark.parametrize("failure", ["forbidden", "timeout", "transport"])
async def test_delivery_failure_is_best_effort_and_throttled(sink, failure):
    config, calls = sink

    async def handle(request):
        calls.append(request)
        if failure == "timeout":
            await asyncio.Future()
        if failure == "transport":
            raise httpx.ConnectError("offline")
        return httpx.Response(403, json={"message": "denied"})

    config.async_client._transport = httpx.MockTransport(handle)
    recorder = EventRecorder(timeout=0.01)
    assert not await recorder.emit(widget(), "Ready", "x", config=config)
    assert not await recorder.emit(widget(), "Ready", "x", config=config)
    assert len(calls) == 1


async def test_concurrent_events_coalesce_and_cancellation_propagates(sink):
    config, calls = sink
    started = asyncio.Event()

    async def handle(request):
        calls.append(request)
        started.set()
        await asyncio.Future()

    config.async_client._transport = httpx.MockTransport(handle)
    recorder = EventRecorder()
    task = asyncio.create_task(recorder.emit(widget(), "Ready", "x", config=config))
    await started.wait()
    assert not await recorder.emit(widget(), "Ready", "x", config=config)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1
