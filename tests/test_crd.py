"""CRD schemas preserve wire names and validation without generated model imports."""

from typing import Annotated, Any, Literal

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, create_model, field_serializer

from cloudcoil.crd import CRD, PrinterColumn, SchemaError
from cloudcoil.resources import Resource


class WidgetSpec(BaseModel):
    replicas: int = Field(default=1, gt=0, le=10)
    image: str = Field(min_length=1, max_length=100)
    pull_policy: Literal["Always", "Never"] = Field(default="Always", alias="pullPolicy")
    labels: dict[str, str] = Field(default_factory=dict)


class WidgetStatus(BaseModel):
    ready: bool = False
    observed_generation: int | None = Field(default=None, alias="observedGeneration")


class Widget(Resource):
    api_version: Literal["widgets.example.com/v1alpha1"] = Field(
        default="widgets.example.com/v1alpha1", alias="apiVersion"
    )
    kind: Literal["Widget"] = "Widget"
    spec: WidgetSpec
    status: WidgetStatus | None = None


def schema(model=Widget, **kwargs):
    return CRD(model, plural="widgets", **kwargs).manifest()["spec"]["versions"][0]["schema"][
        "openAPIV3Schema"
    ]


def model_for(annotation, default=...):
    return create_model("Example", __base__=Widget, spec=(annotation, default))


def test_complete_manifest_wire_fields_defaults_and_nullable_status():
    definition = CRD(Widget, plural="widgets")
    manifest = definition.manifest()
    assert yaml.safe_load(definition.to_yaml()) == manifest
    assert manifest["metadata"] == {"name": "widgets.widgets.example.com"}
    assert manifest["apiVersion"] == "apiextensions.k8s.io/v1"
    version = manifest["spec"]["versions"][0]
    assert version["name"] == "v1alpha1" and version["served"] and version["storage"]
    assert version["subresources"] == {"status": {}}
    root = version["schema"]["openAPIV3Schema"]
    assert root["properties"]["metadata"] == {"type": "object"}
    assert root["properties"]["apiVersion"] == {"type": "string"}
    assert "api_version" not in root["properties"]
    assert "$ref" not in str(root) and "$defs" not in root
    spec = root["properties"]["spec"]
    assert spec["required"] == ["image"]
    assert spec["properties"]["replicas"]["minimum"] == 0
    assert spec["properties"]["replicas"]["exclusiveMinimum"] is True
    assert spec["properties"]["replicas"]["maximum"] == 10
    assert spec["properties"]["replicas"]["default"] == 1
    assert spec["properties"]["pullPolicy"]["enum"] == ["Always", "Never"]
    assert spec["properties"]["labels"]["additionalProperties"] == {"type": "string"}
    assert root["properties"]["status"]["nullable"] is True
    assert version["additionalPrinterColumns"][0]["jsonPath"] == ".metadata.creationTimestamp"
    manifest["spec"]["versions"].clear()
    assert definition.manifest()["spec"]["versions"]


def test_names_scope_columns_and_status_override():
    definition = CRD(
        Widget,
        plural="widgets",
        singular="widget",
        scope="Cluster",
        short_names=["wd"],
        categories=["all"],
        status=False,
        columns=[
            PrinterColumn(name="Ready", json_path=".status.ready", type="boolean", priority=1)
        ],
    )
    spec = definition.manifest()["spec"]
    assert spec["scope"] == "Cluster"
    assert spec["names"]["shortNames"] == ["wd"]
    assert spec["names"]["categories"] == ["all"]
    version = spec["versions"][0]
    assert "subresources" not in version
    assert version["additionalPrinterColumns"] == [
        {"name": "Ready", "jsonPath": ".status.ready", "type": "boolean", "priority": 1}
    ]
    assert (
        "additionalPrinterColumns"
        not in CRD(Widget, plural="widgets", columns=[]).manifest()["spec"]["versions"][0]
    )


def test_untyped_json_explicitly_preserves_values():
    root = schema(model_for(dict[str, Any]))
    assert root["properties"]["spec"] == {
        "type": "object",
        "title": "Spec",
        "x-kubernetes-preserve-unknown-fields": True,
    }
    any_schema = schema(model_for(Any))["properties"]["spec"]
    assert any_schema["x-kubernetes-preserve-unknown-fields"] and any_schema["nullable"]
    assert "type" not in any_schema


