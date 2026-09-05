"""Regressions reproduced during the detailed PR review."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.caching._cached_client import AsyncCachedClient, CachedClient
from cloudcoil.caching._store import ConcurrentStore
from cloudcoil.caching._types import InformerOptions
from cloudcoil.caching._watch_manager import _AsyncWatchManager, _SyncWatchManager
from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.resources import Unstructured


def client_args():
    return dict(
        api_version="v1",
        kind=ConfigMap,
        resource="configmaps",
        subresources=[],
        default_namespace="chosen",
        namespaced=True,
    )


def test_unstructured_declared_values_and_aliases_are_live():
    class Thing(Unstructured):
        spec: dict[str, int] = Field(alias="desiredSpec")
        optional: str | None = None

    thing = Thing(apiVersion="example/v1", kind="Thing", desiredSpec={"x": 1}, nullable=None)
    thing["desiredSpec"]["x"] = 2
    assert thing["spec"] is thing.spec
    assert thing.spec == {"x": 2}
    for key in ("apiVersion", "api_version", "desiredSpec", "spec", "optional", "nullable"):
        assert key in thing
    assert thing["optional"] is None
    assert thing["nullable"] is None
    assert "missing" not in thing
    with pytest.raises(KeyError):
        thing["missing"]
    thing["metadata"] = ObjectMeta(name="before")
    thing["metadata"].name = "after"
    assert thing.name == "after"
    snapshot = thing.raw
    snapshot["desiredSpec"]["x"] = 99
    assert thing.spec["x"] == 2


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_initial_informer_list_consumes_every_page(asynchronous):
    requests = []

    def handler(request):
        requests.append(request)
        second = request.url.params.get("continue") == "next"
        return httpx.Response(
            200,
            json={
                "apiVersion": "v1",
                "kind": "ConfigMapList",
                "metadata": {"resourceVersion": "42", "continue": "" if second else "next"},
                "items": [
                    {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": "second" if second else "first",
                            "namespace": "chosen",
                        },
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    callback = AsyncMock() if asynchronous else Mock()
    if asynchronous:
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as http:
            manager = _AsyncWatchManager(
                AsyncAPIClient(client=http, **client_args()),
                InformerOptions(),
                callback,
                AsyncMock(),
            )
            await manager._initial_list()
    else:
        with httpx.Client(transport=transport, base_url="https://test") as http:
            manager = _SyncWatchManager(
                APIClient(client=http, **client_args()), InformerOptions(), callback, Mock()
            )
            manager._initial_list()
    items, version = callback.call_args.args
    assert [item.name for item in items] == ["first", "second"]
    assert version == "42"
    assert len(requests) == 2


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_cached_namespace_and_server_continuation(asynchronous):
    informer = Mock()
    informer.list.return_value = []
    http = Mock()
    client = (AsyncCachedClient if asynchronous else CachedClient)(
        client=http, informer=informer, strict=True, **client_args()
    )

    async def invoke(method, *args, **kwargs):
        result = method(*args, **kwargs)
        return await result if asynchronous else result

    await invoke(client.get, "sample")
    informer.get.assert_called_with("sample", "chosen")
    await invoke(client.list)
    assert informer.list.call_args.kwargs["namespace"] == "chosen"
    await invoke(client.list, namespace="other", all_namespaces=True)
    assert informer.list.call_args.kwargs["namespace"] is None
    with pytest.raises(ValueError, match="continuation"):
        await invoke(client.list, continue_="server-token")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_store_read_cannot_observe_partially_replaced_snapshot(asynchronous):
    store = ConcurrentStore()
    entered, release = threading.Event(), threading.Event()

    def index(obj):
        if obj.name == "new":
            entered.set()
            assert release.wait(2)
        return "all"

    store.add_index("group", index)
    store.add(ConfigMap(metadata=ObjectMeta(name="old")))
    replacement = ConfigMap(metadata=ObjectMeta(name="new"))
    with ThreadPoolExecutor() as pool:
        writer = pool.submit(
            lambda: (
                asyncio.run(store.async_replace([replacement]))
                if asynchronous
                else store.replace([replacement])
            )
        )
        assert entered.wait(2)
        timer = threading.Timer(0.05, release.set)
        timer.start()
        try:
            assert store.get_by_index("group", "all") == [replacement]
        finally:
            release.set()
            timer.join()
        writer.result()


@pytest.mark.parametrize("outcome", ["match", "error", "timeout"])
async def test_async_wait_closes_watch_on_every_exit(outcome):
    resource = ConfigMap(metadata=ObjectMeta(name="sample"))
    closed = []

    async def stream(**kwargs):
        try:
            yield "ADDED", resource
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    client = AsyncAPIClient(client=Mock(), **client_args())
    client.watch = stream

    def predicate(event, obj):
        if outcome == "error":
            raise ValueError("predicate failed")
        return outcome == "match"

    if outcome == "match":
        assert await client.wait_for(resource, {"ready": predicate}) == "ready"
    else:
        from cloudcoil.errors import WaitTimeout

        with pytest.raises(ValueError if outcome == "error" else WaitTimeout):
            await client.wait_for(resource, {"ready": predicate}, timeout=0.02)
    assert closed == [True]


async def test_cache_sync_exceptions_do_not_report_success():
    from cloudcoil.caching import Cache
    from cloudcoil.caching._informer import AsyncInformer

    cache = Cache(enabled=True)
    informer = AsyncInformer(Mock(kind=ConfigMap), InformerOptions())
    informer._wait_for_sync = AsyncMock(side_effect=ValueError("broken sync"))
    cache._async_informers["test"] = informer
    assert await cache.async_wait(timeout=0.1) is False


def test_generated_lookup_rejects_duplicate_resource_identity(tmp_path):
    from cloudcoil.codegen.typing import generate_lookup

    for module in ("first", "second"):
        (tmp_path / f"{module}.py").write_text(
            'class Thing(Resource):\n    api_version: str = "example/v1"\n    kind: str = "Thing"\n'
        )
    with pytest.raises(ValueError, match="Duplicate resource identity"):
        generate_lookup(tmp_path, "example")
    assert not (tmp_path / "_lookup.py").exists()


def test_nullable_composition_and_dependency_literal_refs():
    from cloudcoil.codegen.schema import normalize_definition, rewrite_refs

    schema = {"nullable": True, "allOf": [{"$ref": "#/definitions/Thing"}]}
    normalize_definition(schema)
    assert schema == {"anyOf": [{"allOf": [{"$ref": "#/definitions/Thing"}]}, {"type": "null"}]}
    schema = {"dependentSchemas": {"default": {"$ref": "#/definitions/Thing"}}}
    assert (
        rewrite_refs(schema, {"#/definitions/Thing": "#/definitions/Renamed"})["dependentSchemas"][
            "default"
        ]["$ref"]
        == "#/definitions/Renamed"
    )
