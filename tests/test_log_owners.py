"""Ownership fallback across arbitrary resources and Kubernetes controller chains."""

import asyncio
from collections import Counter

import httpx
import pytest

from cloudcoil import logs
from cloudcoil.client import Config
from cloudcoil.errors import APIError, ResourceNotFound
from cloudcoil.resources import GVK, Unstructured


def resource(kind, name, uid, owners=(), namespace="jobs", api_version="operator.io/v1"):
    metadata = {"name": name, "uid": uid, "ownerReferences": list(owners)}
    if namespace is not None:
        metadata["namespace"] = namespace
    data = {"apiVersion": api_version, "kind": kind, "metadata": metadata}
    if kind == "Pod":
        data["spec"] = {"containers": [{"name": "app"}]}
    return data


def owner(data):
    return {
        "apiVersion": data["apiVersion"],
        "kind": data["kind"],
        "name": data["metadata"]["name"],
        "uid": data["metadata"]["uid"],
    }


@pytest.fixture
async def config():
    result = Config(server="https://test", namespace="jobs")
    result.client._mounts.clear()
    result.async_client._mounts.clear()
    yield result
    result.client.close()
    await result.async_client.aclose()


def transport(config, handler, asynchronous):
    config.client._transport = httpx.MockTransport(
        (lambda _: pytest.fail("blocking I/O in async traversal")) if asynchronous else handler
    )
    config.async_client._transport = httpx.MockTransport(handler)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["Database", "CronJob"])
async def test_transitive_owners_pagination_and_combined_stream(config, asynchronous, kind):
    target = resource(
        kind,
        "database",
        "target",
        api_version="batch/v1" if kind == "CronJob" else "operator.io/v1",
    )
    parent = resource("Mouse", "mouse", "mouse-uid", [owner(target)])
    # The owner's served version may differ from the target object's version.
    if kind == "Database":
        parent["metadata"]["ownerReferences"][0]["apiVersion"] = "operator.io/v2"
    rs = resource("ReplicaSet", "workers", "rs-uid", [owner(parent)], api_version="apps/v1")
    pods = [
        resource("Pod", name, f"uid-{name}", [owner(rs)], api_version="v1")
        for name in ("first", "second")
    ]
    unrelated = resource("Pod", "unrelated", "unrelated", api_version="v1")
    stale = resource("Pod", "stale", "stale", [{**owner(rs), "uid": "old-rs"}], api_version="v1")
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/cronjobs/database"):
            return httpx.Response(200, json=target)
        if path == "/api/v1/namespaces/jobs/pods":
            assert "labelSelector" not in request.url.params
            second = "continue" in request.url.params
            return httpx.Response(
                200,
                json={
                    "metadata": {"continue": "" if second else "next"},
                    "items": [pods[1], stale] if second else [pods[0], unrelated],
                },
            )
        if path in ("/apis/apps/v1", "/apis/operator.io/v1"):
            assert "PartialObjectMetadata" not in request.headers.get("accept", "")
            return httpx.Response(
                200,
                json={
                    "resources": [
                        {
                            "kind": "ReplicaSet" if path.endswith("apps/v1") else "Mouse",
                            "name": "replicasets" if path.endswith("apps/v1") else "mice",
                            "namespaced": True,
                        }
                    ]
                },
            )
        if path in (
            "/apis/apps/v1/namespaces/jobs/replicasets/workers",
            "/apis/operator.io/v1/namespaces/jobs/mice/mouse",
        ):
            assert "PartialObjectMetadata" in request.headers["accept"]
            return httpx.Response(200, json=rs if "/replicasets/" in path else parent)
        assert path.endswith(("/pods/first/log", "/pods/second/log")), path
        return httpx.Response(200, text="owned\n")

    transport(config, handler, asynchronous)
    target_arg = "cronjob/database" if kind == "CronJob" else Unstructured.model_validate(target)
    sources = (
        [s async for s in logs.async_discover(target_arg, config=config, page_size=2)]
        if asynchronous
        else list(logs.discover(target_arg, config=config, page_size=2))
    )
    assert {source.pod for source in sources} == {"first", "second"}
    counts = Counter(request.url.path for request in requests)
    assert counts["/apis/apps/v1/namespaces/jobs/replicasets/workers"] == 1
    assert counts["/apis/operator.io/v1/namespaces/jobs/mice/mouse"] == 1
    assert counts["/apis/apps/v1"] == counts["/apis/operator.io/v1"] == 1
    # Both the simple and combined APIs reuse the same ancestry selection.
    if asynchronous:
        assert await logs.async_read(target_arg, config=config) == "owned\n"
        async with logs.async_stream(
            target_arg, config=config, all_pods=True, follow=False
        ) as records:
            assert {record.pod async for record in records} == {"first", "second"}
    else:
        assert logs.read(target_arg, config=config) == "owned\n"
        with logs.stream(target_arg, config=config, follow=False) as records:
            assert next(records).pod == "first"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "case", ["deleted", "recreated", "cycle", "forbidden", "discovery_forbidden"]
)
async def test_broken_or_unreadable_owner_chains(config, asynchronous, case):
    target = resource("Database", "database", "target-new")
    old = {**owner(target), "uid": "target-old"}
    first = resource("Mouse", "first", "first", [old])
    second = resource("Mouse", "second", "second", [owner(first)])
    if case == "cycle":
        first["metadata"]["ownerReferences"] = [owner(second)]
    pod = resource("Pod", "worker", "pod", [owner(first)], api_version="v1")
    fetched = []

    def handler(request):
        path = request.url.path
        fetched.append(path)
        if path.endswith("/pods"):
            return httpx.Response(200, json={"items": [pod]})
        if path == "/apis/operator.io/v1":
            if case == "discovery_forbidden":
                return httpx.Response(403, json={"message": "discovery forbidden"})
            return httpx.Response(
                200,
                json={
                    "resources": [
                        {"kind": "Mouse", "name": "mice", "namespaced": True},
                        {"kind": "Database", "name": "databases", "namespaced": True},
                    ]
                },
            )
        if path.endswith("/mice/first"):
            if case in ("deleted", "forbidden"):
                return httpx.Response(
                    404 if case == "deleted" else 403, json={"message": "owner forbidden or gone"}
                )
            return httpx.Response(200, json=first)
        if path.endswith("/mice/second"):
            return httpx.Response(200, json=second)
        assert path.endswith("/databases/database"), path
        return httpx.Response(200, json=target)  # Same name, different UID must not match.

    transport(config, handler, asynchronous)
    custom = Unstructured.model_validate(target)

    async def discover():
        return (
            [s async for s in logs.async_discover(custom, config=config)]
            if asynchronous
            else list(logs.discover(custom, config=config))
        )

    async with asyncio.timeout(2):
        if "forbidden" in case:
            with pytest.raises(APIError) as exc:
                await discover()
            assert exc.value.status_code == 403
        else:
            assert await discover() == []
            assert max(Counter(fetched).values()) == 1
            if asynchronous:
                with pytest.raises(ResourceNotFound, match="No matching Pods"):
                    await logs.async_read(custom, config=config)
            else:
                with pytest.raises(ResourceNotFound, match="No matching Pods"):
                    logs.read(custom, config=config)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("name", ["database", "system:database"])
