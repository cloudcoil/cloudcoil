"""Admission protocol, typed mutation intent, and ASGI lifecycle behavior."""

import asyncio
import base64
import json
from copy import deepcopy
from typing import Literal

import httpx
import pytest
from pydantic import Field, field_validator

from cloudcoil.admission import AdmissionDenied, AdmissionRequest, AdmissionWebhook
from cloudcoil.admission._mutation import mutation_patch
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class Item(BaseModel):
    name: str
    value: int = 1


class Spec(BaseModel):
    replicas: int = 1
    entries: list[Item] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class Widget(Resource):
    api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
    kind: Literal["Widget"] = "Widget"
    spec: Spec = Field(default_factory=Spec)
    status: dict[str, str] | None = None


def review(operation="CREATE", *, raw=None, **kwargs):
    raw = raw or {
        "apiVersion": "example.com/v1",
        "kind": "Widget",
        "metadata": {"name": "sample", "namespace": "test"},
        "spec": {"unknown": "preserve"},
        "unmodeled": {"keep": True},
    }
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "request-uid",
            "kind": {"group": "example.com", "version": "v1", "kind": "Widget"},
            "resource": {"group": "example.com", "version": "v1", "resource": "widgets"},
            "name": "sample",
            "namespace": "test",
            "operation": operation,
            "object": raw if operation != "DELETE" else None,
            "oldObject": deepcopy(raw) if operation != "CREATE" else None,
            **kwargs,
        },
    }


async def post(app, payload, path="/mutate"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://webhook"
    ) as client:
        return await client.post(path, json=payload)


def patch(response):
    value = response.json()["response"]
    assert response.status_code == 200
    assert value["uid"] == "request-uid"
    assert value["allowed"] is True
    if "patch" not in value:
        assert "patchType" not in value
        return []
    assert value["patchType"] == "JSONPatch"
    return json.loads(base64.b64decode(value["patch"], validate=True))


def apply_patch(raw, operations):
    """Small independent RFC6902 evaluator for generated add/remove/replace operations."""
    output = deepcopy(raw)
    for operation in operations:
        parts = [
            part.replace("~1", "/").replace("~0", "~") for part in operation["path"].split("/")[1:]
        ]
        target = output
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        if operation["op"] == "remove":
            del target[key]
        else:
            if operation["op"] == "replace":
                assert key in target if isinstance(target, dict) else key < len(target)
            target[key] = deepcopy(operation["value"])
    return output


@pytest.mark.parametrize("return_copy", [False, True])
async def test_mutator_only_patches_intent_preserves_unknowns_defaults_and_raw_input(return_copy):
    app = AdmissionWebhook()
    payload = review(
        dryRun=True,
        userInfo={"username": "sam", "groups": ["developers"], "extra": {"scope": ["test"]}},
    )
    original = deepcopy(payload)

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request: AdmissionRequest[Widget]):
        assert isinstance(request.resource, Widget)
        assert request.dry_run and request.user_info.username == "sam"
        assert request.user_info.extra["scope"] == ["test"]
        assert request.old_resource is None
        request.raw_object["unmodeled"].clear()
        obj = request.resource.model_copy(deep=True) if return_copy else request.resource
        obj.spec.replicas = 3
        obj.spec.labels["a/b~c"] = "yes"
        return obj

    response = await post(app, payload)
    operations = patch(response)
    assert operations == [
        {"op": "add", "path": "/spec/labels", "value": {"a/b~c": "yes"}},
        {"op": "add", "path": "/spec/replicas", "value": 3},
    ]
    result = apply_patch(original["request"]["object"], operations)
    assert result["spec"]["unknown"] == "preserve"
    assert result["unmodeled"] == {"keep": True}
    assert "entries" not in result["spec"]
    assert payload == original
    # Reinvocation with already defaulted values is a no-op.
    assert (
        patch(
            await post(
                app, review(raw=result, dryRun=True, userInfo=original["request"]["userInfo"])
            )
        )
        == []
    )


