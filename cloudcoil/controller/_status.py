"""Local, validated status edits; persistence stays in the reconciliation runtime."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel as PydanticModel
from pydantic import Field, TypeAdapter

from cloudcoil.apimachinery import Condition, Time
from cloudcoil.crd import ListType
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class ReconcileStatus(BaseModel):
    """Optional base for CR status models used by staged reconcilers."""

    conditions: Annotated[list[Condition], ListType("map", keys=("type",))] = Field(
        default_factory=list
    )
    observed_generation: int | None = Field(default=None, alias="observedGeneration")


def _status_model(resource: Resource) -> type[PydanticModel]:
    field = type(resource).model_fields.get("status")
    if field is not None:
        for candidate in (field.annotation, *get_args(field.annotation)):
            if isinstance(candidate, type) and issubclass(candidate, PydanticModel):
                return candidate
    raise TypeError("Status helpers require a resource with a Pydantic status model")


def update_status[T: Resource](resource: T, **changes: Any) -> T:
    """Edit supplied status fields, preserving other fields; return the resource.

    Accepts Python field names or wire aliases. Creates an absent status through its
    schema (required fields must be provided), validates updates, and rejects typos.
    This is a local edit: return the resource from an ordinary reconciler to save it.
    """
    model = _status_model(resource)
    current = getattr(resource, "status", None)
    values = current.model_dump(mode="python", by_alias=True) if current is not None else {}
    for name, value in changes.items():
        field_name = next(
            (key for key, field in model.model_fields.items() if name in (key, field.alias)), None
        )
        if field_name is None:
            raise ValueError(f"Unknown status field {name!r} on {model.__name__}")
        field = model.model_fields[field_name]
        values[field.alias or field_name] = value
    # Validate before assignment so a failure leaves the original status untouched.
    resource.status = model.model_validate(values)  # type: ignore[attr-defined]
    return resource


def get_condition(resource: Resource, condition: str) -> Condition | None:
    """Read a standard metav1 condition by type, returning an independent copy."""
    status = getattr(resource, "status", None)
    for value in getattr(status, "conditions", None) or []:
        if value.type == condition:
            return Condition.model_validate(value.model_dump(by_alias=True)).model_copy(deep=True)
    return None


def set_condition[T: Resource](
    resource: T,
    condition: str,
    status: bool | Literal["True", "False", "Unknown"],
    *,
    reason: str,
    message: str = "",
) -> T:
    """Upsert a standard condition without churning lastTransitionTime.

    Only a status change updates the timestamp; reason/message/generation changes
    preserve it. Other condition types and status fields survive. No API I/O.
    """
    if not condition or not reason:
        raise ValueError("Condition type and reason must not be empty")
    value = str(status) if isinstance(status, bool) else status
    if value not in ("True", "False", "Unknown"):
        raise ValueError("Condition status must be True, False, or Unknown")
    model = _status_model(resource)
    if "conditions" not in model.model_fields:
        raise TypeError("Status conditions must be declared in the resource schema")
    previous = get_condition(resource, condition)
    updated = Condition(
        type=condition,
        status=value,
        reason=reason,
        message=message,
        observed_generation=resource.metadata.generation if resource.metadata else None,
        last_transition_time=(
            previous.last_transition_time
            if previous is not None and previous.status == value
            else Time(datetime.now(timezone.utc))
        ),
    )
    current = getattr(resource, "status", None)
    conditions = list(getattr(current, "conditions", None) or [])
    index = next(
        (i for i, item in enumerate(conditions) if item.type == condition), len(conditions)
    )
    # Remove malformed duplicate entries for this type, preserving all other types.
    conditions = [item for item in conditions if item.type != condition]
    conditions.insert(index, updated)
    field = model.model_fields["conditions"]
    values = [item.model_dump(by_alias=True) for item in conditions]
    return update_status(resource, conditions=TypeAdapter(field.annotation).validate_python(values))
