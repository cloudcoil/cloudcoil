"""Aggregate existing Pods selected by a CR; no ownership or pod writes."""

from cloudcoil.models.kubernetes.core.v1 import Pod
from pydantic import Field

from cloudcoil.controller import Controller, Request, ResourceKey
from cloudcoil.crd import custom_resource
from cloudcoil.operator import Operator
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class WorkloadSpec(BaseModel):
    selector: dict[str, str] = Field(min_length=1)


class WorkloadStatus(BaseModel):
    pods: int
    ready: int
    observed_generation: int | None = Field(default=None, alias="observedGeneration")


@custom_resource(api_version="patterns.cloudcoil.dev/v1alpha1", plural="workloads")
class Workload(Resource):
    spec: WorkloadSpec
    status: WorkloadStatus | None = None


async def reconcile(request: Request[Workload]) -> Workload | None:
    obj = request.resource
    if not obj or not obj.metadata or obj.metadata.deletion_timestamp:
        return None
    pods = request.cached(Pod).list(labels=obj.spec.selector)
    ready = sum(
        any(c.type == "Ready" and c.status == "True" for c in pod.status.conditions or [])
        for pod in pods
        if pod.status and not (pod.metadata and pod.metadata.deletion_timestamp)
    )
    obj.status = WorkloadStatus(
        pods=len(pods), ready=ready, observedGeneration=obj.metadata.generation
    )
    return obj


def controller() -> Controller[Workload]:
    workload = Controller(Workload, reconcile)

    def dependents(pod: Pod) -> list[ResourceKey]:
        labels = pod.metadata.labels or {} if pod.metadata else {}
        return [
            ResourceKey.from_resource(obj)
            for obj in workload.cached(Workload).list(namespace=pod.namespace)
            if all(labels.get(key) == value for key, value in obj.spec.selector.items())
        ]

    return workload.watch(Pod, mapper=dependents)


def build_operator() -> Operator:
    return Operator("workload-summary", controller())


if __name__ == "__main__":
    build_operator().main()