@pytest.mark.parametrize("mode", ["unchanged", "none", "same-default"])
async def test_noops_and_explicit_default_assignment(mode):
    app = AdmissionWebhook()

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request):
        if mode == "none":
            request.resource.spec.replicas = 7
            return None
        if mode == "same-default":
            request.resource.spec.replicas = 1
        return request.resource

    operations = patch(await post(app, review()))
    assert operations == (
        [{"op": "add", "path": "/spec/replicas", "value": 1}] if mode == "same-default" else []
    )


@pytest.mark.parametrize("mode", ["edit", "append", "remove", "reverse", "ambiguous"])
async def test_list_mutation_preserves_unknown_element_fields(mode):
    app = AdmissionWebhook()
    payload = review()
    payload["request"]["object"]["spec"]["entries"] = [
        {"name": "one", "futureField": {"keep": 1}},
        {"name": "two", "futureField": {"keep": 2}},
    ]

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request):
        entries = request.resource.spec.entries
        if mode == "edit":
            entries[0].value = 2
        elif mode == "append":
            entries.append(Item(name="three", value=4))
        elif mode == "remove":
            entries.pop(0)
        elif mode == "reverse":
            entries.reverse()
        else:
            entries[0].value = 2
            entries.reverse()
        return request.resource

    response = await post(app, payload)
    result = apply_patch(payload["request"]["object"], patch(response))
    for item in result["spec"]["entries"]:
        if item["name"] != "three":
            assert item["futureField"]["keep"] == (1 if item["name"] == "one" else 2)
    if mode == "edit":
        assert result["spec"]["entries"][0]["value"] == 2
        assert "value" not in result["spec"]["entries"][1]


async def test_dictionary_removal_and_explicit_null():
    app = AdmissionWebhook()
    payload = review()
    payload["request"]["object"]["spec"]["labels"] = {"a/b~c": "old", "keep": "yes"}
    payload["request"]["object"]["status"] = {"phase": "Pending"}

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request):
        del request.resource.spec.labels["a/b~c"]
        request.resource.status = None
        return request.resource

    assert patch(await post(app, payload)) == [
        {"op": "remove", "path": "/spec/labels/a~1b~0c"},
        {"op": "replace", "path": "/status", "value": None},
    ]


@pytest.mark.parametrize("operation", ["CREATE", "UPDATE", "DELETE"])
async def test_validation_typed_old_object_and_denial(operation):
    app = AdmissionWebhook()

    @app.validating(
        Widget, resource="widgets", path="/validate", operations=("CREATE", "UPDATE", "DELETE")
    )
    async def validate(request):
        assert (request.resource is None) == (operation == "DELETE")
        assert (request.old_resource is None) == (operation == "CREATE")
        if request.old_resource:
            assert isinstance(request.old_resource, Widget)
        raise AdmissionDenied("replicas are not allowed", code=422, reason="Invalid")

    response = await post(app, review(operation), "/validate")
    assert response.status_code == 200
    assert response.json() == {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": "request-uid",
            "allowed": False,
            "status": {"code": 422, "reason": "Invalid", "message": "replicas are not allowed"},
        },
    }


async def test_validators_allow_and_status_subresource():
    app = AdmissionWebhook()

    @app.validating(
        Widget,
        resource="widgets",
        path="/validate",
        operations=("UPDATE",),
        subresource="status",
        scope="Namespaced",
    )
    async def validate(request):
        assert request.subresource == "status"
        assert request.namespace == "test"
        return None

    assert patch(await post(app, review("UPDATE", subResource="status"), "/validate")) == []
    assert (await post(app, review("UPDATE"), "/validate")).status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "kind",
        "uid",
        "resource",
        "object-kind",
        "operation",
        "subresource",
        "old-object",
        "missing-object",
        "model-validation",
        "dry-run",
    ],
)
async def test_invalid_reviews_never_call_handler(change):
    app = AdmissionWebhook()

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request):
        pytest.fail("Malformed review must not reach handler")

    payload = review()
    raw = payload["request"]
    if change == "version":
        payload["apiVersion"] = "admission.k8s.io/v1beta1"
    elif change == "kind":
        raw["kind"]["version"] = "v2"
    elif change == "uid":
        raw["uid"] = ""
    elif change == "resource":
        raw["resource"]["resource"] = "otherwidgets"
    elif change == "object-kind":
        raw["object"]["kind"] = "Secret"
    elif change == "operation":
        raw["operation"] = "CONNECT"
    elif change == "subresource":
        raw["subResource"] = "status"
    elif change == "old-object":
        raw["oldObject"] = deepcopy(raw["object"])
    elif change == "missing-object":
        raw["object"] = None
    elif change == "model-validation":
        raw["object"]["spec"]["replicas"] = "invalid"
    else:
        raw["dryRun"] = "false"
    response = await post(app, payload)
    if change == "model-validation":
        assert response.status_code == 200
        assert response.json()["response"]["allowed"] is False
        assert response.json()["response"]["status"]["code"] == 422
    else:
        assert response.status_code == 400


