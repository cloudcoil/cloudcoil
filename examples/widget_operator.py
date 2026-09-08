"""A complete operator: one CRD, admission policy, and three owned child kinds.

python examples/widget_operator.py manifests --image widgets:local --ca-file ca.crt
python examples/widget_operator.py install --image widgets:local --ca-file ca.crt
python examples/widget_operator.py run

See examples/widgets/README.md for the complete build/install/exercise walkthrough.
"""

from html import escape
from typing import Annotated, Literal

from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Service
from pydantic import Field

from cloudcoil.admission import AdmissionDenied, AdmissionRequest
from cloudcoil.application import Application, RBACRule, WebhookServer
from cloudcoil.controller import Context, ReconcileStatus, Wait
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


app = Application(
    "widgets",
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("widget-policy",)),),
    webhook=WebhookServer(tls_secret="widgets-tls"),
    leader_election=True,
)
widgets = app.controller(Widget, owns=(ConfigMap, Deployment, Service))


@widgets.mutate()
async def default_labels(request: AdmissionRequest[Widget]) -> Widget | None:
    obj = request.resource
    if obj is not None and obj.metadata is not None:
        obj.metadata.labels = {
            "app.kubernetes.io/managed-by": "cloudcoil",
            **(obj.metadata.labels or {}),
        }
    return obj


@widgets.validate()
async def validate_message(request: AdmissionRequest[Widget]) -> None:
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


@widgets.stage(condition="ConfigurationReady")
async def configure(widget: Widget, ctx: Context[Widget]) -> None:
    # Names, namespaces and controller owner references come from the parent.
    # ensure preserves fields we omit (e.g. Service.clusterIP) and skips no-op writes.
    await ctx.ensure(ConfigMap(data={"index.html": f"<h1>{escape(widget.spec.message)}</h1>\n"}))


@widgets.stage(depends=configure, condition="DeploymentApplied")
async def deploy(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_deployment(widget))


@widgets.stage(depends=deploy, condition="ServiceReady")
async def expose(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_service(widget))


@widgets.stage(depends=expose, condition="WorkloadAvailable")
async def available(widget: Widget, ctx: Context[Widget]) -> None:
    # Read our preceding writes live: a stale cache can report the old rollout Ready.
    # Child watches still wake us when rollout progresses.
    assert widget.name is not None
    deployment = await ctx.get(Deployment, widget.name)
    status = deployment.status
    replicas = widget.spec.replicas
    ready = (status.ready_replicas or 0) if status else 0
    current = bool(
        status
        and deployment.metadata
        and status.observed_generation == deployment.metadata.generation
        and status.updated_replicas == replicas
        and status.replicas == replicas
        and status.available_replicas == replicas
    )
    ctx.set_status(phase="Ready" if current else "Pending", ready_replicas=ready)
    if not current:
        raise Wait("RollingOut", f"{ready}/{replicas} replicas ready", after=10)
    return None


def desired_deployment(widget: Widget) -> Deployment:
    labels = {"examples.cloudcoil.dev/widget": widget.name}
    return Deployment.model_validate(
        {
            "spec": {
                "replicas": widget.spec.replicas,
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
                        "volumes": [{"name": "content", "configMap": {"name": widget.name}}],
                    },
                },
            },
        }
    )


def desired_service(widget: Widget) -> Service:
    labels = {"examples.cloudcoil.dev/widget": widget.name}
    return Service.model_validate(
        {
            "spec": {"selector": labels, "ports": [{"port": 80, "targetPort": "http"}]},
        }
    )


if __name__ == "__main__":
    app.main()
