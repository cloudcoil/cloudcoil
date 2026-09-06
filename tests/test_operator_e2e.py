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