def test_arrays_repeated_refs_and_const():
    class Item(BaseModel):
        name: Literal["entry"] = "entry"

    class Spec(BaseModel):
        first: Item
        second: list[Item]

    result = schema(model_for(Spec))["properties"]["spec"]["properties"]
    assert result["first"]["properties"]["name"]["enum"] == ["entry"]
    assert result["second"]["items"] == result["first"]


def test_nullable_ref_field_description_does_not_change_shared_definition():
    class Spec(BaseModel):
        first: WidgetStatus | None = Field(default=None, description="First status")
        second: WidgetStatus

    props = schema(model_for(Spec))["properties"]["spec"]["properties"]
    assert props["first"]["nullable"] and props["first"]["description"] == "First status"
    assert "nullable" not in props["second"] and "description" not in props["second"]


@pytest.mark.parametrize("annotation", [int | str, str | int | None])
def test_int_or_string_unions(annotation):
    result = schema(model_for(annotation))["properties"]["spec"]
    assert result["x-kubernetes-int-or-string"] is True
    assert "type" not in result
    assert result["anyOf"] == [{"type": "integer"}, {"type": "string"}]


def test_list_map_and_cel_extensions():
    class Condition(BaseModel):
        type: str
        status: Literal["True", "False", "Unknown"]

    class Spec(BaseModel):
        model_config = ConfigDict(
            json_schema_extra={
                "x-kubernetes-validations": [
                    {"rule": "self.min <= self.max", "message": "invalid range"}
                ]
            }
        )
        min: int = 0
        max: int = 10
        conditions: list[Condition] = Field(
            default_factory=list,
            json_schema_extra={
                "x-kubernetes-list-type": "map",
                "x-kubernetes-list-map-keys": ["type"],
            },
        )
        tags: list[str] = Field(
            default_factory=list, json_schema_extra={"x-kubernetes-list-type": "set"}
        )

    result = schema(model_for(Spec))["properties"]["spec"]
    assert result["x-kubernetes-validations"][0]["rule"] == "self.min <= self.max"
    assert result["properties"]["conditions"]["x-kubernetes-list-map-keys"] == ["type"]
    assert result["properties"]["tags"]["x-kubernetes-list-type"] == "set"


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        (str | float, "unions"),
        (tuple[int, str], "prefixItems"),
        (set[str], "uniqueItems"),
        (dict[Annotated[str, Field(pattern="^x")], int], "patternProperties"),
        (type(None), "null-only"),
    ],
)
def test_unsupported_schema_never_silently_weakens(annotation, message):
    with pytest.raises(SchemaError, match=message):
        schema(model_for(annotation))


def test_recursive_ref_has_useful_path():
    class Recursive(BaseModel):
        next: "Recursive | None" = None

    with pytest.raises(SchemaError, match=r"Example.spec.next: recursive"):
        schema(model_for(Recursive))