@pytest.mark.parametrize(
    "mode", ["exception", "return-type", "identity", "delete-return", "validator-return"]
)
async def test_programming_failures_are_http_errors_for_failure_policy(mode):
    app = AdmissionWebhook()

    async def handler(request):
        if mode == "exception":
            raise RuntimeError("secret internal detail")
        if mode == "return-type":
            return True
        if mode == "identity":
            request.resource.name = "different"
        if mode == "delete-return":
            return request.old_resource
        return request.resource

    register = app.validating if mode == "validator-return" else app.mutating
    register(Widget, resource="widgets", path="/mutate", operations=("CREATE", "DELETE"))(handler)
    response = await post(app, review("DELETE" if mode == "delete-return" else "CREATE"))
    assert response.status_code == 500
    assert response.json() == {"message": "Admission webhook failed"}


async def test_mutator_delete_none_is_noop():
    app = AdmissionWebhook()

    @app.mutating(Widget, resource="widgets", path="/mutate", operations=("DELETE",))
    async def mutate(request):
        assert request.resource is None
        return None

    assert patch(await post(app, review("DELETE"))) == []


async def test_timeout_and_external_cancellation_join_handler():
    app = AdmissionWebhook()
    entered, stopped = asyncio.Event(), asyncio.Event()

    @app.mutating(Widget, resource="widgets", path="/mutate", timeout_seconds=1)
    async def mutate(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    response = await post(app, review())
    assert response.status_code == 504
    assert stopped.is_set()
    entered.clear()
    stopped.clear()
    task = asyncio.create_task(post(app, review()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


async def test_http_transport_routes_content_types_and_body_limit():
    app = AdmissionWebhook(max_body_bytes=2048)

    @app.validating(Widget, resource="widgets", path="/mutate")
    async def validate(request):
        return None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://webhook"
    ) as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/missing")).status_code == 404
        assert (await client.get("/mutate")).status_code == 405
        assert (await client.post("/mutate", content=b"{}")).status_code == 415
        assert (
            await client.post("/mutate", content=b"{", headers={"Content-Type": "application/json"})
        ).status_code == 400
        assert (
            await client.post(
                "/mutate", content=b" " * 2049, headers={"Content-Type": "application/json"}
            )
        ).status_code == 413


async def test_asgi_lifespan_chunking_and_disconnect():
    app = AdmissionWebhook()

    @app.validating(Widget, resource="widgets", path="/mutate")
    async def validate(request):
        return None

    sent = []
    messages = asyncio.Queue()

    async def send(message):
        sent.append(message)

    messages.put_nowait({"type": "lifespan.startup"})
    messages.put_nowait({"type": "lifespan.shutdown"})
    await app({"type": "lifespan"}, messages.get, send)
    assert sent == [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]
    sent.clear()
    body = json.dumps(review()).encode()
    messages.put_nowait({"type": "http.request", "body": body[:100], "more_body": True})
    messages.put_nowait({"type": "http.request", "body": body[100:]})
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mutate",
        "headers": [(b"content-type", b"application/json; charset=utf-8")],
    }
    await app(scope, messages.get, send)
    assert sent[0]["status"] == 200
    sent.clear()
    messages.put_nowait({"type": "http.disconnect"})
    await app(scope, messages.get, send)
    assert not sent


def test_configurations_match_registered_routes_and_encode_ca_once():
    app = AdmissionWebhook()

    async def handler(request):
        return None

    app.mutating(Widget, resource="widgets", path="/mutate", scope="Namespaced", timeout_seconds=3)(
        handler
    )
    app.validating(
        Widget,
        resource="widgets",
        path="/validate-status",
        subresource="status",
        operations=("UPDATE",),
        failure_policy="Ignore",
    )(handler)
    ca = b"-----BEGIN CERTIFICATE-----\nexample\n-----END CERTIFICATE-----"
    configurations = app.configurations(
        name="widgets.example.com", service_name="webhook", service_namespace="system", ca_bundle=ca
    )
    assert [value["kind"] for value in configurations] == [
        "MutatingWebhookConfiguration",
        "ValidatingWebhookConfiguration",
    ]
    mutating, validating = [value["webhooks"][0] for value in configurations]
    assert mutating["clientConfig"]["service"] == {
        "name": "webhook",
        "namespace": "system",
        "path": "/mutate",
        "port": 443,
    }
    assert base64.b64decode(mutating["clientConfig"]["caBundle"]) == ca
    assert mutating["rules"] == [
        {
            "apiGroups": ["example.com"],
            "apiVersions": ["v1"],
            "resources": ["widgets"],
            "operations": ["CREATE", "UPDATE"],
            "scope": "Namespaced",
        }
    ]
    assert mutating["admissionReviewVersions"] == ["v1"]
    assert mutating["sideEffects"] == "None"
    assert mutating["matchPolicy"] == "Exact"
    assert mutating["timeoutSeconds"] == 3
    assert validating["failurePolicy"] == "Ignore"
    assert validating["rules"][0]["resources"] == ["widgets/status"]
    assert validating["rules"][0]["operations"] == ["UPDATE"]
    configurations[0]["webhooks"][0]["rules"].clear()
    assert app.configurations(
        name="widgets.example.com", service_name="webhook", service_namespace="system", ca_bundle=ca
    )[0]["webhooks"][0]["rules"]


@pytest.mark.parametrize(
    "options",
    [
        {"path": "bad"},
        {"path": "/healthz"},
        {"resource": "widgets/*"},
        {"subresource": "*"},
        {"operations": ("CONNECT",)},
        {"operations": ()},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"scope": "bad"},
        {"failure_policy": "bad"},
    ],
)
def test_invalid_registrations(options):
    app = AdmissionWebhook()

    async def handler(request):
        return None

    with pytest.raises(ValueError):
        app.mutating(Widget, **{"resource": "widgets", "path": "/mutate", **options})(handler)


