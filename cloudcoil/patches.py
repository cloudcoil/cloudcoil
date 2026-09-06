"""Dependency-free JSON Patch calculation and optimistic resource diffs."""

import json
from copy import deepcopy
from typing import Any

from cloudcoil.resources import Resource


def json_patch(before: Any, after: Any) -> list[dict[str, Any]]:
    """Calculate RFC 6902 operations for JSON values, preserving explicit nulls.

    Object members are diffed recursively. Arrays are replaced as a whole; this
    does not infer Kubernetes strategic-merge keys. Values are copied into the
    patch so later mutation of the desired document cannot change the request.
    """
    # Validate JSON values, including rejecting non-finite numbers.
    json.dumps(before, allow_nan=False)
    json.dumps(after, allow_nan=False)
    patch: list[dict[str, Any]] = []

    def visit(old: Any, new: Any, path: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                pointer = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
                if key not in new:
                    patch.append({"op": "remove", "path": pointer})
                elif key not in old:
                    patch.append({"op": "add", "path": pointer, "value": deepcopy(new[key])})
                else:
                    visit(old[key], new[key], pointer)
        elif json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True):
            patch.append({"op": "replace", "path": path, "value": deepcopy(new)})

    visit(before, after, "")
    return patch


def diff(before: Resource, after: Resource) -> list[dict[str, Any]]:
    """Diff copies of one fetched resource, guarded by UID and resourceVersion.

    Returns [] for no changes. Identity/version changes are rejected. Keep the
    original snapshot unchanged and edit a deep copy. None-valued model fields
    are omitted, matching Resource writes; clearing a field generates a remove.
    """
    if before.gvk() != after.gvk() or (before.name, before.namespace) != (
        after.name,
        after.namespace,
    ):
        raise ValueError("A resource diff cannot change kind, name, or namespace")
    if not before.metadata or not before.metadata.uid or not before.resource_version:
        raise ValueError("An optimistic diff needs a fetched resource with UID and resourceVersion")
    if (
        not after.metadata
        or after.metadata.uid != before.metadata.uid
        or after.resource_version != before.resource_version
    ):
        raise ValueError("A resource diff cannot change UID or resourceVersion")
    patch = json_patch(
        before.model_dump(mode="json", by_alias=True, exclude_none=True),
        after.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    if not patch:
        return []
    return [
        {"op": "test", "path": "/metadata/uid", "value": before.metadata.uid},
        {"op": "test", "path": "/metadata/resourceVersion", "value": before.resource_version},
        *patch,
    ]
