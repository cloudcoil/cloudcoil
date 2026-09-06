import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Literal

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace, Secret

from cloudcoil._context import context
from cloudcoil.client import Config
from cloudcoil.controller import (
    Controller,
    Manager,
    Request,
    ResourceKey,
    Result,
    TerminalError,
    WorkQueue,
)
from cloudcoil.errors import APIError
from cloudcoil.resources import Resource


def cm(name="a", uid=None, namespace="ns", rv="1"):
    return ConfigMap(
        metadata={"name": name, "namespace": namespace, "uid": uid or name, "resourceVersion": rv},
        data={"value": rv},
    )


class EventStream(httpx.AsyncByteStream):
    def __init__(self, events):
        self.events = events
        self.closed = False

    async def __aiter__(self):
        while True:
            yield (json.dumps(await self.events.get()) + "\n").encode()

    async def aclose(self):
        self.closed = True


class Cluster:
    def __init__(self):
        self.config = Config(server="https://cluster", namespace="ns")
        self.config.async_client._mounts.clear()
        self.config.async_client._transport = httpx.MockTransport(self.handle)
        self.items = defaultdict(list)
        self.events = defaultdict(asyncio.Queue)
        self.streams = []
        self.requests = []
        self.gates = {}
        self.errors = {}
        for kind, plural, namespaced in (
            (ConfigMap, "configmaps", True),
            (Secret, "secrets", True),
            (Namespace, "namespaces", False),
        ):
            self.config._rest_mapping[kind.gvk()] = {
                "resource": plural,
                "namespaced": namespaced,
                "subresources": [],
            }

    async def handle(self, request):
        self.requests.append(request)
        plural = request.url.path.rsplit("/", 1)[-1]
        if plural in self.errors:
            return httpx.Response(self.errors[plural], json={"message": "forbidden"})
        if request.url.params.get("watch") == "true":
            stream = EventStream(self.events[plural])
            self.streams.append(stream)
            return httpx.Response(200, stream=stream)
        if plural in self.gates:
            await self.gates[plural].wait()
        return httpx.Response(
            200,
            json={
                "apiVersion": "v1",
                "kind": {
                    "configmaps": "ConfigMapList",
                    "secrets": "SecretList",
                    "namespaces": "NamespaceList",
                }[plural],
                "metadata": {"resourceVersion": "1"},
                "items": [
                    obj.model_dump(by_alias=True, exclude_none=True) for obj in self.items[plural]
                ],
            },
        )

    def emit(self, plural, event, obj):
        self.events[plural].put_nowait(
            {"type": event, "object": obj.model_dump(by_alias=True, exclude_none=True)}
        )


@pytest.fixture
async def cluster():
    cluster = Cluster()
    yield cluster
    cluster.config.client.close()
    await cluster.config.async_client.aclose()


async def wait(awaitable):
    return await asyncio.wait_for(awaitable, 2)


@asynccontextmanager
async def running(controller):
    stop = asyncio.Event()
    task = asyncio.create_task(controller.run(stop=stop))
    try:
        await controller.wait_ready(timeout=2)
        yield stop, task
    finally:
        stop.set()
        try:
            await wait(task)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_initial_latest_and_absent_state_are_reconciled_without_cache_mutation(cluster):
    cluster.items["configmaps"] = [cm()]
    calls = asyncio.Queue()

    async def reconcile(request: Request[ConfigMap]):
        assert context.active_config is cluster.config
        calls.put_nowait(request)
        if request.resource is not None:
            request.resource.data["value"] = "local mutation"

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    async with running(controller):
        first = await wait(calls.get())
        assert first.name == "a" and first.namespace == "ns"
        assert controller._primary.get("a", "ns").data["value"] == "1"
        cluster.emit("configmaps", "MODIFIED", cm(rv="2"))
        second = await wait(calls.get())
        assert second.resource.resource_version == "2"
        cluster.emit("configmaps", "DELETED", cm(rv="2"))
        assert (await wait(calls.get())).resource is None
    assert all(stream.closed for stream in cluster.streams)
    assert not controller.ready


