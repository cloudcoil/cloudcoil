"""Returned primary snapshots produce guarded patches, including CRD status."""

import asyncio
import json
from typing import Literal

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.client import Config
from cloudcoil.controller import Controller, ResourceKey, Result, WorkQueue
from cloudcoil.controller._mutations import _persist
from cloudcoil.errors import APIError, ResourceConflict
from cloudcoil.resources import Resource
from tests.test_controllers import Cluster, cm, running, wait


class Widget(Resource):
    api_version: Literal["example.com/v1"] = "example.com/v1"
    kind: Literal["Widget"] = "Widget"
    spec: dict[str, int] = {}
    status: dict[str, str] | None = None


@pytest.fixture
async def cluster():
    instance = Cluster()
    try:
        yield instance
    finally:
        instance.config.client.close()
        await instance.config.async_client.aclose()


@pytest.mark.parametrize("wrapped", [False, True])
async def test_return_persists_primary_and_unchanged_watch_echo_is_noop(cluster, wrapped):
    cluster.items["configmaps"] = [cm()]
    patches = []
    calls = asyncio.Queue()

    async def handler(request):
        if request.method != "PATCH":
            return await cluster.handle(request)
        operations = json.loads(request.content)
        patches.append(operations)
        assert operations == [
            {"op": "test", "path": "/metadata/uid", "value": "a"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "1"},
            {"op": "replace", "path": "/data/value", "value": "desired"},
        ]
        updated = cm(rv="2")
        updated.data = {"value": "desired"}
        cluster.emit("configmaps", "MODIFIED", updated)
        return httpx.Response(200, json=updated.model_dump(by_alias=True, exclude_none=True))

    cluster.config.async_client._transport = httpx.MockTransport(handler)

    async def reconcile(req):
        calls.put_nowait(req.resource.data["value"])
        req.resource.data["value"] = "desired"
        return Result(resource=req.resource, requeue_after=60) if wrapped else req.resource

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    async with running(controller):
        assert await wait(calls.get()) == "1"
        assert await wait(calls.get()) == "desired"
        assert len(patches) == 1
        assert controller.status.successes == 2
        assert controller.status.delayed == int(wrapped)


@pytest.mark.parametrize("status", [409, 422])
async def test_conflict_retries_against_new_snapshot_preserving_concurrent_changes(cluster, status):
    cluster.items["configmaps"] = [cm()]
    requests = []
    done = asyncio.Event()

    async def handler(request):
        if request.method != "PATCH":
            return await cluster.handle(request)
        operations = json.loads(request.content)
        requests.append(operations)
        if len(requests) == 1:
            assert operations[1]["value"] == "1"
            fresh = cm(rv="2")
            fresh.data["other"] = "external writer"
            cluster.emit("configmaps", "MODIFIED", fresh)
            return httpx.Response(status, json={"message": "stale resourceVersion"})
        assert operations == [
            {"op": "test", "path": "/metadata/uid", "value": "a"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "2"},
            {"op": "replace", "path": "/data/value", "value": "desired"},
        ]
        done.set()
        current = cm(rv="3")
        current.data = {"value": "desired", "other": "external writer"}
        return httpx.Response(200, json=current.model_dump(by_alias=True, exclude_none=True))

    cluster.config.async_client._transport = httpx.MockTransport(handler)

    async def reconcile(req):
        req.resource.data["value"] = "desired"
        return req.resource

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    controller._queue = WorkQueue(base_delay=0.01, max_delay=0.01)
    async with running(controller):
        await wait(done.wait())
        assert controller.status.errors == 1 and controller.status.successes == 1
        assert len(requests) == 2
        assert controller._primary.get("a", "ns").data["other"] == "external writer"


