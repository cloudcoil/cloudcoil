"""Apply typed intent to raw admission JSON without erasing unknown fields."""

import json
from copy import deepcopy
from typing import Any

from cloudcoil.patches import json_patch
from cloudcoil.resources import Resource

_MISSING = object()


def _equal(a: Any, b: Any) -> bool:
    if a is _MISSING or b is _MISSING:
        return a is b
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(
        b, sort_keys=True, allow_nan=False
    )


def _unknown(raw: Any, typed: Any) -> bool:
    if isinstance(raw, dict) and isinstance(typed, dict):
        return any(key not in typed or _unknown(value, typed[key]) for key, value in raw.items())
    if isinstance(raw, list) and isinstance(typed, list):
        return any(_unknown(a, b) for a, b in zip(raw, typed, strict=True))
    return False


def _projection_matches(raw: Any, typed: Any) -> bool:
    if isinstance(raw, dict) and isinstance(typed, dict):
        return all(
            key not in typed or _projection_matches(value, typed[key]) for key, value in raw.items()
        )
    if isinstance(raw, list) and isinstance(typed, list):
        return len(raw) == len(typed) and all(
            _projection_matches(a, b) for a, b in zip(raw, typed, strict=True)
        )
    return _equal(raw, typed)


def _names(values: list[Any]) -> list[str] | None:
    names = [value.get("name") if isinstance(value, dict) else None for value in values]
    if all(isinstance(name, str) and name for name in names) and len(set(names)) == len(names):
        return [str(name) for name in names]
    return None


def _overlay(raw: Any, before: Any, after: Any, explicit_before: Any, explicit_after: Any) -> Any:
    if _equal(before, after) and (raw is not _MISSING or _equal(explicit_before, explicit_after)):
        # Recurse into dictionaries: a nested assignment may explicitly set an
        # omitted field to its default even when the complete dumps are equal.
        if not isinstance(before, (dict, list)) or _equal(explicit_before, explicit_after):
            return deepcopy(raw) if raw is not _MISSING else _MISSING
    if isinstance(before, dict) and isinstance(after, dict):
        output = deepcopy(raw) if isinstance(raw, dict) else {}
        for key in before.keys() | after.keys():
            if key not in after:
                output.pop(key, None)
                continue
            old_explicit = (
                explicit_before.get(key, _MISSING)
                if isinstance(explicit_before, dict)
                else _MISSING
            )
            new_explicit = (
                explicit_after.get(key, _MISSING) if isinstance(explicit_after, dict) else _MISSING
            )
            value = _overlay(
                output.get(key, _MISSING),
                before.get(key, _MISSING),
                after[key],
                old_explicit,
                new_explicit,
            )
            if value is not _MISSING:
                output[key] = value
        return output if output or raw is not _MISSING else _MISSING
    if isinstance(before, list) and isinstance(after, list) and isinstance(raw, list):
        if len(before) != len(raw):
            raise ValueError(
                "A model validator changed array length; mutation cannot preserve raw fields"
            )
        before_names, after_names, raw_names = _names(before), _names(after), _names(raw)
        if before_names is not None and after_names is not None and raw_names is not None:
            if set(before_names) != set(raw_names):
                raise ValueError(
                    "A model validator changed array identity; mutation cannot preserve raw fields"
                )
            old_indices = {name: index for index, name in enumerate(before_names)}
            raw_indices = {name: index for index, name in enumerate(raw_names)}
            if set(after_names) - set(before_names) and any(
                _unknown(raw[raw_indices[name]], before[old_indices[name]])
                for name in set(before_names) - set(after_names)
            ):
                raise ValueError(
                    "Cannot safely replace named array elements containing unknown fields"
                )
            result = []
            for index, name in enumerate(after_names):
                if name not in old_indices:
                    result.append(deepcopy(after[index]))
                    continue
                old_index = old_indices[name]
                result.append(
                    _overlay(
                        raw[raw_indices[name]],
                        before[old_index],
                        after[index],
                        explicit_before[old_index]
                        if isinstance(explicit_before, list)
                        else _MISSING,
                        explicit_after[index] if isinstance(explicit_after, list) else _MISSING,
                    )
                )
            return result
        if not all(_projection_matches(value, old) for value, old in zip(raw, before, strict=True)):
            raise ValueError(
                "A model validator changed unnamed array elements; mutation cannot preserve raw fields"
            )
        matches: list[int | None] = []
        used: set[int] = set()
        for value in after:
            candidates = [i for i, old in enumerate(before) if i not in used and _equal(old, value)]
            if len(candidates) > 1 and any(
                not _equal(raw[candidates[0]], raw[i]) for i in candidates[1:]
            ):
                raise ValueError(
                    "Cannot safely distinguish duplicate array elements containing unknown fields"
                )
            matched_index = candidates[0] if candidates else None
            matches.append(matched_index)
            if matched_index is not None:
                used.add(matched_index)
        if len(before) == len(after) and all(i is None or i == j for j, i in enumerate(matches)):
            if matches.count(None) > 1 and any(
                _unknown(raw[i], before[i]) for i, match in enumerate(matches) if match is None
            ):
                raise ValueError(
                    "Cannot safely match multiple changed unnamed array elements containing unknown fields"
                )
            return [
                _overlay(
                    value,
                    old,
                    new,
                    explicit_before[index] if isinstance(explicit_before, list) else _MISSING,
                    explicit_after[index] if isinstance(explicit_after, list) else _MISSING,
                )
                for index, (value, old, new) in enumerate(zip(raw, before, after, strict=True))
            ]
        if any(i is None for i in matches) and any(
            _unknown(raw[i], old) for i, old in enumerate(before) if i not in used
        ):
            raise ValueError(
                "Cannot safely match changed array elements with unknown fields; "
                "edit elements in place or separate structural edits"
            )
        return [
            _overlay(
                raw[i],
                before[i],
                value,
                explicit_before[i] if isinstance(explicit_before, list) else _MISSING,
                explicit_after[index] if isinstance(explicit_after, list) else _MISSING,
            )
            if i is not None
            else deepcopy(value)
            for index, (i, value) in enumerate(zip(matches, after, strict=True))
        ]
    return deepcopy(after)


def mutation_patch(raw: dict[str, Any], before: Resource, after: Resource) -> list[dict[str, Any]]:
    """Diff only callback changes; preserve unmodeled fields and unmodified defaults."""
    old = before.model_dump(mode="json", by_alias=True)
    new = after.model_dump(mode="json", by_alias=True)
    if before.api_version != after.api_version or before.kind != after.kind:
        raise ValueError("An admission mutator cannot change apiVersion or kind")
    old_meta, new_meta = old.get("metadata") or {}, new.get("metadata") or {}
    for key in ("name", "namespace", "uid", "resourceVersion"):
        if old_meta.get(key) != new_meta.get(key):
            raise ValueError(f"An admission mutator cannot change metadata.{key}")
    desired = _overlay(
        raw,
        old,
        new,
        before.model_dump(mode="json", by_alias=True, exclude_unset=True),
        after.model_dump(mode="json", by_alias=True, exclude_unset=True),
    )
    return json_patch(raw, desired)