async def test_retry_terminal_error_and_explicit_requeue(cluster):
    cluster.items["configmaps"] = [cm()]
    attempts = []
    finished = asyncio.Event()

    async def reconcile(request):
        attempts.append(request.key)
        if len(attempts) == 1:
            raise RuntimeError("retry me")
        if len(attempts) == 2:
            return Result(requeue_after=0.001)
        finished.set()
        raise TerminalError("wait for an external event")

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    controller._queue = WorkQueue(base_delay=0.001, max_delay=0.01, jitter=0)
    async with running(controller):
        await wait(finished.wait())
        await wait(controller._queue.join())
        assert len(attempts) == 3
        assert controller._queue.num_retries(ResourceKey("a", "ns")) == 0


async def test_readiness_waits_for_secondary_sync_before_any_reconcile(cluster):
    cluster.items["configmaps"] = [cm()]
    cluster.gates["secrets"] = asyncio.Event()
    called = asyncio.Event()
    secondary_list_started = asyncio.Event()
    original = cluster.handle

    async def handle(request):
        if request.url.path.endswith("/secrets"):
            secondary_list_started.set()
        return await original(request)

    cluster.config.async_client._transport = httpx.MockTransport(handle)

    async def reconcile(request):
        called.set()

    controller = Controller(ConfigMap, reconcile, config=cluster.config).owns(Secret)
    task = asyncio.create_task(controller.run())
    try:
        await wait(secondary_list_started.wait())
        assert not called.is_set() and not controller.ready
        cluster.gates["secrets"].set()
        await controller.wait_ready(2)
        await wait(called.wait())
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(stream.closed for stream in cluster.streams)


async def test_owned_children_match_uid_and_reject_recreated_owner(cluster):
    cluster.items["configmaps"] = [cm()]
    calls = asyncio.Queue()

    async def reconcile(request):
        calls.put_nowait(request)

    controller = Controller(ConfigMap, reconcile, config=cluster.config).owns(Secret)

    def child(uid):
        return Secret(
            metadata={
                "name": "child",
                "namespace": "ns",
                "ownerReferences": [
                    {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "name": "a",
                        "uid": uid,
                        "controller": True,
                    }
                ],
            }
        )

    async with running(controller):
        await wait(calls.get())
        cluster.emit("secrets", "ADDED", child("a"))
        assert (await wait(calls.get())).name == "a"
        cluster.emit("secrets", "MODIFIED", child("stale"))
        # Update maps both the old (valid) and new (stale) owner.
        await wait(calls.get())
        cluster.emit("secrets", "DELETED", child("stale"))
        # A later valid event acts as a watch-stream barrier.
        cluster.emit("secrets", "ADDED", child("a"))
        await wait(calls.get())
        await wait(controller._queue.join())
        assert calls.empty()


async def test_cluster_scoped_owner_watches_children_across_namespaces(cluster):
    cluster.items["namespaces"] = [Namespace(metadata={"name": "parent", "uid": "parent"})]
    calls = asyncio.Queue()

    async def reconcile(request):
        calls.put_nowait(request)

    controller = Controller(Namespace, reconcile, config=cluster.config).owns(Secret)
    async with running(controller):
        assert (await wait(calls.get())).namespace is None
        child = Secret(
            metadata={
                "name": "child",
                "namespace": "elsewhere",
                "ownerReferences": [
                    {
                        "apiVersion": "v1",
                        "kind": "Namespace",
                        "name": "parent",
                        "uid": "parent",
                        "controller": True,
                    }
                ],
            }
        )
        cluster.emit("secrets", "ADDED", child)
        assert (await wait(calls.get())).name == "parent"
    assert any(request.url.path == "/api/v1/secrets" for request in cluster.requests)


