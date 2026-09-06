import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.caching._informer import AsyncInformer, SyncInformer
from cloudcoil.caching._types import InformerOptions, InformerState
from cloudcoil.caching._watch_manager import _AsyncWatchManager
from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.errors import APIError, WatchExpired
from cloudcoil.resources import ResourceList


def obj(name, uid, rv="1", namespace="ns"):
    return ConfigMap(
        metadata={"name": name, "namespace": namespace, "uid": uid, "resourceVersion": rv}
    )


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_initial_and_relist_events_include_deletes_and_recreated_objects(asynchronous):
    cls = AsyncInformer if asynchronous else SyncInformer
    informer = cls(Mock(kind=ConfigMap), InformerOptions())
    events = []
    if asynchronous:

        async def added(item):
            events.append(("add", item.metadata.uid))

        async def updated(old, new):
            events.append(("update", old.resource_version, new.resource_version))

        async def deleted(item):
            events.append(("delete", item.metadata.uid))

        informer._watch.start = AsyncMock()
    else:

        def added(item):
            events.append(("add", item.metadata.uid))

        def updated(old, new):
            events.append(("update", old.resource_version, new.resource_version))

        def deleted(item):
            events.append(("delete", item.metadata.uid))

        informer._watch.start = Mock()
    informer.on_add(added)
    informer.on_update(updated)
    informer.on_delete(deleted)
    first = [obj("kept", "k"), obj("removed", "r"), obj("recreated", "old")]
    second = [obj("kept", "k", "2"), obj("recreated", "new")]
    if asynchronous:
        await informer._start()
        await informer._handle_initial_items(first, "1")
    else:
        informer._start()
        informer._handle_initial_items(first, "1")
    assert events == [("add", "k"), ("add", "r"), ("add", "old")]
    events.clear()
    if asynchronous:
        await informer._handle_initial_items(second, "2")
    else:
        informer._handle_initial_items(second, "2")
    assert events == [("delete", "r"), ("delete", "old"), ("update", "1", "2"), ("add", "new")]
    assert informer.get("removed", "ns") is None
    assert informer.has_synced()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_cluster_scoped_updates_find_previous_object(asynchronous):
    cls = AsyncInformer if asynchronous else SyncInformer
    informer = cls(Mock(kind=ConfigMap), InformerOptions())
    first, second = obj("global", "g", namespace=None), obj("global", "g", "2", namespace=None)
    informer._store.add(first)
    seen = []
    if asynchronous:

        async def handler(old, new):
            seen.append(old)

        await informer._dispatcher.register_update_handler(handler)
        await informer._handle_update(second)
    else:
        informer._dispatcher.register_update_handler(lambda old, new: seen.append(old))
        informer._handle_update(second)
    assert seen == [first]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("expiry", ["http", "event", "code"])
async def test_watch_expiry_can_be_propagated_for_relisting(asynchronous, expiry):
    def handler(request):
        if expiry == "http":
            return httpx.Response(410)
        status = {"code": 410} if expiry == "code" else {"status": "Failure", "reason": "Expired"}
        return httpx.Response(200, text=json.dumps({"type": "ERROR", "object": status}) + "\n")

    transport = httpx.MockTransport(handler)
    kwargs = dict(
        api_version="v1",
        kind=ConfigMap,
        resource="configmaps",
        namespaced=True,
        subresources=[],
        default_namespace="default",
    )
    if asynchronous:
        async with httpx.AsyncClient(transport=transport, base_url="https://cluster") as http:
            client = AsyncAPIClient(client=http, **kwargs)
            with pytest.raises(WatchExpired):
                await anext(client.watch(_raise_on_expired=True))
    else:
        with httpx.Client(transport=transport, base_url="https://cluster") as http:
            client = APIClient(client=http, **kwargs)
            with pytest.raises(WatchExpired):
                next(client.watch(_raise_on_expired=True))


@pytest.mark.parametrize("reason", ["expiry", "resync"])
async def test_manager_relists_and_closes_old_watch(reason):
    snapshots, closed = [], []
    relisted = asyncio.Event()
    client = Mock(kind=ConfigMap)
    client.list = AsyncMock(
        return_value=ResourceList[ConfigMap](
            api_version="v1",
            kind="ConfigMapList",
            items=[obj("a", "a")],
            metadata={"resourceVersion": "10"},
        )
    )
    options = InformerOptions().model_copy(
        update={"resync_period": 0.01 if reason == "resync" else 300}
    )

    async def watch(**kwargs):
        assert kwargs["_raise_on_expired"]
        try:
            if reason == "expiry" and len(snapshots) == 1:
                raise WatchExpired("expired", status_code=410)
            await asyncio.Event().wait()
            yield  # make this an async generator
        finally:
            closed.append(True)

    async def items(resources, rv):
        snapshots.append(rv)
        if len(snapshots) == 2:
            relisted.set()

    client.watch = watch
    manager = _AsyncWatchManager(client, options, items, AsyncMock())
    await manager.start()
    try:
        async with asyncio.timeout(1):
            await relisted.wait()
        assert snapshots == ["10", "10"]
        assert closed
    finally:
        await manager.stop()
    assert manager._task.done()


async def test_fatal_watch_error_is_retained_and_not_retried():
    client = Mock(kind=ConfigMap)
    client.list = AsyncMock(side_effect=APIError("forbidden", status_code=403))
    manager = _AsyncWatchManager(client, InformerOptions(), AsyncMock(), AsyncMock())
    await manager.start()
    await manager._task
    assert manager._state == InformerState.FAILED
    assert manager._error.status_code == 403
    client.list.assert_awaited_once()
    await manager.stop()


async def test_restart_does_not_reuse_stale_sync_state():
    informer = AsyncInformer(Mock(kind=ConfigMap), InformerOptions())
    informer._watch.start = AsyncMock()
    informer._watch.stop = AsyncMock()
    await informer._start()
    await informer._handle_initial_items([obj("a", "a")], "1")
    await informer._stop()
    await informer._start()
    assert not informer.has_synced()
    assert not await informer._wait_for_sync(timeout=0.001)
    await informer._stop()
