"""Schema-only Kubernetes inference, independent of the Python code emitter."""

import keyword
import re
from copy import deepcopy
from typing import Any, Iterator


class SchemaError(ValueError):
    """An input cannot be translated without losing schema information."""


def walk_schemas(node: Any) -> Iterator[dict]:
    """Visit schema nodes, never examples/defaults or arbitrary extension payloads."""
    if not isinstance(node, dict):
        return
    yield node
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        for child in node.get(key, {}).values():
            yield from walk_schemas(child)
    for key in (
        "items",
        "additionalProperties",
        "additionalItems",
        "not",
        "if",
        "then",
        "else",
        "contains",
    ):
        child = node.get(key)
        if isinstance(child, list):
            for item in child:
                yield from walk_schemas(item)
        else:
            yield from walk_schemas(child)
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for child in node.get(key, []):
            yield from walk_schemas(child)


def pointer_name(name: str) -> str:
    return name.replace("~", "~0").replace("/", "~1")


def rewrite_refs(node: Any, mapping: dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {
            key: mapping.get(value, value)
            if key == "$ref" and isinstance(value, str)
            else rewrite_refs(value, mapping)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [rewrite_refs(value, mapping) for value in node]
    return node


def python_name(name: str) -> str:
    name = re.sub(r"\W", "_", name)
    if not name or name[0].isdigit():
        name = "_" + name
    return name + "_" if keyword.iskeyword(name) else name


def inferred_name(name: str, namespace: str, crd_groups: set[str]) -> str:
    # These are Cloudcoil's canonical, already supplied Kubernetes scalar/metadata types.
    match = re.match(r"io\.k8s\.apimachinery\..*\.(\w+)$", name)
    if match:
        from cloudcoil import apimachinery

        if hasattr(apimachinery, match[1]):
            return f"cloudcoil.apimachinery.{match[1]}"
    for prefix, replacement in (
        ("io.k8s.api.", ""),
        ("io.k8s.apiextensions-apiserver.pkg.apis.apiextensions.", "apiextensions."),
        ("io.k8s.kube-aggregator.pkg.apis.", ""),
    ):
        if name.startswith(prefix):
            name = replacement + name[len(prefix) :]
            break
    else:
        for group in sorted(crd_groups, key=len, reverse=True):
            prefix = ".".join(reversed(group.split("."))) + "."
            if name.startswith(prefix):
                suffix = name[len(prefix) :]
                name = suffix if len(crd_groups) == 1 else f"{python_name(group)}.{suffix}"
                break
    return namespace + "." + ".".join(python_name(part) for part in name.split("."))


def normalize_definition(definition: dict) -> None:
    for node in walk_schemas(definition):
        if node.get("x-kubernetes-int-or-string") or node.get("format") == "int-or-string":
            node["type"] = ["integer", "string"]
            node.pop("format", None)
        # A format is only meaningful for its primitive type. Several CRDs emit
        # e.g. an integer field with format: duration. Don't change the field's type.
        formats = {
            "int32": "integer",
            "int64": "integer",
            "float": "number",
            "double": "number",
            "date": "string",
            "date-time": "string",
            "duration": "string",
            "byte": "string",
            "binary": "string",
            "uuid": "string",
            "password": "string",
        }
        if node.get("format") in formats and node.get("type") != formats[node["format"]]:
            node.pop("format")
        if node.get("nullable"):
            node.pop("nullable")
            type_ = node.get("type")
            if isinstance(type_, str):
                node["type"] = [type_, "null"]
            elif isinstance(type_, list) and "null" not in type_:
                node["type"] = [*type_, "null"]
            elif type_ is None and ("$ref" in node or "anyOf" in node or "oneOf" in node):
                original = deepcopy(node)
                node.clear()
                node["anyOf"] = [original, {"type": "null"}]
        if node.get("x-kubernetes-preserve-unknown-fields"):
            node.setdefault("type", "object")
            node.setdefault("additionalProperties", True)
        if node.get("x-kubernetes-embedded-resource"):
            node.setdefault("type", "object")
            props = node.setdefault("properties", {})
            props.setdefault("apiVersion", {"type": "string"})
            props.setdefault("kind", {"type": "string"})
            props.setdefault("metadata", {"type": "object", "additionalProperties": True})


def lift_inline_objects(definitions: dict, prefix: str) -> None:
    """Give nested objects stable path-based identities instead of global title guesses."""

    def visit(node: dict, name: str):
        for key in ("properties", "patternProperties"):
            for field, child in list(node.get(key, {}).items()):
                if isinstance(child, dict):
                    lift(child, name + re.sub(r"[^A-Za-z0-9]", "", field[:1].upper() + field[1:]))
        for key in ("items", "additionalProperties"):
            child = node.get(key)
            if isinstance(child, dict):
                lift(child, name + ("Item" if key == "items" else "Value"))
        for key in ("allOf", "anyOf", "oneOf"):
            for i, child in enumerate(node.get(key, [])):
                if isinstance(child, dict):
                    lift(child, name + key[:1].upper() + key[1:] + str(i + 1))

    def lift(node: dict, name: str):
        if "properties" in node and "$ref" not in node:
            candidate = name
            index = 2
            while candidate in definitions:
                candidate = name + str(index)
                index += 1
            # Defaults and descriptions belong to the field, not just its model.
            field_data = {
                key: deepcopy(node[key]) for key in ("default", "description") if key in node
            }
            definition = deepcopy(node)
            definition.pop("default", None)
            definitions[candidate] = definition
            node.clear()
            node.update({"$ref": prefix + pointer_name(candidate), **field_data})
            visit(definition, candidate)
        else:
            visit(node, name)

    for name, definition in list(definitions.items()):
        visit(definition, name)


def infer_resource_identities(schema: dict, definitions: dict) -> None:
    """Infer missing GVKs from Kubernetes API paths and direct request/response refs."""
    candidates: dict[str, list[dict[str, str]]] = {}

    def add_refs(node, group, version):
        if isinstance(node, list):
            for child in node:
                add_refs(child, group, version)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(
                ("#/definitions/", "#/components/schemas/", "#/$defs/")
            ):
                name = ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
                definition = definitions.get(name, {})
                props = definition.get("properties", {})
                if {"apiVersion", "kind", "metadata"} <= props.keys() and not definition.get(
                    "x-kubernetes-group-version-kind"
                ):
                    kind = props["kind"].get("default") or name.rsplit(".", 1)[-1]
                    gvk = {"group": group, "version": version, "kind": kind}
                    if gvk not in candidates.setdefault(name, []):
                        candidates[name].append(gvk)
            for child in node.values():
                add_refs(child, group, version)

    for path, operations in schema.get("paths", {}).items():
        match = re.match(r"^/apis/([^/]+)/([^/]+)/", path)
        core = re.match(r"^/api/([^/]+)/", path)
        if match:
            add_refs(operations, match[1], match[2])
        elif core:
            add_refs(operations, "", core[1])
    for name, values in candidates.items():
        definitions[name]["x-kubernetes-group-version-kind"] = values
    families: dict[str, set[str]] = {}
    versioned = re.compile(r"^(.*)\.(v\d+(?:(?:alpha|beta)\d+)?)\.([^.]+)$")
    for name, definition in definitions.items():
        match = versioned.match(name)
        gvks = definition.get("x-kubernetes-group-version-kind", [])
        if match and len(gvks) == 1 and gvks[0]["version"] == match[2]:
            families.setdefault(match[1], set()).add(gvks[0]["group"])
    for name, definition in definitions.items():
        if definition.get("x-kubernetes-group-version-kind"):
            continue
        props = definition.get("properties", {})
        match = versioned.match(name)
        if (
            match
            and len(families.get(match[1], set())) == 1
            and {"apiVersion", "kind", "metadata"} <= props.keys()
        ):
            definition["x-kubernetes-group-version-kind"] = [
                {
                    "group": next(iter(families[match[1]])),
                    "version": match[2],
                    "kind": match[3],
                }
            ]
            continue
        if "metadata" not in props:
            continue
        identity = {}
        for key in ("apiVersion", "kind"):
            field = props.get(key, {})
            identity[key] = (
                field.get("const")
                or field.get("default")
                or (field["enum"][0] if len(field.get("enum", [])) == 1 else None)
            )
        if all(isinstance(value, str) and value for value in identity.values()):
            version = identity["apiVersion"]
            assert isinstance(version, str)
            group, _, version = version.rpartition("/")
            definition["x-kubernetes-group-version-kind"] = [
                {"group": group, "version": version, "kind": identity["kind"]}
            ]
