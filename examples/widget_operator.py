"""A complete operator: one CRD, admission policy, and three owned child kinds.

python examples/widget_operator.py manifests --image widgets:local --ca-file ca.crt
python examples/widget_operator.py install --image widgets:local --ca-file ca.crt
python examples/widget_operator.py run

See examples/widgets/README.md for the complete build/install/exercise walkthrough.
"""

from html import escape
from typing import Annotated, Literal, Self

from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Service
from pydantic import Field

from cloudcoil.admission import AdmissionDenied, AdmissionRequest, mutating, validating
from cloudcoil.controller import Controller, Request
from cloudcoil.crd import PrinterColumn, custom_resource
from cloudcoil.errors import ResourceNotFound
from cloudcoil.operator import Operator, RBACRule, WebhookServer
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class WidgetSpec(BaseModel):
    message: str = Field(min_length=1, max_length=200)
    replicas: int = Field(default=1, ge=1, le=5)


class WidgetStatus(BaseModel):
    phase: Annotated[Literal["Pending", "Ready"], PrinterColumn(name="Phase")]
    observed_generation: int | None = Field(default=None, alias="observedGeneration")
    ready_replicas: int = Field(default=0, alias="readyReplicas")


@custom_resource(
    api_version="examples.cloudcoil.dev/v1alpha1", plural="widgets", short_names=("wd",)
)
class Widget(Resource):
    spec: WidgetSpec
    status: WidgetStatus | None = None

    @classmethod
    @mutating()
    async def default_labels(cls, request: AdmissionRequest[Self]) -> Self | None:
        obj = request.resource
        if obj is not None and obj.metadata is not None:
            obj.metadata.labels = {
                "app.kubernetes.io/managed-by": "cloudcoil",
                **(obj.metadata.labels or {}),
            }
        return obj

    @classmethod
    @validating()
    async def validate_message(cls, request: AdmissionRequest[Self]) -> None:
        obj = request.resource
        if obj is None:
            return
        if not obj.spec.message.strip():
            raise AdmissionDenied("spec.message must contain a non-whitespace character")
        # The same API works in controllers and webhooks, for any resource kind.
        # This is a live read, including on dry runs; admission never writes to Kubernetes.
        client = await request.client(ConfigMap)
        try:
            policy = await client.get("widget-policy")
        except ResourceNotFound:
            return  # Optional namespace policy; the CRD still enforces its field limits.
        limit = int((policy.data or {}).get("maxLength", "200"))
        if len(obj.spec.message) > limit:
            raise AdmissionDenied(f"Namespace policy limits messages to {limit} characters")


async def reconcile(request: Request[Widget]) -> Widget | None:
    obj = request.resource
    if obj is None or obj.metadata is None or obj.metadata.deletion_timestamp:
        return None
    # Names, namespaces and controller owner references come from the parent.
    # ensure preserves fields we omit (e.g. Service.clusterIP) and skips no-op writes.
    await request.ensure(ConfigMap(data={"index.html": f"<h1>{escape(obj.spec.message)}</h1>\n"}))
    labels = {"examples.cloudcoil.dev/widget": request.name}
    deployment = await request.ensure(
        Deployment.model_validate(
            {
                "spec": {
                    "replicas": obj.spec.replicas,
                    "selector": {"matchLabels": labels},
                    "template": {
                        "metadata": {"labels": labels},
                        "spec": {
                            "containers": [
                                {
                                    "name": "web",
                                    "image": "nginx:stable",
                                    "ports": [{"name": "http", "containerPort": 80}],
                                    "volumeMounts": [
                                        {
                                            "name": "content",
                                            "mountPath": "/usr/share/nginx/html",
                                            "readOnly": True,
                                        }
                                    ],
                                    "readinessProbe": {"httpGet": {"path": "/", "port": "http"}},
                                }
                            ],
                            "volumes": [{"name": "content", "configMap": {"name": request.name}}],
                        },
                    },
                },
            }
        )
    )
    await request.ensure(
        Service.model_validate(
            {
                "spec": {"selector": labels, "ports": [{"port": 80, "targetPort": "http"}]},
            }
        )
    )
    ready = (deployment.status.ready_replicas or 0) if deployment.status else 0
    observed = deployment.status.observed_generation if deployment.status else None
    current = bool(deployment.metadata and observed == deployment.metadata.generation)
    obj.status = WidgetStatus(
        phase="Ready" if current and ready >= obj.spec.replicas else "Pending",
        observedGeneration=obj.metadata.generation,
        readyReplicas=ready,
    )
    return obj  # The runtime patches /status; child events trigger the next pass.


operator = Operator(
    "widgets",
    Controller(Widget, reconcile).owns(ConfigMap, Deployment, Service),
    # owns supplies child read/create/patch grants. This named read documents the
    # webhook dependency; unrelated resources always need an explicit RBACRule.
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("widget-policy",)),),
    webhook=WebhookServer(tls_secret="widgets-tls"),
    leader_election=True,
)

if __name__ == "__main__":
    operator.main()
