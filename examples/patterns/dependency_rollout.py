"""Restart opted-in Deployments when referenced ConfigMaps change; never own the ConfigMaps."""

import hashlib
import json

from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.application import Application
from cloudcoil.controller import Controller, Request, ResourceKey

LABEL = "patterns.cloudcoil.dev/reloader"
DIGEST = "patterns.cloudcoil.dev/config-digest"


def references(deployment: Deployment) -> set[str]:
    """ConfigMaps referenced by volumes (including projected volumes), envFrom and env values."""
    if not deployment.spec or not deployment.spec.template.spec:
        return set()
    pod = deployment.spec.template.spec
    names = {
        volume.config_map.name
        for volume in pod.volumes or []
        if volume.config_map and volume.config_map.name
    }
    names.update(
        source.config_map.name
        for volume in pod.volumes or []
        if volume.projected
        for source in volume.projected.sources or []
        if source.config_map and source.config_map.name
    )
    for container in [*pod.containers, *(pod.init_containers or [])]:
        names.update(
            source.config_map_ref.name
            for source in container.env_from or []
            if source.config_map_ref and source.config_map_ref.name
        )
        names.update(
            env.value_from.config_map_key_ref.name
            for env in container.env or []
            if env.value_from
            and env.value_from.config_map_key_ref
            and env.value_from.config_map_key_ref.name
        )
    return names


async def reconcile(request: Request[Deployment]) -> Deployment | None:
    obj = request.resource
    if not obj or not obj.spec or not obj.metadata or obj.metadata.deletion_timestamp:
        return None
    configs = request.cached(ConfigMap)
    inputs = {}
    for name in sorted(references(obj)):
        config = configs.get(name)
        inputs[name] = {"data": config.data, "binaryData": config.binary_data} if config else None
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    from cloudcoil.apimachinery import ObjectMeta

    if obj.spec.template.metadata is None:
        obj.spec.template.metadata = ObjectMeta()
    obj.spec.template.metadata.annotations = {
        **(obj.spec.template.metadata.annotations or {}),
        DIGEST: digest,
    }
    return obj  # Only the pod-template annotation is patched. Identical inputs are a no-op.


def controller() -> Controller[Deployment]:
    workload = Controller(Deployment, reconcile, label_selector=f"{LABEL}=true")

    def dependents(config: ConfigMap) -> list[ResourceKey]:
        # Primary sync precedes secondary handlers. Updates map both old and new objects.
        return [
            ResourceKey.from_resource(obj)
            for obj in workload.cached(Deployment).list(namespace=config.namespace)
            if config.name in references(obj)
        ]

    return workload.watch(ConfigMap, mapper=dependents)


def build_app() -> Application:
    return Application("config-reloader", controller())


if __name__ == "__main__":
    build_app().main()
