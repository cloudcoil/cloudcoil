"""Handwritten resources share generated model builders and client operations."""

from typing import Literal

import httpx
import pytest
from pydantic import Field, ValidationError

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import Config
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class Child(BaseModel):
    message: str = Field(min_length=1)


class Spec(BaseModel):
    children: list[Child] = Field(default_factory=list)
    optional: Child | None = None
    wire_name: str = Field(default="default", alias="wireName")


class Widget(Resource):
    api_version: Literal["builders.example/v1"] = Field(
        default="builders.example/v1", alias="apiVersion"
    )
    kind: Literal["Widget"] = "Widget"
    spec: Spec
    status: dict[str, str] | None = None


def test_handwritten_fluent_builders_interoperate_with_generated_metadata():
    original = Widget.builder().metadata(lambda meta: meta.name("example"))
    builder = original.spec(
        lambda spec: spec.wire_name("renamed").children(
            lambda children: children.add(lambda child: child.message("hello"))
        )
    )
    result = builder.build()
    assert isinstance(result, Widget)
    assert result.name == "example"
    assert result.spec.children == [Child(message="hello")]
    assert result.model_dump(by_alias=True)["spec"]["wireName"] == "renamed"
    with pytest.raises(ValidationError, match="spec"):
        original.build()  # Fluent updates do not alter an earlier builder.
    with pytest.raises(ValidationError, match="at least 1 character"):
        Child.builder().message("").build()


def test_handwritten_nested_contexts_and_explicit_none():
    with Widget.new() as widget:
        with widget.metadata() as meta:
            meta.name("example")
        with widget.spec() as spec:
            with spec.children() as children:
                with children.add() as child:
                    child.message("one")
                with children.add() as child:
                    child.message("two")
            with spec.optional() as child:
                child.message("optional")
        widget.status(None)
    result = widget.build()
    assert result.spec.children == [Child(message="one"), Child(message="two")]
    assert result.spec.optional == Child(message="optional")
    assert result.status is None
    assert not widget._in_context
    assert not spec._in_context


def test_handwritten_builder_context_does_not_commit_failed_children():
    with Spec.new() as spec:
        with pytest.raises(RuntimeError, match="stop"):
            with spec.children() as children:
                with children.add() as child:
                    child.message("not committed")
                raise RuntimeError("stop")
        with pytest.raises(RuntimeError, match="stop"):
            with spec.optional() as child:
                child.message("not committed")
                raise RuntimeError("stop")
    assert spec.build() == Spec()
    assert not child._in_context


def test_handwritten_list_builders_are_persistent_and_validate():
    original = Widget.list_builder()
    changed = original.add(lambda widget: widget.metadata(ObjectMeta(name="example")).spec(Spec()))
    values = changed.build()
    assert values[0].name == "example"
    assert original.build() == []
    values.clear()
    assert len(changed.build()) == 1
    with pytest.raises(ValidationError):
        original.add(lambda widget: widget.spec({"optional": {"message": ""}}))


def test_handwritten_builder_subclasses_and_deferred_annotations():
    class Extended(Widget):
        extra_field: str

    built = Extended.builder().spec(Spec()).extra_field("extra").build()
    assert type(built) is Extended
    assert built.extra_field == "extra"

    class Deferred(BaseModel):
        child: "Later"

    class Later(BaseModel):
        value: int

    Deferred.model_rebuild()  # Resolve function-local forward references as with Pydantic.
    assert Deferred.builder().child(lambda child: child.value(1)).build().child == Later(value=1)


def test_handwritten_builder_requires_explicit_values_for_ambiguous_unions():
    class Choice(BaseModel):
        value: Child | Spec
        build: str

    result = Choice.builder().value(Child(message="choice")).build_("value").build()
    assert result.build == "value"
    with Choice.new() as choice:
        with pytest.raises(TypeError, match="value"):
            choice.value()
    with pytest.raises(TypeError, match="optional"):
        Spec.builder().optional()
    with pytest.raises(AttributeError, match="typo"):
        Spec.builder().typo("value")


def _config():
    config = Config(server="https://example.invalid", namespace="default")
    config._rest_mapping[Widget.gvk()] = {
        "resource": "widgets",
        "namespaced": True,
        "subresources": ["status"],
    }
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        obj = Widget(metadata=ObjectMeta(name="example", namespace="team"), spec=Spec())
        return httpx.Response(200, json=obj.model_dump(by_alias=True, exclude_none=True))

    config.client = httpx.Client(
        base_url="https://example.invalid", transport=httpx.MockTransport(handle)
    )
    config.async_client = httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handle)
    )
    return config, calls


async def test_handwritten_sync_client_explicit_and_active_config():
    config, calls = _config()
    try:
        scoped = Widget.client(config, namespace="team", cached=False)
        assert scoped.get("example").spec == Spec()
        assert config.namespace == "default"
        with config:
            assert Widget.client().default_namespace == "default"
            assert Widget.get("example", namespace="team").name == "example"
        assert calls == [("GET", "/apis/builders.example/v1/namespaces/team/widgets/example")] * 2
    finally:
        config.client.close()
        await config.async_client.aclose()


async def test_handwritten_async_client_namespace_and_inherited_status_patch():
    config, calls = _config()
    try:
        client = await Widget.async_client(config, namespace="team", cached=False)
        widget = await client.get("example")
        assert isinstance(widget, Widget)
        assert config.namespace == "default"
        with config:
            default = await Widget.async_client()
            assert default.default_namespace == "default"
            widget.status = {"phase": "Ready"}
            assert isinstance(await widget.async_update_status(), Widget)
            assert isinstance(await widget.async_patch([]), Widget)
        assert calls == [
            ("GET", "/apis/builders.example/v1/namespaces/team/widgets/example"),
            ("PUT", "/apis/builders.example/v1/namespaces/team/widgets/example/status"),
            ("PATCH", "/apis/builders.example/v1/namespaces/team/widgets/example"),
        ]
    finally:
        config.client.close()
        await config.async_client.aclose()