def test_forbid_extra_is_not_silently_replaced_with_pruning():
    class Spec(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str

    with pytest.raises(SchemaError, match="additionalProperties=false"):
        schema(model_for(Spec))


def test_extra_allow_uses_preserve_unknown_alongside_validated_properties():
    class Spec(BaseModel):
        model_config = ConfigDict(extra="allow")
        name: str

    result = schema(model_for(Spec))["properties"]["spec"]
    assert result["x-kubernetes-preserve-unknown-fields"]
    assert result["properties"]["name"]["type"] == "string"
    assert "additionalProperties" not in result


def test_required_status_rejected_before_producing_uncreatable_crd():
    required = create_model("Required", __base__=Widget, status=(WidgetStatus, ...))
    with pytest.raises(SchemaError, match="status must be optional"):
        schema(required)
    assert schema(required, status=False)["properties"]["status"]["type"] == "object"


def test_status_requires_object_and_missing_status_can_be_disabled():
    scalar = create_model("Scalar", __base__=Widget, status=(str | None, None))
    with pytest.raises(SchemaError, match="status must be an object"):
        schema(scalar)

    class NoStatus(Resource):
        api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
        kind: Literal["NoStatus"] = "NoStatus"

    assert "subresources" not in CRD(NoStatus, plural="things").manifest()["spec"]["versions"][0]
    with pytest.raises(SchemaError, match="requires a status field"):
        CRD(NoStatus, plural="things", status=True)


def test_api_version_alias_is_required_for_actual_client_serialization():
    class WrongAlias(Widget):
        api_version: Literal["example.com/v1"] = "example.com/v1"

    with pytest.raises(SchemaError, match="alias='apiVersion'"):
        schema(WrongAlias)


def test_mismatched_alias_and_computed_or_excluded_fields_fail():
    class Mismatched(BaseModel):
        value: str = Field(validation_alias="input", serialization_alias="output")

    class Computed(BaseModel):
        @computed_field
        @property
        def value(self) -> str:
            return "computed"

    class Excluded(BaseModel):
        value: str = Field(exclude=True)

    class Serialized(BaseModel):
        value: int

        @field_serializer("value")
        def serialize(self, value: int) -> str:
            return str(value)

    for model, message in [
        (Mismatched, "aliases"),
        (Computed, "computed fields"),
        (Excluded, "excluded fields"),
        (Serialized, "custom serializers"),
    ]:
        with pytest.raises(SchemaError, match=message):
            schema(model_for(model))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"plural": "Widgets"},
        {"plural": "my_widgets"},
        {"scope": "unknown"},
        {"short_names": "wd"},
        {"categories": ["UPPER"]},
        {"singular": ""},
    ],
)
def test_invalid_names_and_scope(kwargs):
    with pytest.raises(ValueError):
        CRD(Widget, **({"plural": "widgets"} | kwargs))


@pytest.mark.parametrize(
    "extra",
    [
        {"x-kubernetes-preserve-unknown-fields": False},
        {"x-kubernetes-list-type": "map"},
        {"x-kubernetes-map-type": "set"},
        {"x-kubernetes-validations": [{"message": "no rule"}]},
        {"not-a-schema-key": True},
    ],
)
def test_malformed_extensions_and_unknown_keywords_fail(extra):
    annotation = Annotated[str, Field(json_schema_extra=extra)]
    with pytest.raises(SchemaError):
        schema(model_for(annotation))


def test_bound_conversion_preserves_stricter_inclusive_bound():
    result = schema(model_for(Annotated[int, Field(ge=5, gt=2, le=8, lt=10)]))["properties"]["spec"]
    assert result["minimum"] == 5 and result["maximum"] == 8
    assert "exclusiveMinimum" not in result and "exclusiveMaximum" not in result


def test_dns_names_can_include_hyphens():
    assert CRD(Widget, plural="my-widgets").manifest()["spec"]["names"]["plural"] == "my-widgets"


def test_invalid_api_version_does_not_get_truncated():
    class WrongVersion(Widget):
        api_version: Literal["example.com/v1/extra"] = Field(
            default="example.com/v1/extra", alias="apiVersion"
        )

    with pytest.raises(ValueError, match="exactly one"):
        schema(WrongVersion)


def test_resource_metadata_and_annotated_columns_share_wire_names_and_types():
    from datetime import datetime

    from cloudcoil.crd import custom_resource

    class Status(BaseModel):
        available_replicas: Annotated[int, PrinterColumn(name="Available")] = Field(
            default=0, alias="availableReplicas"
        )
        ready: Annotated[bool, PrinterColumn(name="Ready")] = False
        updated: Annotated[datetime | None, PrinterColumn(name="Updated")] = None

    @custom_resource(plural="gadgets", scope="Cluster", short_names=("gd",))
    class Gadget(Widget):
        status: Status | None = None

    definition = CRD(Gadget).manifest()["spec"]
    assert definition["scope"] == "Cluster"
    assert definition["names"]["plural"] == "gadgets"
    assert definition["names"]["shortNames"] == ["gd"]
    columns = definition["versions"][0]["additionalPrinterColumns"]
    assert [(column["jsonPath"], column["type"]) for column in columns] == [
        (".status.availableReplicas", "integer"),
        (".status.ready", "boolean"),
        (".status.updated", "date"),
        (".metadata.creationTimestamp", "date"),
    ]
    assert "x-cloudcoil" not in str(definition)
    # Explicit constructor options override metadata, including empty collections.
    explicit = CRD(Gadget, plural="others", scope="Namespaced", short_names=[], columns=[])
    assert explicit.plural == "others" and explicit.scope == "Namespaced"
    assert "shortNames" not in explicit.manifest()["spec"]["names"]
    assert "additionalPrinterColumns" not in explicit.manifest()["spec"]["versions"][0]


