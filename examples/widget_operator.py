"""One typed resource used for CRD generation, reconciliation, and admission.

Generate: python examples/widget_operator.py manifests --image example/widgets:v1
Install: python examples/widget_operator.py install --image example/widgets:v1
Run: python examples/widget_operator.py run
See docs/operators.md for TLS, namespace, image entry point, and RBAC setup.
"""

import os
from pathlib import Path
from typing import Annotated, Literal, Self

from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.admission import (
    AdmissionDenied,
    AdmissionRequest,
    mutating,
    validating,
)
from cloudcoil.controller import (
    Controller,
    LeaderElection,
    Request,
    TerminalError,
    mutate,
)
from cloudcoil.crd import PrinterColumn, custom_resource
from cloudcoil.errors import ResourceNotFound
from cloudcoil.operator import Operator, RBACRule, WebhookServer
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class WidgetSpec(BaseModel):
    message: str = Field(min_length=1, max_length=200)


class WidgetStatus(BaseModel):
    phase: Annotated[Literal["Ready"], PrinterColumn(name="Phase")] = "Ready"
    observed_generation: int | None = Field(default=None, alias="observedGeneration")
    config_map: str = Field(alias="configMap")


@custom_resource(plural="widgets", short_names=("wd",))
class Widget(Resource):
    api_version: Literal["examples.cloudcoil.dev/v1alpha1"] = Field(
        default="examples.cloudcoil.dev/v1alpha1", alias="apiVersion"
    )
    kind: Literal["Widget"] = "Widget"
    spec: WidgetSpec
    status: WidgetStatus | None = None

    @classmethod
    @mutating()
    async def default_labels(cls, request: AdmissionRequest[Self]) -> Self | None:
        obj = request.resource
        if obj is None or obj.metadata is None:
            return None
        obj.metadata.labels = {
            "app.kubernetes.io/managed-by": "cloudcoil",
            **(obj.metadata.labels or {}),
        }
        return obj

    @classmethod
    @validating()
    async def validate_message(cls, request: AdmissionRequest[Self]) -> None:
        obj = request.resource
        if obj is not None and not obj.spec.message.strip():
            raise AdmissionDenied("spec.message must contain a non-whitespace character")


async def reconcile(request: Request[Widget]) -> Widget | None:
    obj = request.resource
    if obj is None or obj.metadata is None or obj.metadata.deletion_timestamp:
        return None
    source_uid = obj.metadata.uid
    # Sharing the Widget's name avoids exceeding the Kubernetes name length limit.
    try:
        child = await ConfigMap.async_get(request.name, request.namespace)
    except ResourceNotFound:
        child = await ConfigMap.model_validate(
            {
                "metadata": {
                    "name": request.name,
                    "namespace": request.namespace,
                    "ownerReferences": [
                        {
                            "apiVersion": obj.api_version,
                            "kind": obj.kind,
                            "name": obj.name,
                            "uid": source_uid,
                            "controller": True,
                        }
                    ],
                },
                "data": {"message": obj.spec.message},
            }
        ).async_create()
    else:

        def change(current: ConfigMap) -> None:
            owners = current.metadata.owner_references if current.metadata else None
            if not any(ref.controller and ref.uid == source_uid for ref in owners or []):
                raise TerminalError(f"Refusing to adopt unrelated ConfigMap {request.name}")
            current.data = {**(current.data or {}), "message": obj.spec.message}

        child = await mutate(child, change)
    assert child.name is not None
    obj.status = WidgetStatus(observedGeneration=obj.metadata.generation, configMap=child.name)
    return obj  # Only status changed; the runtime sends a guarded /status patch.


# The same definition generates installation manifests and runs the process.
# Supply the public CA bundle when generating/installing webhook configurations.
ca_file = os.environ.get("CLOUDCOIL_WEBHOOK_CA_FILE")
operator = Operator(
    "widgets",
    Controller(Widget, reconcile, name="widget").owns(ConfigMap),
    rules=(
        RBACRule(
            ConfigMap,
            ("get", "create", "patch"),
            plural="configmaps",
            scope="Namespaced",
        ),
    ),
    webhook=WebhookServer(
        ca_bundle=Path(ca_file).read_bytes() if ca_file else b"",
        tls_secret="widgets-tls",
    ),
    leader_election=LeaderElection("widgets"),
)

if __name__ == "__main__":
    operator.main()
