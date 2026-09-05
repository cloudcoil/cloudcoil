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
    config.initialize = Mock()
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
    config.initialize = Mock()
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
