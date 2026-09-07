"""Finalizer ordering and periodic external drift repair, with an explicit provider adapter.

The in-memory provider makes the example executable without an external account.
Replace it with a durable API adapter for actual external resources.
"""

from typing import Protocol

from cloudcoil.controller import Controller, Request, Result, ensure_finalizer, remove_finalizer
from cloudcoil.crd import custom_resource
from cloudcoil.operator import Operator
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

FINALIZER = "patterns.cloudcoil.dev/external-record"


class RecordSpec(BaseModel):
    value: str


@custom_resource(api_version="patterns.cloudcoil.dev/v1alpha1", plural="externalrecords")
class ExternalRecord(Resource):
    spec: RecordSpec


class Provider(Protocol):
    async def put(self, key: str, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class MemoryProvider:
    def __init__(self) -> None:
        self.records: dict[str, str] = {}

    async def put(self, key: str, value: str) -> None:
        self.records[key] = value

    async def delete(self, key: str) -> None:
        self.records.pop(key, None)


def build_operator(provider: Provider | None = None) -> Operator:
    external = provider if provider is not None else MemoryProvider()

    async def reconcile(request: Request[ExternalRecord]) -> Result | None:
        obj = request.resource
        if not obj or not obj.metadata or not obj.metadata.uid:
            return None  # Cache absence never authorizes external deletion.
        if obj.metadata.deletion_timestamp:
            if FINALIZER in (obj.metadata.finalizers or []):
                await external.delete(obj.metadata.uid)  # Idempotent; retry errors normally.
                await remove_finalizer(obj, FINALIZER, config=request.config)
            return None
        # Persist this before the first external side effect. A returned resource
        # would not be persisted until after this callback completes.
        uid = obj.metadata.uid
        obj = await ensure_finalizer(obj, FINALIZER, config=request.config)
        if obj.metadata and obj.metadata.deletion_timestamp:
            return Result(requeue_after=0)  # Deletion may begin during the live finalizer read.
        await external.put(uid, obj.spec.value)
        return Result(requeue_after=60)  # External changes have no Kubernetes watch.

    return Operator("external-records", Controller(ExternalRecord, reconcile))


if __name__ == "__main__":
    build_operator().main()
