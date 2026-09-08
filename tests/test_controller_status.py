from typing import Literal

import pytest
from pydantic import Field, ValidationError

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.controller import ReconcileStatus, get_condition, set_condition, update_status
from cloudcoil.crd import custom_resource
from cloudcoil.resources import Resource


class Status(ReconcileStatus):
    ready_replicas: int = Field(default=0, ge=0, alias="readyReplicas")
    endpoint: str | None = None


class Widget(Resource):
    api_version: Literal["example.com/v1"] = "example.com/v1"
    kind: Literal["Widget"] = "Widget"
    status: Status | None = None


def widget():
    return Widget(metadata=ObjectMeta(name="a", namespace="ns", uid="u", generation=1))


def test_status_updates_preserve_fields_validate_and_accept_aliases():
    obj = widget()
    assert update_status(obj, endpoint="https://example.com", readyReplicas=2) is obj
    update_status(obj, ready_replicas=3)
    assert obj.status.ready_replicas == 3
    assert obj.status.endpoint == "https://example.com"
    with pytest.raises(ValueError, match="Unknown status field"):
        update_status(obj, ready_replica=10)
    with pytest.raises(ValidationError):
        update_status(obj, ready_replicas=-1)
    assert obj.status.ready_replicas == 3


def test_conditions_preserve_timestamp_except_on_status_transition():
    obj = widget()
    set_condition(obj, "Ready", False, reason="Creating")
    original = obj.model_copy(deep=True)
    set_condition(obj, "Ready", False, reason="Creating")
    assert obj == original
    first = get_condition(obj, "Ready")
    obj.metadata.generation = 2
    set_condition(obj, "Ready", False, reason="Waiting", message="Waiting for deployment")
    current = get_condition(obj, "Ready")
    assert current.last_transition_time == first.last_transition_time
    assert current.observed_generation == 2
    set_condition(obj, "Ready", True, reason="Available")
    assert get_condition(obj, "Ready").last_transition_time != first.last_transition_time
    assert get_condition(obj, "Unknown") is None


def test_conditions_preserve_unrelated_status_and_do_not_alias_reads():
    obj = widget()
    update_status(obj, endpoint="keep")
    set_condition(obj, "ExternalReady", True, reason="Available")
    external = get_condition(obj, "ExternalReady")
    set_condition(obj, "Ready", "Unknown", reason="Starting")
    assert obj.status.endpoint == "keep"
    assert get_condition(obj, "ExternalReady") == external
    external.reason = "Mutated"
    assert get_condition(obj, "ExternalReady").reason == "Available"
    with pytest.raises(ValueError):
        set_condition(obj, "Ready", "yes", reason="Invalid")


def test_status_schema_declares_conditions_as_a_map():
    resource = custom_resource(api_version="example.com/v1", plural="widgets")(Widget)
    schema = resource.model_json_schema()
    conditions = schema["$defs"]["Status"]["properties"]["conditions"]
    assert conditions["x-kubernetes-list-type"] == "map"
    assert conditions["x-kubernetes-list-map-keys"] == ["type"]
