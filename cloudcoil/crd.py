"""Generate single-version Kubernetes CRDs from the models used by controllers.

Pydantic validators are Python code: use a validation webhook or explicit CEL
rules for checks that cannot be represented by the model's JSON Schema.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cloudcoil.resources import Resource

__all__ = ["CRD", "PrinterColumn", "SchemaError"]


class SchemaError(ValueError):
    """A model cannot be represented faithfully as a structural CRD schema."""


class PrinterColumn(BaseModel):
    """A kubectl get column; paths use serialized Kubernetes field names."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1)
    json_path: str
    type: Literal["string", "integer", "number", "boolean", "date"] = "string"
    description: str | None = None
    format: str | None = None
    priority: int = Field(default=0, ge=0)

    @field_validator("json_path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith(".") or any(char in value for char in "\n\r"):
            raise ValueError("json_path must start with '.' and contain no newline")
        return value

    def _manifest(self) -> dict[str, Any]:
        result = self.model_dump(exclude_none=True)
        result["jsonPath"] = result.pop("json_path")
        return result


_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?\Z")
_NAME = re.compile(r"[a-z](?:[-a-z0-9]*[a-z0-9])?\Z")
_KIND = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_KEYWORDS = {
    "type",
    "properties",
    "items",
    "additionalProperties",
    "required",
    "nullable",
    "title",
    "description",
    "default",
    "enum",
    "format",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
    "example",
    "externalDocs",
    "x-kubernetes-preserve-unknown-fields",
    "x-kubernetes-embedded-resource",
    "x-kubernetes-int-or-string",
    "x-kubernetes-list-type",
    "x-kubernetes-list-map-keys",
    "x-kubernetes-map-type",
    "x-kubernetes-validations",
}
_ANNOTATIONS = {"title", "description", "default", "example"}


def _error(path: str, message: str) -> SchemaError:
    return SchemaError(f"{path}: {message}")


def _merge(base: dict[str, Any], extra: dict[str, Any], path: str) -> dict[str, Any]:
    for key, value in extra.items():
        if key in base and base[key] != value and key not in _ANNOTATIONS:
            raise _error(path, f"conflicting {key!r} constraints around a reference or union")
        base[key] = value
    return base


def _convert(
    raw: Any, definitions: dict[str, Any], path: str, refs: tuple[str, ...] = ()
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _error(path, "boolean schemas are unsupported")
    node = copy.deepcopy(raw)
    if "$ref" in node:
        ref = node.pop("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise _error(path, f"only local $defs references are supported: {ref!r}")
        name = ref[len("#/$defs/") :].replace("~1", "/").replace("~0", "~")
        if name in refs:
            raise _error(path, f"recursive schema reference {name!r} is unsupported")
        if name not in definitions:
            raise _error(path, f"unresolved schema reference {name!r}")
        expanded = _merge(copy.deepcopy(definitions[name]), node, path)
        return _convert(expanded, definitions, path, (*refs, name))
    if "anyOf" in node:
        variants = node.pop("anyOf")
        if not isinstance(variants, list):
            raise _error(path, "anyOf must be a list")
        nullable = any(variant == {"type": "null"} for variant in variants)
        branches = [variant for variant in variants if variant != {"type": "null"}]
        if len(branches) == 1:
            branch = _convert(branches[0], definitions, path, refs)
            converted = _convert(node, definitions, path, refs) if "type" in node else node
            result = _merge(branch, converted, path)
            if nullable:
                result["nullable"] = True
            # Process merged annotations/extensions, without reintroducing a union.
            return _convert(result, definitions, path, refs)
        if (
            len(branches) == 2
            and {"type": "integer"} in branches
            and {"type": "string"} in branches
        ):
            node["x-kubernetes-int-or-string"] = True
            if nullable:
                node["nullable"] = True
        else:
            raise _error(path, "unions must be T | None or unconstrained int | str")
    if isinstance(node.get("type"), list):
        types = node["type"]
        non_null = [item for item in types if item != "null"]
        if "null" not in types or len(non_null) != 1:
            raise _error(path, "mixed-type enums/unions are unsupported")
        node["type"] = non_null[0]
        node["nullable"] = True
    if "const" in node:
        value = node.pop("const")
        if "enum" in node and value not in node["enum"]:
            raise _error(path, "const conflicts with enum")
        node["enum"] = [value]
    for bound, inclusive in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        value = node.get(bound)
        if value is not None and not isinstance(value, bool):
            if inclusive in node:
                old = node[inclusive]
                if (bound == "exclusiveMinimum" and old > value) or (
                    bound == "exclusiveMaximum" and old < value
                ):
                    node.pop(bound)
                    continue
            node[inclusive] = value
            node[bound] = True
    if node.pop("uniqueItems", False):
        raise _error(
            path,
            "uniqueItems/set types are unsupported; use a list with x-kubernetes-list-type='set'",
        )
    if "examples" in node:
        examples = node.pop("examples")
        if examples and "example" not in node:
            node["example"] = examples[0]
    unsupported = node.keys() - _KEYWORDS
    if unsupported:
        raise _error(path, f"unsupported schema keywords: {', '.join(sorted(unsupported))}")
    if node.get("type") == "null":
        raise _error(path, "null-only fields are unsupported; use an optional concrete type")
    if "type" in node and node["type"] not in (
        "object",
        "array",
        "string",
        "number",
        "integer",
        "boolean",
    ):
        raise _error(path, "type must be a supported OpenAPI primitive")
    if node.get("type") == "array" and "items" not in node:
        raise _error(path, "arrays require an items schema")
    additional = node.get("additionalProperties")
    if additional is False:
        raise _error(
            path,
            "additionalProperties=false is forbidden by Kubernetes; use pruning or a webhook instead of extra='forbid'",
        )
    if additional is True:
        node.pop("additionalProperties")
        node["x-kubernetes-preserve-unknown-fields"] = True
    elif isinstance(additional, dict):
        if node.get("properties"):
            raise _error(path, "properties and additionalProperties cannot coexist in a CRD")
        node["additionalProperties"] = _convert(additional, definitions, f"{path}.*", refs)
    if "properties" in node:
        props = node["properties"]
        if node.get("x-kubernetes-embedded-resource"):
            props["metadata"] = {"type": "object"}
        node["properties"] = {
            name: _convert(value, definitions, f"{path}.{name}", refs)
            for name, value in props.items()
        }
    if "items" in node:
        node["items"] = _convert(node["items"], definitions, f"{path}[]", refs)
    if "type" not in node and not node.get("x-kubernetes-int-or-string"):
        # An unconstrained JSON Schema is precisely Pydantic's Any type.
        if node.keys() - (_ANNOTATIONS | {"nullable", "x-kubernetes-preserve-unknown-fields"}):
            raise _error(path, "constraints require an explicit structural type")
        node["x-kubernetes-preserve-unknown-fields"] = True
        node["nullable"] = True
    _extensions(node, path)
    if node.get("x-kubernetes-int-or-string"):
        node["anyOf"] = [{"type": "integer"}, {"type": "string"}]
    return node


def _extensions(node: dict[str, Any], path: str) -> None:
    for key in (
        "x-kubernetes-preserve-unknown-fields",
        "x-kubernetes-embedded-resource",
        "x-kubernetes-int-or-string",
    ):
        if key in node and node[key] is not True:
            raise _error(path, f"{key} must be true when specified")
    if node.get("x-kubernetes-embedded-resource") and node.get("type") != "object":
        raise _error(path, "embedded resources require type object")
    if node.get("x-kubernetes-int-or-string") and "type" in node:
        raise _error(path, "int-or-string must not specify type")
    if "x-kubernetes-map-type" in node:
        if node.get("type") != "object" or node["x-kubernetes-map-type"] not in (
            "atomic",
            "granular",
        ):
            raise _error(path, "map-type requires an object and must be atomic or granular")
    list_type = node.get("x-kubernetes-list-type")
    if list_type is not None:
        if node.get("type") != "array" or list_type not in ("atomic", "set", "map"):
            raise _error(path, "list-type requires an array and must be atomic, set or map")
        items = node.get("items", {})
        if list_type in ("set", "map") and items.get("nullable"):
            raise _error(path, "set/map list items cannot be nullable")
        if list_type == "map":
            keys = node.get("x-kubernetes-list-map-keys")
            if items.get("type") != "object" or not isinstance(keys, list) or not keys:
                raise _error(path, "map lists need object items and nonempty list-map-keys")
            for key in keys:
                field = items.get("properties", {}).get(key, {})
                if field.get("type") not in ("string", "integer", "number", "boolean") or field.get(
                    "nullable"
                ):
                    raise _error(
                        path, f"list map key {key!r} must be a nonnullable scalar property"
                    )
                if key not in items.get("required", []) and "default" not in field:
                    raise _error(path, f"list map key {key!r} must be required or have a default")
        if list_type == "set" and items.get("type") in ("object", "array"):
            extension = (
                "x-kubernetes-map-type" if items["type"] == "object" else "x-kubernetes-list-type"
            )
            if items.get(extension) != "atomic":
                raise _error(path, "set list object/array items must be atomic")
    if "x-kubernetes-list-map-keys" in node and list_type != "map":
        raise _error(path, "list-map-keys requires list-type='map'")
    if "x-kubernetes-validations" in node:
        rules = node["x-kubernetes-validations"]
        if not isinstance(rules, list) or any(
            not isinstance(rule, dict)
            or not isinstance(rule.get("rule"), str)
            or not rule["rule"].strip()
            for rule in rules
        ):
            raise _error(path, "validations must be a list of nonempty CEL rules")


def _check_models(model: type[BaseModel], seen: set[type[BaseModel]]) -> None:
    if model in seen:
        return
    seen.add(model)
    if model.model_computed_fields:
        raise _error(model.__name__, "computed fields are unsupported in stored resource models")
    decorators = model.__pydantic_decorators__
    if decorators.field_serializers or decorators.model_serializers:
        raise _error(
            model.__name__, "custom serializers require an explicit schema and are unsupported"
        )
    for name, field in model.model_fields.items():
        validation_name = field.validation_alias or field.alias or name
        serialization_name = field.serialization_alias or field.alias or name
        if not isinstance(validation_name, str) or validation_name != serialization_name:
            raise _error(
                f"{model.__name__}.{name}", "validation and serialization aliases must match"
            )
        if field.exclude or field.exclude_if is not None:
            raise _error(
                f"{model.__name__}.{name}",
                "excluded fields are unsupported in stored resource models",
            )
        pending = [field.annotation]
        while pending:
            annotation = pending.pop()
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                _check_models(annotation, seen)
            else:
                pending.extend(get_args(annotation))


class CRD:
    """A single served/storage version derived from a controller Resource model.

    The plural is explicit; group, version and kind come from ``resource.gvk()``.
    Status is enabled automatically when the model has an optional status field.
    Passing ``columns=[]`` disables the default Age column. No cluster writes occur.
    """

    def __init__(
        self,
        resource: type[Resource],
        *,
        plural: str,
        scope: Literal["Namespaced", "Cluster"] = "Namespaced",
        singular: str | None = None,
        short_names: Sequence[str] = (),
        categories: Sequence[str] = (),
        status: bool | None = None,
        columns: Sequence[PrinterColumn] | None = None,
    ) -> None:
        if not isinstance(resource, type) or not issubclass(resource, Resource):
            raise TypeError("resource must be a Resource subclass")
        gvk = resource.gvk()
        group, version, kind = gvk.group, gvk.version, gvk.kind
        if gvk.api_version != f"{group}/{version}":
            raise ValueError("api_version must have exactly one group/version separator")
        if (
            not group
            or len(group) > 253
            or any(len(label) > 63 or not _LABEL.fullmatch(label) for label in group.split("."))
        ):
            raise ValueError("CRDs require an api_version with a valid DNS group and version")
        if not _NAME.fullmatch(version) or len(version) > 63:
            raise ValueError("CRD version must be a DNS label starting with a letter")
        if not _KIND.fullmatch(kind):
            raise ValueError("CRD kind must be an alphanumeric identifier starting with a letter")
        singular = singular if singular is not None else kind.lower()
        for label, value in (("plural", plural), ("singular", singular)):
            if not _NAME.fullmatch(value) or len(value) > 63:
                raise ValueError(f"{label} must be a DNS label starting with a letter")
        if len(f"{plural}.{group}") > 253:
            raise ValueError("CRD metadata.name exceeds 253 characters")
        if scope not in ("Namespaced", "Cluster"):
            raise ValueError("scope must be Namespaced or Cluster")
        for label, values in (("short_names", short_names), ("categories", categories)):
            if isinstance(values, str) or any(
                len(value) > 63 or not _LABEL.fullmatch(value) for value in values
            ):
                raise ValueError(f"{label} must contain DNS label names")
        _check_models(resource, set())
        api_field = resource.model_fields["api_version"]
        if (api_field.serialization_alias or api_field.alias) != "apiVersion":
            raise SchemaError("api_version must declare Field(default=..., alias='apiVersion')")
        raw = copy.deepcopy(resource.model_json_schema(by_alias=True, mode="validation"))
        definitions = raw.pop("$defs", {})
        properties = raw.get("properties", {})
        if "kind" not in properties or "metadata" not in properties:
            raise SchemaError("kind and metadata must retain their Kubernetes field names")
        properties["apiVersion"] = {"type": "string"}
        properties["kind"] = {"type": "string"}
        properties["metadata"] = {"type": "object"}
        schema = _convert(raw, definitions, resource.__name__)
        enabled = "status" in properties if status is None else status
        if enabled:
            if "status" not in properties:
                raise SchemaError("status=True requires a status field on the resource model")
            if "status" in schema.get("required", []):
                raise SchemaError(
                    "status must be optional (for example Status | None = None) because the status subresource strips it on create"
                )
            if schema["properties"]["status"].get("type") != "object":
                raise SchemaError("status must be an object or optional object")
        version_spec: dict[str, Any] = {
            "name": version,
            "served": True,
            "storage": True,
            "schema": {"openAPIV3Schema": schema},
        }
        if enabled:
            version_spec["subresources"] = {"status": {}}
        if columns is None:
            columns = [
                PrinterColumn(name="Age", json_path=".metadata.creationTimestamp", type="date")
            ]
        if columns:
            version_spec["additionalPrinterColumns"] = [column._manifest() for column in columns]
        names: dict[str, Any] = {
            "plural": plural,
            "singular": singular,
            "kind": kind,
            "listKind": f"{kind}List",
        }
        if short_names:
            names["shortNames"] = list(short_names)
        if categories:
            names["categories"] = list(categories)
        self.resource = resource
        self.plural = plural
        self.scope = scope
        self._manifest: dict[str, Any] = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": f"{plural}.{group}"},
            "spec": {"group": group, "scope": scope, "names": names, "versions": [version_spec]},
        }

    def manifest(self) -> dict[str, Any]:
        """Return an independent manifest suitable for YAML export or API submission."""
        return copy.deepcopy(self._manifest)

    def to_yaml(self) -> str:
        """Serialize the CRD as one YAML document without Python-specific tags."""
        return yaml.safe_dump(self._manifest, sort_keys=False)
