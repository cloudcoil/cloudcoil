"""Regression tests for isolation, HTTP failures, and server pagination contracts."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil._context import context
from cloudcoil.apimachinery import APIResource, APIResourceList, ObjectMeta
from cloudcoil.client import Config
from cloudcoil.client._api_client import APIClient, AsyncAPIClient
from cloudcoil.errors import APIError, ResourceConflict, ResourceNotFound


@pytest.fixture(autouse=True)
def isolate_context():
    original = context.configs
    context.configs = None
    yield
    context.configs = original


@pytest.mark.asyncio
async def test_inherited_context_is_isolated_between_tasks():
    parent, first, second = object(), object(), object()
    context._enter(parent)
    ready = asyncio.Event()

    async def child(config):
        context._enter(config)
        ready.set()
        await asyncio.sleep(0)
        assert context.active_config is config
        context._exit(config)
        assert context.active_config is parent

    await asyncio.gather(child(first), child(second))
    assert context.configs == [parent]


def test_context_does_not_expose_mutable_stack():
    parent = object()
    values = [parent]
    context.configs = values
    values.clear()
    context.configs.clear()
    assert context.active_config is parent


def test_failed_config_start_restores_previous_context():
    parent = object()
    context._enter(parent)
    config = object.__new__(Config)
    import threading

    config._scope_lock = threading.RLock()
    config._async_scope_lock = asyncio.Lock()
    config._cache_users = 0
    config._cache_mode = None
    config.initialize = Mock()
    config.async_initialize = AsyncMock()
    config.cache = Mock(enabled=True, wait_for_sync=True, mode="strict", sync_timeout=1)
    config.cache.wait.return_value = False
    with pytest.raises(APIError):
        with config:
            pytest.fail("Must not enter failed scope")
    assert context.active_config is parent
    config.cache.stop.assert_called_once()


@pytest.mark.asyncio
async def test_failed_async_config_cleanup_restores_context():
    parent = object()
    context._enter(parent)
    config = object.__new__(Config)
    import threading

    config._scope_lock = threading.RLock()
    config._async_scope_lock = asyncio.Lock()
    config._cache_users = 0
    config._cache_mode = None
    config.initialize = Mock()
    config.async_initialize = AsyncMock()
    config.cache = Mock(enabled=True, wait_for_sync=False)
    config.cache.async_start = AsyncMock()
    config.cache.async_stop = AsyncMock(side_effect=RuntimeError("cleanup"))
    with pytest.raises(RuntimeError, match="cleanup"):
        async with config:
            assert context.active_config is config
    assert context.active_config is parent


def test_builder_exception_does_not_mask_error_or_commit_partial_object():
    with APIResourceList.new() as builder:
        builder.group_version("v1")
        with pytest.raises(RuntimeError, match="original"):
            with builder.resources() as resources:
                with resources.add() as resource:
                    resource.name("pods")
                    raise RuntimeError("original")
        assert "resources" not in builder._attrs


def test_list_builder_result_is_not_shared_storage():
    resource = APIResource(name="pods", kind="Pod", namespaced=True, singular_name="pod", verbs=[])
    builder = APIResource.list_builder().add(resource)
    builder.build().clear()
    assert builder.build() == [resource]


def client_for(handler, async_=False):
    transport = httpx.MockTransport(handler)
    cls, http_cls = (AsyncAPIClient, httpx.AsyncClient) if async_ else (APIClient, httpx.Client)
    return cls(
        "v1",
        ConfigMap,
        "configmaps",
        ["status"],
        "default",
        True,
        http_cls(base_url="https://cluster.test", transport=transport),
    )


@pytest.mark.parametrize(
    "status,error",
    [(403, APIError), (404, ResourceNotFound), (409, ResourceConflict), (500, APIError)],
)
@pytest.mark.parametrize("method", ["get", "delete", "list"])
def test_http_errors_are_not_model_validation_errors(status, error, method):
    client = client_for(lambda _: httpx.Response(status, text="upstream failure"))
    with pytest.raises(error) as exc:
        getattr(client, method)(*(["sample"] if method != "list" else []))
    assert exc.value.status_code == status
    assert "upstream failure" in str(exc.value)


@pytest.mark.asyncio
async def test_async_error_mapping():
    client = client_for(lambda _: httpx.Response(409, json={"message": "conflict"}), async_=True)
    with pytest.raises(ResourceConflict, match="conflict"):
        await client.create(ConfigMap(metadata=ObjectMeta(name="sample")))


def test_zero_grace_period_is_sent():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"apiVersion": "v1", "kind": "Status", "status": "Success"})

    client_for(handler).delete("sample", grace_period_seconds=0)
    assert requests[0].url.params["gracePeriodSeconds"] == "0"


@pytest.mark.parametrize("method", ["update", "update_status"])
def test_unnamed_updates_never_target_collection(method):
    client = client_for(lambda _: pytest.fail("Must not make a request"))
    with pytest.raises(ValueError, match="metadata.name"):
        getattr(client, method)(ConfigMap(metadata=ObjectMeta()))


def page_handler(request):
    token = request.url.params.get("continue")
    assert request.url.params["labelSelector"] == "app=test"
    return httpx.Response(
        200,
        json={
            "apiVersion": "v1",
            "kind": "ConfigMapList",
            "metadata": {"continue": "" if token else "next"},
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "two" if token else "one"},
                }
            ],
        },
    )


def test_pagination_uses_continue_without_remaining_count_and_original_client():
    result = client_for(page_handler).list(label_selector="app=test")
    context._enter(object())  # A different active config must never affect the next page.
    assert [item.name for item in result] == ["one", "two"]
    last = result.get_next_page()
    with pytest.raises(ValueError, match="no next page"):
        last.get_next_page()


@pytest.mark.asyncio
async def test_async_pagination_keeps_client_and_selectors():
    result = await client_for(page_handler, async_=True).list(label_selector="app=test")
    context._enter(object())
    assert [item.name async for item in result] == ["one", "two"]


def test_tls_settings_are_not_shared_between_configs(monkeypatch):
    import ssl

    import cloudcoil.client._config as config_module

    contexts = []

    def client(**kwargs):
        contexts.append(kwargs["verify"])
        return Mock()

    monkeypatch.setattr(config_module.httpx, "Client", client)
    monkeypatch.setattr(config_module.httpx, "AsyncClient", client)
    Config(skip_verify=True)
    Config()
    assert contexts[0].verify_mode == ssl.CERT_NONE
    assert contexts[2].verify_mode == ssl.CERT_REQUIRED
    assert contexts[2].check_hostname is True
    assert contexts[0] is not contexts[2]


def test_clone_preserves_selected_kubeconfig_context_and_overrides(tmp_path, monkeypatch):
    import yaml

    import cloudcoil.client._config as config_module

    monkeypatch.setattr(config_module.httpx, "Client", Mock())
    monkeypatch.setattr(config_module.httpx, "AsyncClient", Mock())
    source = tmp_path / "config"
    source.write_text(
        yaml.safe_dump(
            {
                "current-context": "first",
                "clusters": [
                    {
                        "name": name,
                        "cluster": {
                            "server": f"https://{name}.test",
                            "insecure-skip-tls-verify": True,
                        },
                    }
                    for name in ("first", "second")
                ],
                "users": [{"name": "user", "user": {"token": "test-token"}}],
                "contexts": [
                    {
                        "name": name,
                        "context": {"cluster": name, "user": "user", "namespace": "from-file"},
                    }
                    for name in ("first", "second")
                ],
            }
        )
    )
    config = Config(kubeconfig=source, context="second", namespace="custom", skip_verify=False)
    clone = config.clone()
    assert clone.server == "https://second.test"
    assert clone.namespace == "custom"
    assert clone.skip_verify is False
    assert clone.cache is not config.cache
    assert config.clone(context="first").server == "https://first.test"


def test_unstructured_mapping_and_attributes_share_one_source_of_truth():
    from cloudcoil.resources import Unstructured

    resource = Unstructured(apiVersion="example.com/v1", kind="Thing", metadata={"name": "before"})
    resource.name = "after"
    assert resource["metadata"]["name"] == "after"
    resource["apiVersion"] = "example.com/v2"
    assert resource.api_version == "example.com/v2"
    assert resource.raw["apiVersion"] == "example.com/v2"
    resource["spec"] = {"value": 42}
    assert resource.spec == {"value": 42}
    resource["spec"]["value"] = 43
    assert resource.spec == {"value": 43}
    resource["spec"]["value"] = 42
    assert resource.model_dump(by_alias=True)["spec"] == {"value": 42}


def test_save_carries_resource_version_without_mutating_caller():
    requests = []

    def handler(request):
        import json

        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "sample", "resourceVersion": "42"},
                },
            )
        data = json.loads(request.content)
        assert data["metadata"]["resourceVersion"] == "42"
        return httpx.Response(200, json=data)

    client = client_for(handler)
    config = Mock()
    config.client_for.return_value = client
    context._enter(config)
    resource = ConfigMap(metadata=ObjectMeta(name="sample"))
    assert resource.save().resource_version == "42"
    assert resource.resource_version is None
    assert [request.method for request in requests] == ["GET", "PUT"]


@pytest.mark.asyncio
async def test_async_watch_is_directly_iterable_and_closes_stream():
    closed = []

    async def watch(**kwargs):
        try:
            yield "ADDED", ConfigMap(metadata=ObjectMeta(name="sample"))
        finally:
            closed.append(True)

    config = Mock()
    config.async_client_for = AsyncMock(return_value=Mock(watch=watch))
    context._enter(config)
    stream = ConfigMap.async_watch()
    event, resource = await anext(stream)
    assert (event, resource.name) == ("ADDED", "sample")
    await stream.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_shared_cached_config_stays_running_until_last_scope_exits(monkeypatch):
    config = Config(cache=True)
    config.async_initialize = AsyncMock()
    monkeypatch.setattr(type(config.cache), "async_start", AsyncMock())
    monkeypatch.setattr(type(config.cache), "async_stop", AsyncMock())
    config.cache.wait_for_sync = False
    entered = asyncio.Event()
    release = asyncio.Event()

    async def child():
        async with config:
            entered.set()
            await release.wait()
            config.cache.async_stop.assert_not_called()

    task = asyncio.create_task(child())
    await entered.wait()
    async with config:
        assert context.active_config is config
    config.cache.async_stop.assert_not_called()
    release.set()
    await task
    config.cache.async_start.assert_called_once()
    config.cache.async_stop.assert_called_once()


def test_default_change_applies_after_implicit_access(monkeypatch):
    import cloudcoil._context as context_module

    first, second = object(), object()
    monkeypatch.setattr(context_module, "_default_config", first)
    assert context.active_config is first
    context.set_default(second)
    assert context.active_config is second


def test_caught_item_error_does_not_commit_partial_list_item():
    with APIResourceList.new() as builder:
        builder.group_version("v1")
        with builder.resources() as resources:
            with pytest.raises(RuntimeError, match="discard"):
                with resources.add() as item:
                    item.name("incomplete")
                    raise RuntimeError("discard")
            with resources.add() as item:
                item.name("pods").kind("Pod").namespaced(True).singular_name("pod").verbs([])
    assert [item.name for item in builder.build().resources] == ["pods"]
    assert not builder._in_context


@pytest.mark.parametrize("async_", [False, True])
@pytest.mark.asyncio
async def test_watch_authorization_failure_is_terminal(async_):
    client = client_for(lambda _: httpx.Response(403, json={"message": "forbidden"}), async_=async_)
    with pytest.raises(APIError) as exc:
        if async_:
            await anext(client.watch())
        else:
            next(client.watch())
    assert exc.value.status_code == 403


def test_sync_wait_predicate_inherits_active_config(monkeypatch):
    config = object()
    context._enter(config)
    resource = ConfigMap(metadata=ObjectMeta(name="sample"))
    client = client_for(lambda _: pytest.fail("No real request"))

    def watch(**kwargs):
        yield "MODIFIED", resource

    monkeypatch.setattr(client, "watch", watch)

    def predicate(event, obj):
        assert context.active_config is config
        return True

    assert client.wait_for(resource, {"ready": predicate}, timeout=1) == "ready"


def test_deep_copy_of_page_retains_transport_and_copies_data():
    page = client_for(page_handler).list(label_selector="app=test")
    copy = page.model_copy(deep=True)
    assert copy._page_client is page._page_client
    assert copy.items[0] is not page.items[0]
    assert [item.name for item in copy] == ["one", "two"]


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_informer_ready_when_initial_snapshot_wakes_waiters(asynchronous):
    from cloudcoil.caching._informer import AsyncInformer, SyncInformer
    from cloudcoil.caching._types import InformerOptions

    client = Mock(kind=ConfigMap)
    informer = (AsyncInformer if asynchronous else SyncInformer)(client, InformerOptions())
    informer._started = True
    resource = ConfigMap(metadata=ObjectMeta(name="sample", namespace="default"))
    if asynchronous:
        await informer._handle_initial_items([resource], "42")
        assert await informer._wait_for_sync(timeout=0.1)
    else:
        informer._handle_initial_items([resource], "42")
        assert informer._wait_for_sync(timeout=0.1)
    assert not informer._watch.is_running
    assert informer.has_synced()
    assert informer.list(namespace="default") == [resource]
    informer._started = False
    assert not informer.has_synced()
