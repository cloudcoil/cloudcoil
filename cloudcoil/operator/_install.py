"""Ordered, idempotent operator installation using server-side apply."""

import asyncio
import json
from typing import Any
from urllib.parse import quote

from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status

_ENDPOINTS = {
    ("apiextensions.k8s.io/v1", "CustomResourceDefinition"): ("customresourcedefinitions", False),
    ("v1", "ServiceAccount"): ("serviceaccounts", True),
    ("v1", "Service"): ("services", True),
    ("rbac.authorization.k8s.io/v1", "Role"): ("roles", True),
    ("rbac.authorization.k8s.io/v1", "RoleBinding"): ("rolebindings", True),
    ("rbac.authorization.k8s.io/v1", "ClusterRole"): ("clusterroles", False),
    ("rbac.authorization.k8s.io/v1", "ClusterRoleBinding"): ("clusterrolebindings", False),
    ("apps/v1", "Deployment"): ("deployments", True),
    ("admissionregistration.k8s.io/v1", "MutatingWebhookConfiguration"): (
        "mutatingwebhookconfigurations",
        False,
    ),
    ("admissionregistration.k8s.io/v1", "ValidatingWebhookConfiguration"): (
        "validatingwebhookconfigurations",
        False,
    ),
}


def _url(manifest: dict[str, Any]) -> str:
    version = manifest["apiVersion"]
    plural, namespaced = _ENDPOINTS[(version, manifest["kind"])]
    root = f"/apis/{version}" if "/" in version else f"/api/{version}"
    if namespaced:
        root += f"/namespaces/{quote(manifest['metadata']['namespace'], safe='')}"
    return f"{root}/{plural}/{quote(manifest['metadata']['name'], safe='')}"


async def _wait(config: Config, manifest: dict[str, Any]) -> None:
    kind = manifest["kind"]
    while True:
        response = await config.async_client.get(_url(manifest))
        raise_for_status(response)
        obj = response.json()
        status = obj.get("status") or {}
        conditions = status.get("conditions") or []
        if kind == "CustomResourceDefinition":
            if any(
                c.get("type") == "NamesAccepted" and c.get("status") == "False" for c in conditions
            ):
                raise RuntimeError(f"CRD name rejected: {manifest['metadata']['name']}")
            if any(
                c.get("type") == "Established" and c.get("status") == "True" for c in conditions
            ):
                return
        elif (
            status.get("observedGeneration", 0) >= obj["metadata"].get("generation", 1)
            and status.get("availableReplicas", 0) >= manifest["spec"].get("replicas", 1)
            and status.get("updatedReplicas", 0) >= manifest["spec"].get("replicas", 1)
            # Available old pods cannot establish readiness for a new revision.
            # During a rolling update both counts above can be satisfied while
            # every updated pod is unready and only the old pods serve traffic.
            and status.get("replicas", 0) == status.get("updatedReplicas", 0)
        ):
            return
        await asyncio.sleep(0.2)


async def install(
    config: Config,
    manifests: list[dict[str, Any]],
    *,
    field_manager: str,
    timeout: float,
    force: bool,
    wait_deployment: bool,
) -> None:
    """Establish CRDs before refreshing discovery, then enable admission last."""
    async with asyncio.timeout(timeout):
        crds = [m for m in manifests if m["kind"] == "CustomResourceDefinition"]
        rest = [m for m in manifests if m["kind"] != "CustomResourceDefinition"]
        for manifest in [*crds, *rest]:
            response = await config.async_client.patch(
                _url(manifest),
                params={"fieldManager": field_manager, "force": str(force).lower()},
                headers={"Content-Type": "application/apply-patch+yaml"},
                content=json.dumps(manifest),
            )
            raise_for_status(response)
            if manifest["kind"] == "CustomResourceDefinition":
                await _wait(config, manifest)
            elif manifest["kind"] == "Deployment" and wait_deployment:
                await _wait(config, manifest)
        if crds:
            await asyncio.to_thread(config.refresh_api_resources)