def test_duplicate_route_rejected():
    app = AdmissionWebhook()

    async def handler(request):
        return None

    app.mutating(Widget, resource="widgets", path="/mutate")(handler)
    with pytest.raises(ValueError):
        app.validating(Widget, resource="widgets", path="/mutate")(handler)


def test_reordered_and_edited_named_items_keep_their_own_unknown_fields():
    raw = review()["request"]["object"]
    raw["spec"]["entries"] = [{"name": "one", "future": 1}, {"name": "two", "future": 2}]
    after = Widget.model_validate(raw)
    before = after.model_copy(deep=True)
    after.spec.entries.reverse()
    for item in after.spec.entries:
        item.value = 2
    result = apply_patch(raw, mutation_patch(raw, before, after))
    assert result["spec"]["entries"] == [
        {"name": "two", "value": 2, "future": 2},
        {"name": "one", "value": 2, "future": 1},
    ]


def test_model_validator_reordered_items_keep_their_raw_unknown_fields():
    class SortedSpec(Spec):
        @field_validator("entries")
        @classmethod
        def sort_entries(cls, value):
            return sorted(value, key=lambda item: item.name)

    class SortedWidget(Widget):
        spec: SortedSpec

    raw = review()["request"]["object"]
    raw["spec"]["entries"] = [{"name": "two", "future": 2}, {"name": "one", "future": 1}]
    after = SortedWidget.model_validate(raw)
    before = after.model_copy(deep=True)
    after.spec.entries[0].value = 4
    result = apply_patch(raw, mutation_patch(raw, before, after))
    assert result["spec"]["entries"] == [
        {"name": "one", "value": 4, "future": 1},
        {"name": "two", "future": 2},
    ]


