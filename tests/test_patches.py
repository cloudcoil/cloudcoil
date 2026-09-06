import json

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Pod

from cloudcoil import patches
from cloudcoil.client import Config
from cloudcoil.controller import TerminalError, ensure_finalizer, mutate, remove_finalizer
from cloudcoil.errors import APIError, ResourceConflict


@pytest.mark.parametrize(
    "before,after,expected",
    [
        (
            {"a/b": {"~x": 1}},
            {"a/b": {"~x": 2}},
            [{"op": "replace", "path": "/a~1b/~0x", "value": 2}],
        ),
        (
            {"old": 1},
            {"new": None},
            [{"op": "add", "path": "/new", "value": None}, {"op": "remove", "path": "/old"}],
        ),
        ({"items": [1, 2]}, {"items": [2]}, [{"op": "replace", "path": "/items", "value": [2]}]),
        ({"value": True}, {"value": 1}, [{"op": "replace", "path": "/value", "value": 1}]),
        ({"value": [True]}, {"value": [1]}, [{"op": "replace", "path": "/value", "value": [1]}]),
        ([1], None, [{"op": "replace", "path": "", "value": None}]),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, []),
    ],
)
def test_json_patch_values_and_pointer_escaping(before, after, expected):
    assert patches.json_patch(before, after) == expected


def cm():
    return ConfigMap(
        metadata={"name": "settings", "namespace": "ns", "uid": "uid", "resourceVersion": "7"},
        data={"value": "old"},
    )


def test_resource_diff_preconditions_noop_and_field_removal():
    before = cm()
    after = before.model_copy(deep=True)
    after.data = None
    assert patches.diff(before, after) == [
        {"op": "test", "path": "/metadata/uid", "value": "uid"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "7"},
        {"op": "remove", "path": "/data"},
    ]
    assert patches.diff(before, before.model_copy(deep=True)) == []
    assert before.data == {"value": "old"}


@pytest.mark.parametrize(
    "field,value",
    [("name", "other"), ("namespace", "elsewhere"), ("uid", "other"), ("resource_version", "8")],
)
def test_diff_refuses_identity_or_version_change(field, value):
    before, after = cm(), cm()
    setattr(after.metadata, field, value)
    with pytest.raises(ValueError):
        patches.diff(before, after)


def test_patch_values_are_independent_and_invalid_numbers_rejected():
    desired = {"nested": {"items": []}}
    patch = patches.json_patch({}, desired)
    desired["nested"]["items"].append("later")
    assert patch[0]["value"] == {"items": []}
    with pytest.raises(ValueError):
        patches.json_patch({}, {"value": float("nan")})
    with pytest.raises(ValueError):
        patches.diff(ConfigMap(metadata={"name": "draft"}), ConfigMap(metadata={"name": "draft"}))


@pytest.fixture
async def config():
    config = Config(server="https://cluster", namespace="ns")
    config.client._mounts.clear()
    config.async_client._mounts.clear()
    for kind, plural in ((ConfigMap, "configmaps"), (Pod, "pods")):
        config._rest_mapping[kind.gvk()] = {
            "resource": plural,
            "namespaced": True,
            "subresources": ["status"] if kind is Pod else [],
        }
    yield config
    config.client.close()
    await config.async_client.aclose()


def install(config, handler):
    config.client._transport = httpx.MockTransport(handler)
    config.async_client._transport = httpx.MockTransport(handler)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status", [False, True])