@pytest.mark.parametrize("outcome", ["none", "error", "wrong_kind", "wrong_name", "absent"])
async def test_only_explicit_valid_primary_returns_write(cluster, outcome):
    if outcome != "absent":
        cluster.items["configmaps"] = [cm()]
    called = asyncio.Event()

    async def reconcile(req):
        called.set()
        if req.resource:
            req.resource.data["value"] = "local edit"
        if outcome == "none":
            return None
        if outcome == "error":
            raise RuntimeError("after local edit")
        if outcome == "wrong_kind":
            return Widget(metadata=cm().metadata)
        if outcome == "wrong_name":
            req.resource.metadata.name = "another"
        return req.resource if req.resource else cm()

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    controller.enqueue(ResourceKey("a", "ns"))
    async with running(controller):
        await wait(called.wait())
        assert not any(req.method == "PATCH" for req in cluster.requests)
        assert controller.status.errors == int(outcome != "none")
        if outcome != "absent":
            assert controller._primary.get("a", "ns").data["value"] == "1"


@pytest.fixture
async def widget_config():
    config = Config(server="https://cluster", namespace="ns")
    config.async_client._mounts.clear()
    config._rest_mapping[Widget.gvk()] = {
        "resource": "widgets",
        "namespaced": True,
        "subresources": ["status"],
    }
    try:
        yield config
    finally:
        config.client.close()
        await config.async_client.aclose()


def widget():
    return Widget(
        metadata={"name": "example", "namespace": "ns", "uid": "uid", "resourceVersion": "7"},
        spec={"replicas": 1},
        status={"phase": "Pending"},
    )


@pytest.mark.parametrize(
    "mode", ["status", "main", "both", "noop", "inline_status", "remove_status"]
)
async def test_custom_resource_status_routing_and_version_chain(widget_config, mode):
    original = widget()
    desired = original.model_copy(deep=True)
    if mode in ("main", "both"):
        desired.spec["replicas"] = 2
    if mode in ("status", "both", "inline_status"):
        desired.status["phase"] = "Ready"
    if mode == "remove_status":
        desired.status = None
    if mode == "inline_status":
        widget_config._rest_mapping[Widget.gvk()]["subresources"] = []
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "PATCH"  # No unsafe live-read rebase.
        operations = json.loads(request.content)
        assert operations[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": "uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": str(6 + len(requests))},
        ]
        status_route = request.url.path.endswith("/status")
        if status_route or mode == "inline_status":
            assert operations[2:] == (
                [{"op": "remove", "path": "/status"}]
                if mode == "remove_status"
                else [{"op": "replace", "path": "/status/phase", "value": "Ready"}]
            )
            updated = desired.model_copy(deep=True)
        else:
            assert operations[2:] == [{"op": "replace", "path": "/spec/replicas", "value": 2}]
            updated = original.model_copy(deep=True)
            updated.spec = desired.spec
        updated.metadata.resource_version = str(7 + len(requests))
        return httpx.Response(200, json=updated.model_dump(by_alias=True, exclude_none=True))

    widget_config.async_client._transport = httpx.MockTransport(handler)
    async with widget_config:
        result = await _persist(original, desired)
    assert len(requests) == (0 if mode == "noop" else 2 if mode == "both" else 1)
    if requests:
        assert requests[-1].url.path.endswith("/status") == (
            mode in ("status", "both", "remove_status")
        )
    assert result.spec == desired.spec and result.status == desired.status
    assert original.spec == {"replicas": 1} and original.status == {"phase": "Pending"}


@pytest.mark.parametrize("failure", ["status_conflict", "admission_status", "replaced_uid"])
async def test_partial_write_does_not_overwrite_changed_status_or_roll_back(widget_config, failure):
    original = widget()
    desired = original.model_copy(deep=True)
    desired.spec["replicas"] = 2
    desired.status["phase"] = "Ready"
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/status"):
            assert failure == "status_conflict"
            return httpx.Response(409, json={"message": "concurrent status writer"})
        response = original.model_copy(deep=True)
        response.spec = desired.spec
        response.metadata.resource_version = "8"
        if failure == "admission_status":
            response.status = {"phase": "external change"}
        if failure == "replaced_uid":
            response.metadata.uid = "replacement"
        return httpx.Response(200, json=response.model_dump(by_alias=True, exclude_none=True))

    widget_config.async_client._transport = httpx.MockTransport(handler)
    async with widget_config:
        with pytest.raises(APIError if failure == "status_conflict" else ResourceConflict):
            await _persist(original, desired)
    assert len(requests) == (2 if failure == "status_conflict" else 1)
