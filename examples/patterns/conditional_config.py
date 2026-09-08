"""First-match cases: suspension, a missing dependency, or convergence.

Create a shared ConfigMap, then an ApplicationConfig with spec.configMap set to its
name. The operator maintains an owned ConfigMap named after the ApplicationConfig.
"""

from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.application import Application
from cloudcoil.controller import Cases, Controller, ReconcileStatus, Request, ResourceKey, Wait
from cloudcoil.crd import custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class ConfigSpec(BaseModel):
    config_map: str = Field(alias="configMap", min_length=1)
    suspended: bool = False


@custom_resource(api_version="patterns.cloudcoil.dev/v1alpha1", plural="applicationconfigs")
class ApplicationConfig(Resource):
    spec: ConfigSpec
    status: ReconcileStatus | None = None


def build_app() -> Application:
    cases = Cases[ApplicationConfig]()

    @cases.case("Suspended", when=lambda req: req.object.spec.suspended, priority=100)
    async def suspended(request: Request[ApplicationConfig]) -> Wait:
        return Wait("Suspended", "Reconciliation is suspended", requeue_after=300)

    @cases.case(
        "InputMissing",
        when=lambda req: req.cached(ConfigMap).get(req.object.spec.config_map) is None,
        priority=50,
    )
    async def missing(request: Request[ApplicationConfig]) -> Wait:
        return Wait("ConfigMapMissing", f"Waiting for ConfigMap {request.object.spec.config_map}")

    @cases.otherwise("Configured")
    async def configure(request: Request[ApplicationConfig]) -> None:
        source = request.cached(ConfigMap).get(request.object.spec.config_map)
        assert source is not None  # The preceding predicate selected this case.
        await request.ensure(ConfigMap(data=source.data))

    controller = Controller(ApplicationConfig, cases).owns(ConfigMap)

    def dependents(config: ConfigMap) -> list[ResourceKey]:
        return [
            ResourceKey.from_resource(obj)
            for obj in controller.cached(ApplicationConfig).list(namespace=config.namespace)
            if obj.spec.config_map == config.name
        ]

    return Application("conditional-config", controller.watch(ConfigMap, mapper=dependents))


if __name__ == "__main__":
    build_app().main()
