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
from cloudcoil.application import Application, RBACRule, WebhookServer
from cloudcoil.controller import Controller, ReconcileStatus, Request, Stage, Stages, Wait
from cloudcoil.crd import PrinterColumn, custom_resource
from cloudcoil.errors import ResourceNotFound
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class WidgetSpec(BaseModel):
    message: str = Field(min_length=1, max_length=200)
    replicas: int = Field(default=1, ge=1, le=5)


class WidgetStatus(ReconcileStatus):
    phase: Annotated[Literal["Pending", "Ready"], PrinterColumn(name="Phase")] = "Pending"
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


async def configure(request: Request[Widget]) -> None:
    obj = request.object
    # Names, namespaces and controller owner references come from the parent.
    # ensure preserves fields we omit (e.g. Service.clusterIP) and skips no-op writes.
    await request.ensure(ConfigMap(data={"index.html": f"<h1>{escape(obj.spec.message)}</h1>\n"}))


async def deploy(request: Request[Widget]) -> None:
    obj = request.object
    labels = {"examples.cloudcoil.dev/widget": request.name}
    await request.ensure(
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


async def expose(request: Request[Widget]) -> None:
    labels = {"examples.cloudcoil.dev/widget": request.name}
    await request.ensure(
        Service.model_validate(
            {
                "spec": {"selector": labels, "ports": [{"port": 80, "targetPort": "http"}]},
            }
        )
    )


async def available(request: Request[Widget]) -> Wait | None:
    # Read our preceding writes live: a stale cache can report the old rollout Ready.
    # Child watches still wake us when rollout progresses.
    client = await request.client(Deployment)
    deployment = await client.get(request.name)
    status = deployment.status
    replicas = request.object.spec.replicas
    ready = (status.ready_replicas or 0) if status else 0
    current = bool(
        status
        and deployment.metadata
        and status.observed_generation == deployment.metadata.generation
        and status.updated_replicas == replicas
        and status.replicas == replicas
        and status.available_replicas == replicas
    )
    request.set_status(phase="Ready" if current else "Pending", ready_replicas=ready)
    if not current:
        return Wait("RollingOut", f"{ready}/{replicas} replicas ready", requeue_after=10)
    return None


# Every pass repairs all children. None continues, Wait pauses, exceptions retry.
reconcile = Stages(
    Stage("ConfigurationReady", configure),
    Stage("DeploymentApplied", deploy),
    Stage("ServiceReady", expose),
    Stage("WorkloadAvailable", available),
)


app = Application(
    "widgets",
    Controller(Widget, reconcile).owns(ConfigMap, Deployment, Service),
    # owns supplies child read/create/patch grants. This named read documents the
    # webhook dependency; unrelated resources always need an explicit RBACRule.
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("widget-policy",)),),
    webhook=WebhookServer(tls_secret="widgets-tls"),
    leader_election=True,
)

if __name__ == "__main__":
    app.main()