def test_indistinguishable_duplicate_items_with_unknown_fields_reject_deletion():
    raw = review()["request"]["object"]
    raw["spec"]["entries"] = [{"name": "same", "future": 1}, {"name": "same", "future": 2}]
    after = Widget.model_validate(raw)
    before = after.model_copy(deep=True)
    after.spec.entries.pop(0)
    with pytest.raises(ValueError, match="duplicate array"):
        mutation_patch(raw, before, after)


def test_multiple_changed_unnamed_unknown_items_rejected():
    class UnnamedItem(BaseModel):
        value: int

    class UnnamedWidget(Widget):
        entries: list[UnnamedItem]

    raw = review()["request"]["object"]
    raw["entries"] = [{"value": 1, "future": 1}, {"value": 2, "future": 2}]
    after = UnnamedWidget.model_validate(raw)
    before = after.model_copy(deep=True)
    after.entries.reverse()
    for item in after.entries:
        item.value += 2
    with pytest.raises(ValueError, match="multiple changed unnamed"):
        mutation_patch(raw, before, after)


def test_reordered_unnamed_items_keep_explicit_default_assignment():
    class UnnamedItem(BaseModel):
        id: int
        value: int = 1

    class UnnamedWidget(Widget):
        entries: list[UnnamedItem]

    raw = review()["request"]["object"]
    raw["entries"] = [{"id": 1}, {"id": 2}]
    after = UnnamedWidget.model_validate(raw)
    before = after.model_copy(deep=True)
    after.entries.reverse()
    after.entries[0].value = 1
    result = apply_patch(raw, mutation_patch(raw, before, after))
    assert result["entries"] == [{"id": 2, "value": 1}, {"id": 1}]


async def test_invalid_typed_input_is_denied_even_with_ignore_failure_policy():
    app = AdmissionWebhook()

    @app.validating(Widget, resource="widgets", path="/mutate", failure_policy="Ignore")
    async def validate(request):
        pytest.fail("Invalid typed object must be denied before callback")

    payload = review()
    payload["request"]["object"]["spec"]["replicas"] = "invalid-private-value"
    response = await post(app, payload)
    assert response.status_code == 200
    assert response.json()["response"]["uid"] == "request-uid"
    assert response.json()["response"]["allowed"] is False
    assert response.json()["response"]["status"]["code"] == 422
    assert response.json()["response"]["status"]["details"]["causes"][0]["field"] == "spec.replicas"
    assert "spec.replicas" in response.json()["response"]["status"]["message"]
    assert "invalid-private-value" not in response.text


async def test_asgi_disconnect_cancels_and_joins_callback():
    app = AdmissionWebhook()
    entered, cancelled = asyncio.Event(), asyncio.Event()
    messages, sent = asyncio.Queue(), []

    @app.validating(Widget, resource="widgets", path="/mutate")
    async def validate(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def send(message):
        sent.append(message)

    messages.put_nowait({"type": "http.request", "body": json.dumps(review()).encode()})
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mutate",
        "headers": [(b"content-type", b"application/json")],
    }
    task = asyncio.create_task(app(scope, messages.get, send))
    await asyncio.wait_for(entered.wait(), 1)
    messages.put_nowait({"type": "http.disconnect"})
    await asyncio.wait_for(task, 1)
    assert cancelled.is_set()
    assert not sent


async def test_slow_response_does_not_send_second_status_after_timeout():
    app = AdmissionWebhook()
    messages, sent = asyncio.Queue(), []

    @app.validating(Widget, resource="widgets", path="/mutate", timeout_seconds=1)
    async def validate(request):
        return None

    async def send(message):
        sent.append(message)
        await asyncio.Event().wait()

    messages.put_nowait({"type": "http.request", "body": json.dumps(review()).encode()})
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mutate",
        "headers": [(b"content-type", b"application/json")],
    }
    await asyncio.wait_for(app(scope, messages.get, send), 2)
    assert len(sent) == 1
    assert sent[0]["status"] == 200


