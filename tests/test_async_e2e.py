import asyncio
import os
import random
import time
from importlib.metadata import version
from pathlib import Path

import pytest

import cloudcoil.models.kubernetes as k8s
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.errors import WaitTimeout
from cloudcoil.resources import get_dynamic_resource, parse_file

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
cluster_provider = os.environ.get("CLUSTER_PROVIDER", "kind")


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_basic_crud(test_config):
    with test_config:
        assert (
            await k8s.core.v1.Service.async_get("kubernetes", "default")
        ).metadata.name == "kubernetes"
        output = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-")
        ).async_create()
        name = output.metadata.name
        assert (await k8s.core.v1.Namespace.async_get(name)).metadata.name == name
        output.metadata.annotations = {"test": "test"}
        output = await output.async_update()
        assert output.metadata.annotations == {"test": "test"}
        assert (await output.async_remove(dry_run=True)).metadata.name == name
        await output.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_list_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        for i in range(3):
            await k8s.core.v1.ConfigMap(
                metadata=dict(name=f"test-list-{i}", namespace=ns.name, labels={"test": "true"}),
                data={"key": f"value{i}"},
            ).async_create()

        cms = await k8s.core.v1.ConfigMap.async_list(namespace=ns.name, label_selector="test=true")
        assert len(cms.items) == 3
        await k8s.core.v1.ConfigMap.async_delete_all(namespace=ns.name, label_selector="test=true")
        assert not (
            await k8s.core.v1.ConfigMap.async_list(namespace=ns.name, label_selector="test=true")
        ).items
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_dynamic_resources(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        cm = DynamicConfigMap(
            metadata={"name": "test-cm", "namespace": ns.name}, data={"key": "value"}
        )

        created = await cm.async_create()
        assert created["data"]["key"] == "value"

        fetched = await DynamicConfigMap.async_get("test-cm", ns.name)
        assert fetched.raw.get("data", {}).get("key") == "value"

        fetched["data"]["new_key"] = "new_value"
        updated = await fetched.async_update()
        assert updated.raw.get("data", {}).get("new_key") == "new_value"

        await DynamicConfigMap.async_delete("test-cm", ns.name)
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_save_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()

        # Test regular save
        cm = k8s.core.v1.ConfigMap(
            metadata=dict(name="test-save", namespace=ns.name), data={"key": "value"}
        )
        saved = await cm.async_save()
        assert saved.metadata.name == "test-save"
        assert saved.data["key"] == "value"

        saved.data["key"] = "new-value"
        updated = await saved.async_save()
        assert updated.data["key"] == "new-value"
        await saved.async_remove()

        # Test dynamic save
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        dynamic_cm = DynamicConfigMap(
            metadata={"name": "test-dynamic-save", "namespace": ns.name}, data={"key": "value"}
        )
        saved_dynamic = await dynamic_cm.async_save()
        assert saved_dynamic["data"]["key"] == "value"

        saved_dynamic["data"]["key"] = "updated"
        updated_dynamic = await saved_dynamic.async_save()
        assert updated_dynamic.raw["data"]["key"] == "updated"

        await DynamicConfigMap.async_delete("test-dynamic-save", ns.name)
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_wait_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-wait", namespace=ns.name), data={"key": "initial"}
        ).async_create()

        async def update_cm():
            with test_config:
                await asyncio.sleep(random.randint(1, 3))
                cm.data["key"] = "updated"
                await cm.async_update()

        update_task = asyncio.create_task(update_cm())

        def check_updated(event_type, obj):
            if event_type != "MODIFIED":
                return None
            return obj.data.get("key") == "updated"

        await cm.async_wait_for(check_updated, timeout=5)
        start_time = time.time()

        with pytest.raises(WaitTimeout):
            await cm.async_wait_for(lambda event_type, _: event_type == "DELETED", timeout=1)
        assert time.time() - start_time < 2

        await update_task
        await cm.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_watch_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        events = []

        async def watch_func():
            with test_config:
                async for event in await k8s.core.v1.Namespace.async_watch(
                    field_selector=f"metadata.name={ns.name}"
                ):
                    events.append(event)

        asyncio.create_task(watch_func())
        await asyncio.sleep(1)

        ns.metadata.annotations = {"test": "test"}
        await ns.async_update()
        await asyncio.sleep(1)

        assert (
            await k8s.core.v1.Namespace.async_delete(ns.name, grace_period_seconds=0)
        ).status.phase == "Terminating"

        await asyncio.sleep(2)
        assert any(
            event[0] == "MODIFIED" and event[1].status.phase == "Terminating" for event in events
        )


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_scale_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()

        # Create a deployment
        deployment = await k8s.apps.v1.Deployment(
            metadata=dict(name="test-scale", namespace=ns.name),
            spec={
                "selector": {"matchLabels": {"app": "test"}},
                "replicas": 1,
                "template": {
                    "metadata": {"labels": {"app": "test"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "nginx",
                                "image": "nginx:latest",
                            }
                        ]
                    },
                },
            },
        ).async_create()

        # Test scaling
        scaled = await deployment.async_scale(replicas=3)
        assert scaled.spec.replicas == 3

        # Verify actual replicas
        current = await k8s.apps.v1.Deployment.async_get("test-scale", ns.name)
        assert current.spec.replicas == 3

        await deployment.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_crd_scale_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()

        # First delete the CRD if it exists
        try:
            await k8s.apiextensions.v1.CustomResourceDefinition.async_delete(
                "webservices.cloudcoil.io"
            )
        except Exception:
            pass

        crd_path = Path(__file__).parent / "data" / "scale_crd.yaml"
        crd = parse_file(crd_path)
        crd = await crd.async_create()

        def check_established(event_type, obj):
            if event_type != "MODIFIED":
                return None
            return any(
                cond.type == "Established" and cond.status == "True"
                for cond in obj.status.conditions or []
            )

        await crd.async_wait_for(check_established, timeout=10)
        test_config.refresh_api_resources()
        # Create a custom resource
        DynamicWebService = get_dynamic_resource("WebService", "cloudcoil.io/v1alpha1")
        webservice = DynamicWebService(
            metadata={"name": "test-scale", "namespace": ns.name},
            spec={"image": "nginx:latest", "size": 3},
        )
        created = await webservice.async_create()
        assert created["spec"]["size"] == 3

        # Update status
        created["status"] = {
            "currentSize": 3,
            "availableReplicas": 2,
            "conditions": [
                {
                    "type": "Available",
                    "status": "True",
                    "lastTransitionTime": "2024-01-01T00:00:00Z",
                    "reason": "MinimumReplicasAvailable",
                    "message": "2 of 3 replicas are available",
                }
            ],
        }
        updated = await created.async_update_status()
        assert updated["status"]["availableReplicas"] == 2
        assert updated["status"]["currentSize"] == 3

        # Test scale subresource
        scaled = await created.async_scale(replicas=5)
        assert scaled["spec"]["size"] == 5

        # Verify actual replicas
        current = await DynamicWebService.async_get("test-scale", ns.name)
        assert current["spec"]["size"] == 5

        await DynamicWebService.async_delete("test-scale", ns.name)
        await crd.async_remove()
        await ns.async_remove()
