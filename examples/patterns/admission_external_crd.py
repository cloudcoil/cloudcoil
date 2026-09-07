"""Policies for a CRD installed by another operator, without taking ownership of it."""

from pydantic import Field

from cloudcoil.admission import AdmissionDenied, AdmissionRequest, AdmissionWebhook
from cloudcoil.application import Application, WebhookServer
from cloudcoil.crd import custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class DatabaseSpec(BaseModel):
    storage_gib: int = Field(alias="storageGiB", ge=1)


# In a real integration, import the other operator's generated model instead.
# This describes the wire type; it does not install the CRD by itself.
@custom_resource(api_version="database.example.com/v1", plural="databases")
class Database(Resource):
    spec: DatabaseSpec


def build_app() -> Application:
    policies = AdmissionWebhook()

    @policies.validating(Database, path="/database-storage", operations=("UPDATE",))
    async def prevent_shrink(request: AdmissionRequest[Database]) -> None:
        old, new = request.old_resource, request.resource
        if old and new and new.spec.storage_gib < old.spec.storage_gib:
            raise AdmissionDenied("Database storage cannot shrink")

    # Database is deliberately not in resources= or a Controller: no CRD or CRUD grant.
    return Application(
        "database-policy",
        admission=policies,
        webhook=WebhookServer(tls_secret="database-policy-tls"),
    )


if __name__ == "__main__":
    build_app().main()
