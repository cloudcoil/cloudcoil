"""Cases within a stage: choose a configuration branch, then publish its checksum.

Create a shared ConfigMap and an ApplicationConfig referencing it. Each pass either
waits for suspension/input, or maintains a child ConfigMap and reports its checksum.
"""

import json
from hashlib import sha256

from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.application import Application
from cloudcoil.controller import Context, ReconcileStatus, ResourceKey, Wait
from cloudcoil.crd import custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class ConfigSpec(BaseModel):
    config_map: str = Field(alias="configMap", min_length=1)
    suspended: bool = False


class ConfigStatus(ReconcileStatus):
    checksum: str = ""


@custom_resource(api_version="patterns.cloudcoil.dev/v1alpha1", plural="applicationconfigs")
class ApplicationConfig(Resource):
    spec: ConfigSpec
    status: ConfigStatus | None = None


def build_app() -> Application:
    app = Application("conditional-config")
    configs = app.controller(ApplicationConfig, owns=(ConfigMap,))
    configuration = configs.stage("configuration", condition="ConfigurationReady")

    def is_suspended(obj: ApplicationConfig) -> bool:
        return obj.spec.suspended

    def input_missing(obj: ApplicationConfig, ctx: Context[ApplicationConfig]) -> bool:
        return ctx.cached(ConfigMap).get(obj.spec.config_map) is None

    @configuration.case(when=is_suspended)
    async def suspended(obj: ApplicationConfig) -> None:
        raise Wait("Suspended", "Reconciliation is suspended", after=300)

    @configuration.case(when=input_missing, after=suspended)
    async def missing(obj: ApplicationConfig) -> None:
        raise Wait("ConfigMapMissing", f"Waiting for ConfigMap {obj.spec.config_map}")

    @configuration.otherwise()
    async def configure(obj: ApplicationConfig, ctx: Context[ApplicationConfig]) -> None:
        source = ctx.cached(ConfigMap).get(obj.spec.config_map)
        assert source is not None  # No await between selection and reading this snapshot.
        await ctx.ensure(ConfigMap(data=source.data))

    @configs.stage(depends=configuration, condition="ChecksumPublished")
    async def publish_checksum(obj: ApplicationConfig, ctx: Context[ApplicationConfig]) -> None:
        # Read the child live: the informer can lag our preceding write.
        assert obj.name is not None
        child = await ctx.get(ConfigMap, obj.name)
        checksum = sha256(json.dumps(child.data or {}, sort_keys=True).encode()).hexdigest()
        ctx.set_status(checksum=checksum)

    @configs.watch(ConfigMap)
    def dependents(config: ConfigMap) -> list[ResourceKey]:
        return [
            ResourceKey.from_resource(obj)
            for obj in configs.cached(ApplicationConfig).list(namespace=config.namespace)
            if obj.spec.config_map == config.name
        ]

    return app


if __name__ == "__main__":
    build_app().main()