async def test_dependency_update_enqueues_both_old_and_new_targets(cluster):
    cluster.items["configmaps"] = [cm("a"), cm("b")]
    cluster.items["secrets"] = [
        Secret(metadata={"name": "dependency", "namespace": "ns", "labels": {"target": "a"}})
    ]
    calls = asyncio.Queue()

    async def reconcile(request):
        calls.put_nowait(request.name)

    controller = Controller(
        ConfigMap, reconcile, config=cluster.config, label_selector="managed=true"
    ).watch(Secret, mapper=lambda obj: [ResourceKey(obj.metadata.labels["target"], obj.namespace)])
    async with running(controller):
        assert {await wait(calls.get()), await wait(calls.get())} == {"a", "b"}
        await wait(controller._queue.join())
        cluster.emit(
            "secrets",
            "MODIFIED",
            Secret(metadata={"name": "dependency", "namespace": "ns", "labels": {"target": "b"}}),
        )
        assert {await wait(calls.get()), await wait(calls.get())} == {"a", "b"}
    assert all(
        "labelSelector" not in request.url.params
        for request in cluster.requests
        if request.url.path.endswith("/secrets")
    )


async def test_mapper_failure_stops_controller_instead_of_dropping_event(cluster):
    async def reconcile(request):
        pass

    def broken(obj):
        raise ValueError("bad mapper")

    controller = Controller(ConfigMap, reconcile, config=cluster.config).watch(
        Secret, mapper=broken
    )
    task = asyncio.create_task(controller.run())
    await controller.wait_ready(2)
    cluster.emit("secrets", "ADDED", Secret(metadata={"name": "child", "namespace": "ns"}))
    with pytest.raises(ValueError, match="bad mapper"):
        await wait(task)
    assert not controller.ready and all(stream.closed for stream in cluster.streams)


async def test_startup_permission_failure_propagates_to_run_and_readiness(cluster):
    cluster.errors["configmaps"] = 403

    async def reconcile(request):
        pytest.fail("must not reconcile before sync")

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    task = asyncio.create_task(controller.run())
    with pytest.raises(APIError):
        await controller.wait_ready(2)
    with pytest.raises(APIError):
        await wait(task)


async def test_cancel_during_startup_closes_started_watches(cluster):
    cluster.gates["secrets"] = asyncio.Event()
    primary_listed = asyncio.Event()

    async def reconcile(request):
        pytest.fail("workers must not start")

    original = cluster.handle

    async def handle(request):
        if request.url.path.endswith("/secrets"):
            primary_listed.set()
        return await original(request)

    cluster.config.async_client._transport = httpx.MockTransport(handle)
    controller = Controller(ConfigMap, reconcile, config=cluster.config).owns(Secret)
    task = asyncio.create_task(controller.run())
    await wait(primary_listed.wait())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(stream.closed for stream in cluster.streams)


@pytest.mark.parametrize("cancel", [False, True])
async def test_shutdown_drains_or_cancels_inflight_workers(cluster, cancel):
    cluster.items["configmaps"] = [cm()]
    entered, release, exited = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def reconcile(request):
        entered.set()
        try:
            await release.wait()
        finally:
            exited.set()

    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    stop = asyncio.Event()
    task = asyncio.create_task(controller.run(stop=stop))
    await wait(entered.wait())
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait(task)
    else:
        stop.set()
        await asyncio.sleep(0)
        assert not exited.is_set()
        release.set()
        await wait(task)
    assert exited.is_set() and not controller._queue._processing