async def test_resource_patch_protocol_and_dry_run(config, asynchronous, status):
    obj = Pod(metadata={"name": "settings", "namespace": "ns"}) if status else cm()
    operations = [
        {"op": "add", "path": "/metadata/annotations", "value": {"example.com/note": "x"}}
    ]

    def handler(request):
        expected = (
            "/api/v1/namespaces/ns/pods/settings/status"
            if status
            else "/api/v1/namespaces/ns/configmaps/settings"
        )
        assert request.method == "PATCH" and request.url.path == expected
        assert request.url.params["dryRun"] == "All"
        assert request.headers["content-type"] == "application/json-patch+json"
        assert json.loads(request.content) == operations
        return httpx.Response(200, json=obj.model_dump(by_alias=True, exclude_none=True))

    install(config, handler)
    kwargs = {"subresource": "status" if status else None, "dry_run": True}
    async with config:
        result = (
            await obj.async_patch(operations, **kwargs)
            if asynchronous
            else obj.patch(operations, **kwargs)
        )
    assert type(result) is type(obj)


@pytest.mark.parametrize("status", [403, 409, 422])
async def test_patch_errors_propagate(config, status):
    install(config, lambda request: httpx.Response(status, json={"message": "failed"}))
    async with config:
        with pytest.raises(APIError) as caught:
            await cm().async_patch([])
    assert caught.value.status_code == status


async def test_mutate_reads_live_preserves_other_fields_and_skips_noop(config):
    current = cm()
    current.metadata.resource_version = "9"
    current.data["other"] = "preserved"
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "PATCH":
            assert json.loads(request.content) == [
                {"op": "test", "path": "/metadata/uid", "value": "uid"},
                {"op": "test", "path": "/metadata/resourceVersion", "value": "9"},
                {"op": "replace", "path": "/data/value", "value": "new"},
            ]
            current.data["value"] = "new"
        return httpx.Response(200, json=current.model_dump(by_alias=True, exclude_none=True))

    install(config, handler)

    def change(obj):
        obj.data["value"] = "new"

    result = await mutate(cm(), change, config=config)
    assert result.data == {"value": "new", "other": "preserved"}
    await mutate(cm(), change, config=config)
    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]


async def test_mutate_rejects_recreated_resource_before_callback(config):
    replacement = cm()
    replacement.metadata.uid = "new uid"
    install(
        config,
        lambda request: httpx.Response(
            200, json=replacement.model_dump(by_alias=True, exclude_none=True)
        ),
    )
    with pytest.raises(ResourceConflict):
        await mutate(cm(), lambda obj: pytest.fail("must not edit replacement"), config=config)


async def test_finalizers_preserve_other_controllers_and_are_idempotent(config):
    current = cm()
    current.metadata.finalizers = ["other.io/cleanup"]
    operations = []

    def handler(request):
        if request.method == "PATCH":
            patch = json.loads(request.content)
            operations.append(patch)
            assert patch[-1]["path"] == "/metadata/finalizers"
            current.metadata.finalizers = patch[-1]["value"]
        return httpx.Response(200, json=current.model_dump(by_alias=True, exclude_none=True))

    install(config, handler)
    await ensure_finalizer(cm(), "example.io/cleanup", config=config)
    await ensure_finalizer(cm(), "example.io/cleanup", config=config)
    assert current.metadata.finalizers == ["other.io/cleanup", "example.io/cleanup"]
    await remove_finalizer(cm(), "example.io/cleanup", config=config)
    await remove_finalizer(cm(), "example.io/cleanup", config=config)
    assert current.metadata.finalizers == ["other.io/cleanup"]
    assert len(operations) == 2


async def test_finalizer_cannot_be_added_after_deletion_starts(config):
    current = cm()
    current.metadata.deletion_timestamp = "2026-09-06T00:00:00Z"

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(
            200, json=current.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    install(config, handler)
    with pytest.raises(TerminalError):
        await ensure_finalizer(cm(), "example.io/cleanup", config=config)


async def test_status_mutations_cannot_accidentally_change_spec(config):
    install(
        config,
        lambda request: httpx.Response(200, json=cm().model_dump(by_alias=True, exclude_none=True)),
    )

    def change(obj):
        obj.data["value"] = "new"

    with pytest.raises(ValueError, match="only change status"):
        await mutate(cm(), change, config=config, status=True)
    async with config:
        with pytest.raises(ValueError, match="subresource"):
            await cm().async_patch([], subresource="status")
