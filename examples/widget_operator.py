"""One typed resource used for CRD generation, reconciliation, and admission.

Generate: python examples/widget_operator.py crd
Reconcile: python examples/widget_operator.py controller --namespace default
Serve admission with an ASGI server; see docs/custom-resources.md for TLS setup.
"""

import argparse
import asyncio
import signal
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from cloudcoil.models.kubernetes.core.v1 import ConfigMap
from pydantic import Field

from cloudcoil.admission import (
    AdmissionDenied,
    AdmissionRequest,
    AdmissionWebhook,
    mutating,
    validating,
)
from cloudcoil.client import Config
from cloudcoil.controller import (
    Controller,
    HealthServer,
    LeaderElection,
    Manager,
    Request,
    TerminalError,
    mutate,
)
from cloudcoil.crd import CRD, PrinterColumn, custom_resource
from cloudcoil.errors import ResourceNotFound
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


crd = CRD(Widget)
admission = AdmissionWebhook().register(Widget)


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


async def run_controller(namespace: str, lease: str | None, health_port: int | None) -> None:
    config = Config(namespace=namespace)
    manager = Manager(
        Controller(Widget, reconcile, name="widget", namespace=namespace).owns(ConfigMap),
        config=config,
        leader_election=LeaderElection(lease, namespace=namespace) if lease else None,
        health=HealthServer(host="0.0.0.0", port=health_port) if health_port is not None else None,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await manager.run(stop=stop)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        config.client.close()
        await config.async_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("crd", help="Print the generated CRD manifest")
    controller = commands.add_parser("controller", help="Run the reconciliation manager")
    controller.add_argument("--namespace", default="default")
    controller.add_argument("--lease")
    controller.add_argument("--health-port", type=int)
    webhooks = commands.add_parser("webhook-config", help="Print admission registration manifests")
    webhooks.add_argument("--namespace", required=True)
    webhooks.add_argument("--service", required=True)
    webhooks.add_argument("--ca-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "crd":
        print(crd.to_yaml(), end="")
    elif args.command == "webhook-config":
        print(
            yaml.safe_dump_all(
                admission.configurations(
                    name="widgets.examples.cloudcoil.dev",
                    service_name=args.service,
                    service_namespace=args.namespace,
                    ca_bundle=args.ca_file.read_bytes(),
                ),
                sort_keys=False,
            ),
            end="",
        )
    else:
        asyncio.run(run_controller(args.namespace, args.lease, args.health_port))


if __name__ == "__main__":
    main()
