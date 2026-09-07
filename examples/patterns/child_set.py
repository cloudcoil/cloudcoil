"""A variable set of owned ConfigMaps, including guarded pruning when entries disappear."""

from hashlib import sha256

from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.application import Application, RBACRule
from cloudcoil.controller import Controller, Request
from cloudcoil.crd import custom_resource
from cloudcoil.errors import ResourceNotFound
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

OWNER = "patterns.cloudcoil.dev/bundle-uid"


class BundleSpec(BaseModel):
    entries: dict[str, str] = Field(default_factory=dict)


@custom_resource(api_version="patterns.cloudcoil.dev/v1alpha1", plural="bundles")
class Bundle(Resource):
    spec: BundleSpec


async def reconcile(request: Request[Bundle]) -> None:
    obj = request.resource
    if not obj or not obj.metadata or not obj.metadata.uid or obj.metadata.deletion_timestamp:
        return
    uid = obj.metadata.uid
    desired = set()
    for key, value in obj.spec.entries.items():
        name = "bundle-" + sha256(f"{uid}/{key}".encode()).hexdigest()
        desired.add(name)
        await request.ensure(
            ConfigMap.model_validate(
                {
                    "metadata": {
                        "name": name,
                        "labels": {OWNER: uid},
                        "annotations": {"patterns.cloudcoil.dev/entry": key},
                    },
                    "data": {"value": value},
                }
            )
        )
    client = await request.client(ConfigMap)
    for child in request.cached(ConfigMap).list(labels={OWNER: uid}):
        if not child.name or child.name in desired or not child.metadata:
            continue
        if not any(
            ref.controller and ref.uid == uid for ref in child.metadata.owner_references or []
        ):
            continue  # A copied label is not proof of ownership.
        try:
            # The API server verifies the cached identity/version before deletion.
            # A replacement or concurrent update conflicts and causes reconciliation to retry.
            await client.delete(
                child.name, uid=child.metadata.uid, resource_version=child.resource_version
            )
        except ResourceNotFound:
            pass


def build_app() -> Application:
    return Application(
        "bundles",
        Controller(Bundle, reconcile).owns(ConfigMap),
        rules=(RBACRule(ConfigMap, ("delete",)),),
    )


if __name__ == "__main__":
    build_app().main()