async def test_direct_ownership_and_selector_override_skip_ancestor_io(config, asynchronous, name):
    target = resource("Database", name, "target")
    pod = resource("Pod", "worker", "pod", [owner(target)], api_version="v1")
    params = []

    def handler(request):
        assert request.url.path == "/api/v1/namespaces/jobs/pods"
        params.append(dict(request.url.params))
        return httpx.Response(200, json={"items": [pod]})

    transport(config, handler, asynchronous)
    for extra in ({}, {"label_selector": "operator.io/database=database"}):
        custom = Unstructured.model_validate(target)
        result = (
            [s async for s in logs.async_discover(custom, config=config, **extra)]
            if asynchronous
            else list(logs.discover(custom, config=config, **extra))
        )
        assert len(result) == 1
    assert "labelSelector" not in params[0]
    assert params[1]["labelSelector"] == "operator.io/database=database"


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_cluster_scoped_owner_and_cached_rest_mapping(config, asynchronous):
    target = resource("Fleet", "fleet", "fleet", namespace=None)
    parent = resource("Pool", "pool", "pool", [owner(target)], namespace=None)
    pod = resource("Pod", "worker", "pod", [owner(parent)], api_version="v1")
    config._rest_mapping[GVK(api_version="operator.io/v1", kind="Pool")] = {
        "resource": "pools",
        "namespaced": False,
        "subresources": [],
    }

    def handler(request):
        if request.url.path == "/api/v1/namespaces/jobs/pods":
            return httpx.Response(200, json={"items": [pod]})
        assert request.url.path == "/apis/operator.io/v1/pools/pool"
        return httpx.Response(200, json=parent)

    transport(config, handler, asynchronous)
    custom = Unstructured.model_validate(target)
    result = (
        [s async for s in logs.async_discover(custom, config=config)]
        if asynchronous
        else list(logs.discover(custom, config=config))
    )
    assert len(result) == 1
    # A namespaced target cannot own a cluster-scoped parent through an invalid ref.
    target["metadata"]["namespace"] = "jobs"
    custom = Unstructured.model_validate(target)
    config._rest_mapping[GVK(api_version="operator.io/v1", kind="Fleet")] = {
        "resource": "fleets",
        "namespaced": True,
        "subresources": [],
    }
    result = (
        [s async for s in logs.async_discover(custom, config=config)]
        if asynchronous
        else list(logs.discover(custom, config=config))
    )
    assert result == []


async def test_cancel_during_owner_lookup(config):
    target = resource("Database", "database", "target")
    parent = resource("Mouse", "mouse", "mouse", [owner(target)])
    pod = resource("Pod", "worker", "pod", [owner(parent)], api_version="v1")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(request):
        if request.url.path.endswith("/pods"):
            return httpx.Response(200, json={"items": [pod]})
        if request.url.path == "/apis/operator.io/v1":
            return httpx.Response(
                200, json={"resources": [{"kind": "Mouse", "name": "mice", "namespaced": True}]}
            )
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    transport(config, handler, True)

    async def consume():
        return [
            s async for s in logs.async_discover(Unstructured.model_validate(target), config=config)
        ]

    task = asyncio.create_task(consume())
    async with asyncio.timeout(2):
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cancelled.is_set()
