"""Install and run one custom operator against the supported Kubernetes matrix."""

import asyncio
import os
from importlib.metadata import version
from typing import Literal
from uuid import uuid4

import pytest
from cloudcoil.models.kubernetes.core.v1 import Namespace
from pydantic import BaseModel, Field, create_model

from cloudcoil.controller import Controller
from cloudcoil.crd import custom_resource
from cloudcoil.operator import Operator
from cloudcoil.operator._install import _url
from cloudcoil.resources import Resource

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
pytestmark = pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    k8s_version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)


class ReadyStatus(BaseModel):
    ready: bool


async def test_live_operator_install_rbac_and_returned_status(test_config):
    namespace = await (await Namespace.async_client(test_config)).create(
        Namespace(metadata={"generateName": "operator-"})
    )
    group = f"operator-{uuid4().hex[:12]}.cloudcoil.dev"
    api_version = f"{group}/v1"
    widget = custom_resource(plural="widgets")(
        create_model(
            "OperatorWidget",
            __base__=Resource,
            api_version=(Literal[api_version], Field(default=api_version, alias="apiVersion")),
            kind=(Literal["OperatorWidget"], "OperatorWidget"),
            status=(ReadyStatus | None, None),
        )
    )

    async def reconcile(request):
        if request.resource is not None:
            request.resource.status = ReadyStatus(ready=True)
        return request.resource

    config = test_config.clone(namespace=namespace.name)
    app = Operator("widgets", Controller(widget, reconcile), config=config)
    stop = asyncio.Event()
    task = None
    try:
        await app.install()
        await app.install()  # Server-side apply is repeatable, including RBAC.
        assert not app.ready
        for resource, verb, allowed in (
            ("widgets", "list", True),
            ("widgets/status", "patch", True),
            ("widgets", "delete", False),
        ):
            review = await config.async_client.post(
                "/apis/authorization.k8s.io/v1/subjectaccessreviews",
                json={
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SubjectAccessReview",
                    "spec": {
                        "user": f"system:serviceaccount:{namespace.name}:widgets",
                        "groups": [
                            "system:authenticated",
                            "system:serviceaccounts",
                            f"system:serviceaccounts:{namespace.name}",
                        ],
                        "resourceAttributes": {
                            "group": group,
                            "resource": resource.split("/")[0],
                            "subresource": "status" if "/" in resource else "",
                            "verb": verb,
                            "namespace": namespace.name,
                        },
                    },
                },
            )
            review.raise_for_status()
            assert review.json()["status"]["allowed"] is allowed
        client = await widget.async_client(config)
        await client.create(widget(metadata={"name": "example", "namespace": namespace.name}))
        task = asyncio.create_task(app.run(stop=stop))
        await app.wait_ready()
        async with asyncio.timeout(30):
            while True:
                obj = await client.get("example")
                if obj.status and obj.status.ready:
                    break
                await asyncio.sleep(0.1)
        stop.set()
        await task
        assert not config.async_client.is_closed
    finally:
        stop.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for manifest in reversed(app.manifests()):
            response = await config.async_client.delete(_url(manifest))
            assert response.status_code in (200, 202, 404), response.text
        await config.async_client.aclose()
        config.client.close()
        await (await Namespace.async_client(test_config)).delete(namespace.name)


