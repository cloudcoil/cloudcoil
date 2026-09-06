"""Converge explicitly supplied child fields without adopting somebody else's objects."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from cloudcoil.apimachinery import ObjectMeta, OwnerReference
from cloudcoil.errors import ResourceNotFound
from cloudcoil.patches import diff
from cloudcoil.resources import Resource

from ._types import TerminalError

if TYPE_CHECKING:
    from cloudcoil.client import Config


def _merge(current: dict[str, Any], desired: dict[str, Any]) -> None:
    for key, value in desired.items():
        if value is None:
            current.pop(key, None)
        elif isinstance(value, dict) and isinstance(current.get(key), dict):
            _merge(current[key], value)
        else:
            current[key] = deepcopy(value)


async def ensure[T: Resource](parent: Resource, desired: T, *, config: "Config | None") -> T:
    if not parent.metadata or not parent.metadata.uid or not parent.name:
        raise ValueError("Ensuring a child requires a persisted parent with a UID")
    if parent.metadata.deletion_timestamp:
        raise TerminalError("Cannot ensure children while the parent is being deleted")
    child = desired.model_copy(deep=True)
    if child.metadata is None:
        child.metadata = ObjectMeta()
    if child.metadata.uid or child.metadata.resource_version:
        raise ValueError("Supply desired child fields, not a fetched resource with UID/version")
    if child.metadata.owner_references:
        raise ValueError("ensure sets owner references; omit them from the desired child")
    if "status" in child.model_fields_set:
        raise ValueError("ensure manages child desired state, not child status")
    if child.name is None:
        child.metadata.name = parent.name
    client = await type(child).async_client(config, cached=False)
    if client.namespaced:
        child.metadata.namespace = child.namespace or parent.namespace or client.default_namespace
        if parent.namespace and child.namespace != parent.namespace:
            raise ValueError("A namespaced parent cannot own a child in another namespace")
    elif parent.namespace or child.namespace:
        raise ValueError("A cluster-scoped child requires a cluster-scoped parent and no namespace")
    owner = OwnerReference(
        api_version=parent.gvk().api_version,
        kind=parent.gvk().kind,
        name=parent.name,
        uid=parent.metadata.uid,
        controller=True,
    )
    child.metadata.owner_references = [owner]
    assert child.name is not None
    try:
        current = await client.get(child.name, child.namespace)
    except ResourceNotFound:
        return await client.create(child)
    owners = current.metadata.owner_references if current.metadata else None
    if not any(
        ref.controller
        and ref.uid == owner.uid
        and ref.kind == owner.kind
        and ref.name == owner.name
        and ref.api_version.rpartition("/")[0] == owner.api_version.rpartition("/")[0]
        for ref in owners or []
    ):
        raise TerminalError(f"Refusing to adopt unrelated {child.kind} {child.name}")
    if current.metadata and current.metadata.deletion_timestamp:
        raise RuntimeError(f"Waiting for deleting {child.kind} {child.name} to disappear")
    fields = child.model_dump(mode="json", by_alias=True, exclude_unset=True)
    # Preserve all existing owner references, including non-controller owners.
    fields.get("metadata", {}).pop("ownerReferences", None)
    merged = current.model_dump(mode="json", by_alias=True, exclude_none=True)
    _merge(merged, fields)
    updated = type(child).model_validate(merged)
    operations = diff(current, updated)
    return await client.patch(current, operations) if operations else current
