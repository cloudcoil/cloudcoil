"""Finalizer ordering and periodic external drift repair, with an explicit provider adapter.

The in-memory provider makes the example executable without an external account.
Replace it with a durable API adapter for actual external resources.
"""

from typing import Protocol

from cloudcoil.application import Application
from cloudcoil.crd import custom_resource
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


def build_app(provider: Provider | None = None) -> Application:
    external = provider if provider is not None else MemoryProvider()

    app = Application("external-records")
    records = app.controller(ExternalRecord)

    @records.reconcile(every=60)
    async def reconcile(record: ExternalRecord) -> None:
        assert record.metadata and record.metadata.uid
        await external.put(record.metadata.uid, record.spec.value)

    @records.finalize(FINALIZER)
    async def cleanup(record: ExternalRecord) -> None:
        assert record.metadata and record.metadata.uid
        await external.delete(record.metadata.uid)

    return app


if __name__ == "__main__":
    build_app().main()