def test_registration_requires_wire_alias_and_accepts_dns_plural():
    app = AdmissionWebhook()

    class MissingAlias(Widget):
        api_version: Literal["example.com/v1"] = "example.com/v1"

    async def handler(request):
        return None

    with pytest.raises(ValueError, match="alias='apiVersion'"):
        app.mutating(MissingAlias, resource="widgets", path="/mutate")(handler)
    app.mutating(Widget, resource="my-widgets", path="/mutate")(handler)


async def test_nonfinite_json_rejected():
    app = AdmissionWebhook()

    @app.mutating(Widget, resource="widgets", path="/mutate")
    async def mutate(request):
        pytest.fail("Non-finite JSON must not reach handler")

    payload = review()
    payload["request"]["object"]["unknown"] = float("nan")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://webhook"
    ) as client:
        response = await client.post(
            "/mutate", content=json.dumps(payload), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 400


async def test_resource_attached_policies_receive_typed_payload_and_live_client():
    from unittest.mock import AsyncMock, Mock

    from cloudcoil.admission import mutating, validating
    from cloudcoil.crd import custom_resource

    clients = [Mock(name="first-client"), Mock(name="second-client")]
    configs = [Mock(async_client_for=AsyncMock(return_value=client)) for client in clients]
    seen = []

    @custom_resource(plural="widgets")
    class Attached(Widget):
        @classmethod
        @mutating(path="/mutate")
        async def defaults(cls, request, client):
            assert isinstance(request.resource, cls)
            assert request.dry_run and request.user_info.username == "sam"
            seen.append((request.config, client))
            # Mutators edit the payload, not the API resource. No write methods are called.
            request.resource.spec.replicas = 4
            return request.resource

        @staticmethod
        @validating(path="/validate", operations=("DELETE",))
        async def protect_delete(request):
            assert request.resource is None
            assert isinstance(request.old_resource, Attached)
            raise AdmissionDenied("Deletion requires an administrator")

    apps = [AdmissionWebhook(config=config).register(Attached) for config in configs]
    assert all(config.async_client_for.await_count == 0 for config in configs)
    payload = review(dryRun=True, userInfo={"username": "sam"})
    for app, config, client in zip(apps, configs, clients, strict=True):
        assert patch(await post(app, payload)) == [
            {"op": "add", "path": "/spec/replicas", "value": 4}
        ]
        config.async_client_for.assert_awaited_once_with(Attached, cached=False)
        assert not client.method_calls
    assert seen == list(zip(configs, clients, strict=True))
    response = await post(apps[0], review("DELETE"), path="/validate")
    assert response.json()["response"]["allowed"] is False
    assert response.json()["response"]["status"]["message"].startswith("Deletion requires")
    configs[0].async_client_for.assert_awaited_once()  # Pure callback does not discover clients.


def test_resource_registration_is_atomic_and_requires_client_config():
    from cloudcoil.admission import mutating, validating
    from cloudcoil.crd import custom_resource

    @custom_resource(plural="widgets")
    class Collision(Widget):
        @classmethod
        @mutating(path="/same")
        async def first(cls, request):
            return request.resource

        @classmethod
        @validating(path="/same")
        async def second(cls, request):
            pass

    app = AdmissionWebhook()
    with pytest.raises(ValueError, match="unique"):
        app.register(Collision)
    assert app._routes == {}

    @custom_resource(plural="widgets")
    class NeedsClient(Widget):
        @classmethod
        @validating()
        async def validate_lookup(cls, request, client):
            pass

    with pytest.raises(ValueError, match="config="):
        app.register(NeedsClient)
    assert app._routes == {}


async def test_attached_handlers_honor_inheritance_shadowing_and_explicit_registration():
    from cloudcoil.admission import mutating, validating
    from cloudcoil.crd import custom_resource

    class Base(Widget):
        @classmethod
        @mutating()
        async def inherited(cls, request):
            assert isinstance(request.resource, cls)
            request.resource.spec.replicas = 7
            return request.resource

        @classmethod
        @validating()
        async def overridden(cls, request):
            raise AssertionError("A shadowed parent policy must not run")

    @custom_resource(plural="widgets", scope="Namespaced")
    class Child(Base):
        @classmethod
        async def overridden(cls, request):
            pass

    first, second = AdmissionWebhook(), AdmissionWebhook()
    first.register(Child)
    assert not second._routes  # Class definition and registration never touch other apps.
    assert list(first._routes) == ["/mutate/example/com/v1/widgets/inherited"]
    response = await post(first, review(), path=next(iter(first._routes)))
    assert patch(response)[0]["value"] == 7
    manifest = first.configurations(
        name="widgets.example.com",
        service_name="webhook",
        service_namespace="test",
        ca_bundle=b"-----BEGIN CERTIFICATE-----\nexample\n-----END CERTIFICATE-----",
    )[0]
    assert manifest["webhooks"][0]["rules"][0]["scope"] == "Namespaced"
    with pytest.raises(ValueError, match="unique"):
        first.register(Child)
    assert len(first._routes) == 1


def test_resource_policy_methods_reject_ambiguous_signatures_and_instance_methods():
    from cloudcoil.admission import validating
    from cloudcoil.crd import custom_resource

    @custom_resource(plural="widgets")
    class InstancePolicy(Widget):
        @validating()
        async def policy(self, request):
            pass

    with pytest.raises(TypeError, match="classmethod or @staticmethod"):
        AdmissionWebhook().register(InstancePolicy)

    @custom_resource(plural="widgets")
    class VariadicPolicy(Widget):
        @classmethod
        @validating()
        async def policy(cls, *args):
            pass

    with pytest.raises(TypeError, match="request and optionally client"):
        AdmissionWebhook().register(VariadicPolicy)


async def test_injected_clients_default_to_each_concurrent_requests_namespace():
    from unittest.mock import AsyncMock, Mock

    from cloudcoil.admission import validating
    from cloudcoil.client import AsyncAPIClient
    from cloudcoil.crd import custom_resource

    in_flight = []
    created_clients = []
    both_arrived = asyncio.Event()

    async def transport(request):
        namespace = request.url.path.split("/namespaces/")[1].split("/")[0]
        in_flight.append(namespace)
        if len(in_flight) == 2:
            both_arrived.set()
        await both_arrived.wait()
        return httpx.Response(
            200,
            json={
                "apiVersion": "example.com/v1",
                "kind": "Widget",
                "metadata": {"name": "sample", "namespace": namespace},
                "spec": {},
            },
        )

    async with httpx.AsyncClient(
        base_url="https://cluster", transport=httpx.MockTransport(transport)
    ) as http_client:

        async def client_for(model, *, cached):
            assert cached is False
            client = AsyncAPIClient(
                api_version="example.com/v1",
                kind=model,
                resource="widgets",
                subresources=[],
                default_namespace="configured-default",
                namespaced=True,
                client=http_client,
            )
            created_clients.append(client)
            return client

        config = Mock(
            namespace="configured-default", async_client_for=AsyncMock(side_effect=client_for)
        )

        @custom_resource(plural="widgets")
        class NamespacedWidget(Widget):
            @classmethod
            @validating(path="/validate")
            async def check_namespace(cls, request, client):
                assert client.default_namespace == request.namespace
                stored = await client.get(request.name)
                assert isinstance(stored, cls)
                assert stored.namespace == request.namespace == client.default_namespace

        app = AdmissionWebhook(config=config).register(NamespacedWidget)
        payloads = []
        for namespace in ("first-tenant", "second-tenant"):
            payload = review(namespace=namespace)
            payload["request"]["object"]["metadata"]["namespace"] = namespace
            payloads.append(payload)
        responses = await asyncio.wait_for(
            asyncio.gather(*(post(app, payload, path="/validate") for payload in payloads)), 3
        )
        assert all(response.json()["response"]["allowed"] for response in responses)
        assert sorted(in_flight) == ["first-tenant", "second-tenant"]
        assert len({id(client) for client in created_clients}) == 2
        assert config.namespace == "configured-default"
        assert sorted(client.default_namespace for client in created_clients) == sorted(in_flight)