def test_resource_metadata_requires_explicit_plural_on_concrete_subclasses():
    from cloudcoil.crd import custom_resource

    @custom_resource(plural="widgets")
    class Parent(Widget):
        pass

    class Child(Parent):
        pass

    with pytest.raises(ValueError, match="plural"):
        CRD(Child)
    assert CRD(Child, plural="children").plural == "children"
    with pytest.raises(ValueError, match="already declared"):
        custom_resource(plural="other")(Parent)


def test_annotated_cel_and_list_semantics_preserve_pydantic_constraints():
    from cloudcoil.crd import CEL, ListType

    class Condition(BaseModel):
        condition_type: str = Field(alias="conditionType")
        status: Literal["True", "False"]

    class Spec(BaseModel):
        replicas: Annotated[
            int,
            Field(ge=0),
            CEL("self <= 10", "Too many replicas"),
            CEL("self % 2 == 0", "Must be even"),
        ] = 2
        conditions: Annotated[list[Condition], ListType("map", keys=("conditionType",))]
        tags: Annotated[list[str], ListType("set")] = Field(default_factory=list)

    props = schema(model_for(Spec))["properties"]["spec"]["properties"]
    assert props["replicas"]["minimum"] == 0
    assert props["replicas"]["x-kubernetes-validations"] == [
        {"rule": "self <= 10", "message": "Too many replicas"},
        {"rule": "self % 2 == 0", "message": "Must be even"},
    ]
    assert props["conditions"]["x-kubernetes-list-map-keys"] == ["conditionType"]
    assert props["tags"]["x-kubernetes-list-type"] == "set"
    # CEL is intentionally a server constraint, not an implicit Python validator.
    assert Spec(replicas=11, conditions=[]).replicas == 11


def test_annotation_errors_do_not_silently_generate_invalid_columns_or_lists():
    from cloudcoil.crd import ListType

    with pytest.raises(ValueError, match="keys"):
        ListType("map")
    with pytest.raises(ValueError, match="keys"):
        ListType("set", keys=("name",))
    with pytest.raises(SchemaError, match="requires an array"):
        schema(model_for(Annotated[str, ListType("atomic")]))
    with pytest.raises(SchemaError, match="scalar field"):
        schema(model_for(Annotated[WidgetSpec, PrinterColumn(name="Spec")]))
    with pytest.raises(ValueError, match="json_path"):
        CRD(Widget, plural="widgets", columns=[PrinterColumn(name="Unknown")])


def test_annotated_columns_resolve_each_reused_model_path_and_escape_aliases():
    class Nested(BaseModel):
        value: Annotated[int, PrinterColumn(name="Value")] = Field(alias="some.value")

    class Spec(BaseModel):
        first: Nested
        second: Nested

    columns = CRD(model_for(Spec), plural="widgets").manifest()["spec"]["versions"][0][
        "additionalPrinterColumns"
    ]
    assert [column["jsonPath"] for column in columns[:2]] == [
        r".spec.first.some\.value",
        r".spec.second.some\.value",
    ]
    # Collection items have no single inferred JSONPath; require an explicit path.
    with pytest.raises(SchemaError, match="explicit json_path"):
        schema(model_for(list[Nested]))


def test_explicit_columns_replace_annotated_columns_without_requiring_inference():
    model = model_for(Annotated[WidgetSpec, PrinterColumn(name="Spec")])
    version = CRD(model, plural="widgets", columns=[]).manifest()["spec"]["versions"][0]
    assert "additionalPrinterColumns" not in version
    assert "x-cloudcoil" not in str(version)