async def test_live_widget_example_manages_three_children_and_reads_admission_policy(test_config):
    """Run the shipped reconciler against real CRDs, children, status and admission reads.

    HTTPS deployment/bootstrap is exercised by examples/widgets/demo.sh; ASGI here
    keeps this regression independent of container builds and certificate tooling.
    """
    import importlib.util
    import sys
    from pathlib import Path

    import httpx
    from cloudcoil.models.kubernetes.apps.v1 import Deployment
    from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Service

    from cloudcoil.admission import AdmissionWebhook
    from cloudcoil.errors import ResourceNotFound
    from cloudcoil.operator import WebhookServer

    path = Path(__file__).resolve().parents[1] / "examples/widget_operator.py"
    spec = importlib.util.spec_from_file_location("widget_example_e2e", path)
    example = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = example
    spec.loader.exec_module(example)
    namespace = await (await Namespace.async_client(test_config)).create(
        Namespace(metadata={"generateName": "widgets-e2e-"})
    )
    config = test_config.clone(namespace=namespace.name)
    controller = Controller(example.Widget, example.reconcile, config=config).owns(
        ConfigMap, Deployment, Service
    )
    app = Operator("widgets", controller, config=config, webhook=WebhookServer())
    stop = asyncio.Event()
    task = None
    try:
        await app.install(include_webhooks=False)
        client = await example.Widget.async_client(config)
        maps = await ConfigMap.async_client(config)
        deployments = await Deployment.async_client(config)
        services = await Service.async_client(config)
        parent = await client.create(
            example.Widget(metadata={"name": "hello"}, spec=example.WidgetSpec(message="first"))
        )
        task = asyncio.create_task(controller.run(stop=stop))
        await controller.wait_ready()

        async def converged(message, replicas, previous_uid=None):
            async with asyncio.timeout(60):
                while True:
                    if task.done():
                        await task
                        pytest.fail("Controller stopped")
                    try:
                        child = await maps.get("hello")
                        deployment = await deployments.get("hello")
                        service = await services.get("hello")
                        current = await client.get("hello")
                        if (
                            child.data["index.html"] == f"<h1>{message}</h1>\n"
                            and child.metadata.uid != previous_uid
                            and deployment.spec.replicas == replicas
                            and current.status is not None
                            and current.status.observed_generation == current.metadata.generation
                        ):
                            for obj in (child, deployment, service):
                                assert obj.metadata.owner_references[0].uid == parent.metadata.uid
                            return child, service
                    except ResourceNotFound:
                        pass
                    await asyncio.sleep(0.1)

        child, service = await converged("first", 1)
        cluster_ip = service.spec.cluster_ip
        parent = await client.get("hello")
        parent.spec.message = "second"
        parent.spec.replicas = 2
        await client.update(parent)
        child, service = await converged("second", 2)
        assert service.spec.cluster_ip == cluster_ip
        child.data["index.html"] = "drift"
        await maps.update(child)
        child, _ = await converged("second", 2)
        await maps.delete("hello")
        await converged("second", 2, previous_uid=child.metadata.uid)

        policy = await maps.create(
            ConfigMap(metadata={"name": "widget-policy"}, data={"maxLength": "3"})
        )
        admission = AdmissionWebhook(config=config).register(example.Widget)
        endpoint = next(path for path in admission._routes if path.endswith("/validate_message"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admission), base_url="https://webhook"
        ) as web:
            response = await web.post(
                endpoint,
                json={
                    "apiVersion": "admission.k8s.io/v1",
                    "kind": "AdmissionReview",
                    "request": {
                        "uid": "dry-review",
                        "operation": "CREATE",
                        "dryRun": True,
                        "namespace": namespace.name,
                        "name": "denied",
                        "kind": {
                            "group": "examples.cloudcoil.dev",
                            "version": "v1alpha1",
                            "kind": "Widget",
                        },
                        "resource": {
                            "group": "examples.cloudcoil.dev",
                            "version": "v1alpha1",
                            "resource": "widgets",
                        },
                        "object": example.Widget(
                            metadata={"name": "denied", "namespace": namespace.name},
                            spec=example.WidgetSpec(message="too long"),
                        ).model_dump(mode="json", by_alias=True, exclude_none=True),
                    },
                },
            )
        review = response.json()["response"]
        assert not review["allowed"]
        assert "3 characters" in review["status"]["message"]
        assert (await maps.get("widget-policy")).resource_version == policy.resource_version
        with pytest.raises(ResourceNotFound):
            await client.get("denied")
    finally:
        stop.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for manifest in reversed(app.manifests(include_webhooks=False)):
            response = await config.async_client.delete(_url(manifest))
            assert response.status_code in (200, 202, 404), response.text
        await config.async_client.aclose()
        config.client.close()
        await (await Namespace.async_client(test_config)).delete(namespace.name)
