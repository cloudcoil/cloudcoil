"""Resolve Pod ancestry using UID-checked Kubernetes owner references."""

import re
from collections.abc import Generator
from contextlib import closing
from typing import Any
from urllib.parse import quote

import httpx

from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status
from cloudcoil.resources import GVK

type _Steps[T] = Generator[tuple[str, bool], dict[str, Any] | None, T]

_METADATA_HEADERS = {
    "Accept": "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1,application/json;q=0.9"
}


def _api_path(api_version: str) -> str:
    if not re.fullmatch(r"(?:[a-z0-9][a-z0-9.-]*/)?[a-z][a-z0-9]*", api_version):
        raise ValueError(f"Invalid owner apiVersion: {api_version!r}")
    return f"/apis/{api_version}" if "/" in api_version else f"/api/{api_version}"


def _segment(value: str) -> str:
    if not value or value in (".", "..") or "/" in value or "%" in value:
        raise ValueError(f"Invalid owner resource path segment: {value!r}")
    return quote(value, safe="")


def _body(response: httpx.Response) -> dict[str, Any] | None:
    # A removed intermediate object breaks that ownership path. Other failures,
    # especially RBAC, cannot be treated as evidence of no matching descendants.
    if response.status_code == 404:
        return None
    raise_for_status(response)
    return response.json()


class OwnerTraversal:
    """Per-discovery caches shared across Pods; no stale cross-call ownership cache.

    The traversal generator shares the graph algorithm between sync/async callers;
    each driver executes its yielded GET requests with the appropriate HTTP client.
    """

    def __init__(self, config: Config, target: dict[str, Any]):
        self.config = config
        self.target = target
        self.responses: dict[str, dict[str, Any] | None] = {}
        self.mappings: dict[GVK, tuple[str, bool] | None] = {}
        if not (target.get("metadata") or {}).get("uid"):
            raise ValueError(
                "Ownership discovery needs metadata.uid; fetch the resource first "
                "or provide label_selector= with its Pod labels"
            )

    def _is_target(self, ref: dict[str, Any], namespace: str | None) -> bool:
        meta = self.target["metadata"]
        return (
            ref.get("uid") == meta["uid"]
            and ref.get("name") == meta["name"]
            and ref.get("kind") == self.target["kind"]
            and ref.get("apiVersion", "").rpartition("/")[0]
            == self.target["apiVersion"].rpartition("/")[0]
            and (not meta.get("namespace") or meta["namespace"] == namespace)
        )

    def _get(self, url: str, *, metadata: bool = False) -> _Steps[dict[str, Any] | None]:
        if url not in self.responses:
            self.responses[url] = yield url, metadata
        return self.responses[url]

    def _mapping(self, gvk: GVK) -> _Steps[tuple[str, bool] | None]:
        if gvk not in self.mappings:
            known = self.config._rest_mapping.get(gvk)
            if known is not None:
                self.mappings[gvk] = (known["resource"], known["namespaced"])
            else:
                # Discover only the referenced group/version, not every CRD in the cluster.
                discovery = yield from self._get(_api_path(gvk.api_version))
                matches = [
                    item
                    for item in (discovery or {}).get("resources", [])
                    if item.get("kind") == gvk.kind and "/" not in item.get("name", "")
                ]
                if len(matches) > 1:
                    raise ValueError(f"Ambiguous owner resource mapping for {gvk}")
                self.mappings[gvk] = (
                    (matches[0]["name"], matches[0]["namespaced"]) if matches else None
                )
        return self.mappings[gvk]

    def _trace(self, pod: dict[str, Any]) -> _Steps[bool]:
        pending = [pod["metadata"]]
        visited: set[tuple[str, str | None]] = set()
        while pending:
            meta = pending.pop()
            namespace = meta.get("namespace")
            refs = meta.get("ownerReferences") or []
            if any(self._is_target(ref, namespace) for ref in refs):
                return True
            for ref in refs:
                uid = ref.get("uid")
                if not uid or (uid, namespace) in visited:
                    continue
                visited.add((uid, namespace))
                gvk = GVK(api_version=ref["apiVersion"], kind=ref["kind"])
                mapping = yield from self._mapping(gvk)
                if mapping is None:
                    continue
                plural, namespaced = mapping
                if namespaced and namespace is None:
                    continue  # A cluster-scoped dependent cannot have a namespaced owner.
                scope = f"/namespaces/{_segment(namespace)}" if namespaced and namespace else ""
                url = f"{_api_path(gvk.api_version)}{scope}/{_segment(plural)}/{_segment(ref['name'])}"
                owner = yield from self._get(url, metadata=True)
                if owner is None:
                    continue
                owner_meta = owner.get("metadata") or {}
                if owner_meta.get("uid") != uid:
                    continue  # Same name, new object: the old dependent does not belong to it.
                # The discovered scope, not caller-supplied metadata, determines the next hop.
                pending.append({**owner_meta, "namespace": namespace if namespaced else None})
        return False

    def matches(self, pod: dict[str, Any]) -> bool:
        with closing(self._trace(pod)) as traversal:
            response = None
            while True:
                try:
                    url, metadata = traversal.send(response)
                except StopIteration as done:
                    return done.value
                response = _body(
                    self.config.client.get(url, headers=_METADATA_HEADERS if metadata else None)
                )

    async def async_matches(self, pod: dict[str, Any]) -> bool:
        with closing(self._trace(pod)) as traversal:
            response = None
            while True:
                try:
                    url, metadata = traversal.send(response)
                except StopIteration as done:
                    return done.value
                response = _body(
                    await self.config.async_client.get(
                        url, headers=_METADATA_HEADERS if metadata else None
                    )
                )