async def test_shutdown_timeout_cancels_stuck_reconcile(cluster):
    cluster.items["configmaps"] = [cm()]
    entered, exited = asyncio.Event(), asyncio.Event()

    async def reconcile(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    controller = Controller(ConfigMap, reconcile, config=cluster.config, shutdown_timeout=0.01)
    async with running(controller):
        await wait(entered.wait())
    assert exited.is_set()


async def test_manager_failure_cancels_siblings_and_closes_watches(cluster):
    cluster.items["configmaps"] = [cm()]
    entered, exited = asyncio.Event(), asyncio.Event()

    async def reconcile(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    async def fail(request):
        pass

    first = Controller(ConfigMap, reconcile, config=cluster.config)
    second = Controller(Secret, fail, config=cluster.config)

    async def broken_sync():
        await entered.wait()
        raise ValueError("second controller failed")

    second._sync = broken_sync
    with pytest.raises(ExceptionGroup, match="TaskGroup"):
        await wait(Manager(first, second).run())
    assert exited.is_set() and all(stream.closed for stream in cluster.streams)


async def test_runtime_configuration_validation_and_single_use(cluster):
    async def reconcile(request):
        pass

    for kwargs in (
        {"workers": 0},
        {"workers": True},
        {"shutdown_timeout": -1},
        {"reconcile_timeout": float("nan")},
    ):
        with pytest.raises(ValueError):
            Controller(ConfigMap, reconcile, **kwargs)
    for delay in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            Result(delay)
    controller = Controller(ConfigMap, reconcile, config=cluster.config)
    async with running(controller):
        with pytest.raises(RuntimeError):
            controller.owns(Secret)
    with pytest.raises(RuntimeError):
        await controller.run()
    with pytest.raises(ValueError):
        Manager(controller, controller)


async def test_workers_run_distinct_keys_concurrently_and_coalesce_busy_key(cluster):
    cluster.items["configmaps"] = [cm("a"), cm("b")]
    entered = set()
    both_entered, release = asyncio.Event(), asyncio.Event()
    active = set()
    calls = []

    async def reconcile(request):
        assert request.key not in active
        active.add(request.key)
        try:
            calls.append(request.name)
            entered.add(request.name)
            if entered == {"a", "b"}:
                both_entered.set()
            await release.wait()
        finally:
            active.remove(request.key)

    controller = Controller(ConfigMap, reconcile, config=cluster.config, workers=2)
    async with running(controller):
        await wait(both_entered.wait())
        for _ in range(100):
            controller.enqueue(ResourceKey("a", "ns"))
        release.set()
        await wait(controller._queue.join())
        assert calls.count("a") == 2 and calls.count("b") == 1


async def test_reconcile_timeout_releases_key_for_retry(cluster):
    cluster.items["configmaps"] = [cm()]
    attempts = 0
    finished = asyncio.Event()

    async def reconcile(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.Event().wait()
        finished.set()

    controller = Controller(ConfigMap, reconcile, config=cluster.config, reconcile_timeout=0.01)
    controller._queue = WorkQueue(base_delay=0.001, max_delay=0.01)
    async with running(controller):
        await wait(finished.wait())
        await wait(controller._queue.join())
        assert attempts == 2


async def test_sync_timeout_closes_watches_and_reports_failure(cluster):
    cluster.gates["secrets"] = asyncio.Event()

    async def reconcile(request):
        pytest.fail("must not start")

    controller = Controller(ConfigMap, reconcile, config=cluster.config, sync_timeout=0.01).owns(
        Secret
    )
    task = asyncio.create_task(controller.run())
    with pytest.raises(TimeoutError):
        await wait(task)
    assert all(stream.closed for stream in cluster.streams)
    assert not controller.ready


async def test_primary_fatal_watch_error_aborts_secondary_startup(cluster):
    cluster.gates["secrets"] = asyncio.Event()
    secondary_started = asyncio.Event()
    original = cluster.handle

    async def handle(request):
        if request.url.path.endswith("/secrets"):
            secondary_started.set()
        return await original(request)

    cluster.config.async_client._transport = httpx.MockTransport(handle)

    async def reconcile(request):
        pytest.fail("must not reconcile")

    controller = Controller(ConfigMap, reconcile, config=cluster.config).owns(Secret)
    task = asyncio.create_task(controller.run())
    await wait(secondary_started.wait())
    cluster.events["configmaps"].put_nowait(
        {"type": "ERROR", "object": {"code": 403, "message": "access revoked"}}
    )
    with pytest.raises(APIError, match="access revoked"):
        await wait(task)
    assert all(stream.closed for stream in cluster.streams)


class Widget(Resource):
    api_version: Literal["example.com/v1"] = "example.com/v1"
    kind: Literal["Widget"] = "Widget"
    spec: dict[str, str]


async def test_custom_resource_controller_and_owner_version_mapping(cluster):
    widget = Widget(
        metadata={"name": "sample", "namespace": "ns", "uid": "widget", "resourceVersion": "1"},
        spec={"message": "custom"},
    )
    cluster.config._rest_mapping[Widget.gvk()] = {
        "resource": "widgets",
        "namespaced": True,
        "subresources": [],
    }
    original = cluster.handle

    async def handle(request):
        if request.url.path != "/apis/example.com/v1/namespaces/ns/widgets":
            return await original(request)
        if request.url.params.get("watch") == "true":
            stream = EventStream(cluster.events["widgets"])
            cluster.streams.append(stream)
            return httpx.Response(200, stream=stream)
        return httpx.Response(
            200,
            json={
                "apiVersion": "example.com/v1",
                "kind": "WidgetList",
                "metadata": {"resourceVersion": "1"},
                "items": [widget.model_dump(by_alias=True)],
            },
        )

    cluster.config.async_client._transport = httpx.MockTransport(handle)
    calls = asyncio.Queue()

    async def reconcile(request: Request[Widget]):
        assert isinstance(request.resource, Widget)
        calls.put_nowait(request.resource.spec)

    controller = Controller(Widget, reconcile, config=cluster.config).owns(Secret)
    async with running(controller):
        assert await wait(calls.get()) == {"message": "custom"}
        child = Secret(
            metadata={
                "name": "child",
                "namespace": "ns",
                "ownerReferences": [
                    {
                        "apiVersion": "example.com/v2",
                        "kind": "Widget",
                        "name": "sample",
                        "uid": "widget",
                        "controller": True,
                    }
                ],
            }
        )
        cluster.emit("secrets", "ADDED", child)
        assert await wait(calls.get()) == {"message": "custom"}


async def test_manager_shares_identical_watches_and_fans_out_initial_state(cluster):
    cluster.items["configmaps"] = [cm()]
    calls = [asyncio.Queue(), asyncio.Queue()]

    async def first(request):
        calls[0].put_nowait(request)

    async def second(request):
        calls[1].put_nowait(request)

    a = Controller(ConfigMap, first, namespace="ns").owns(Secret)
    b = Controller(ConfigMap, second).owns(Secret)
    manager = Manager(a, b, config=cluster.config)
    async with running(manager):
        assert manager.informer_count == 2
        assert a._primary is b._primary
        for queue in calls:
            assert (await wait(queue.get())).name == "a"
        cluster.emit("configmaps", "MODIFIED", cm(rv="2"))
        for queue in calls:
            assert (await wait(queue.get())).resource.resource_version == "2"
        assert len(cluster.streams) == 2
    assert all(stream.closed for stream in cluster.streams)


async def test_manager_keeps_distinct_selectors_and_resync_settings_separate(cluster):
    async def reconcile(request):
        pass

    manager = Manager(
        Controller(ConfigMap, reconcile, label_selector="app=a"),
        Controller(ConfigMap, reconcile, label_selector="app=b"),
        Controller(ConfigMap, reconcile, label_selector="app=a", resync_period=60),
        config=cluster.config,
    )
    async with running(manager):
        assert manager.informer_count == 3
        assert len(cluster.streams) == 3


async def test_manager_never_shares_different_configs(cluster):
    other = Cluster()
    try:

        async def reconcile(request):
            pass

        manager = Manager(
            Controller(ConfigMap, reconcile, config=cluster.config),
            Controller(ConfigMap, reconcile, config=other.config),
        )
        async with running(manager):
            assert manager.informer_count == 2
            assert len(cluster.streams) == len(other.streams) == 1
    finally:
        other.config.client.close()
        await other.config.async_client.aclose()


async def test_manager_initialization_failure_reaches_readiness_waiters(cluster):
    async def reconcile(request):
        pass

    controller = Controller(ConfigMap, reconcile, config=cluster.config)

    async def broken(config):
        raise ValueError("discovery failed")

    controller._install = broken
    manager = Manager(controller)
    task = asyncio.create_task(manager.run())
    with pytest.raises(ValueError, match="discovery failed"):
        await manager.wait_ready(2)
    with pytest.raises(ValueError, match="discovery failed"):
        await task
