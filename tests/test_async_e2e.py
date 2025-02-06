import asyncio
import os
import random
import time
from importlib.metadata import version

import pytest

import cloudcoil.models.kubernetes as k8s
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.errors import WaitTimeout
from cloudcoil.resources import get_dynamic_resource

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
async def test_async_status_operations(test_config):
    with test_config:
        ns = await k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()

        # Create a Job
        job = k8s.batch.v1.Job(
            metadata=dict(name="test-status", namespace=ns.name),
            spec={
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "test", "image": "busybox", "command": ["sh", "-c", "sleep 1"]}
                        ],
                        "restartPolicy": "Never",
                    }
                }
            },
        )
        created = await job.async_create()

        # Test status update
        now = "2024-01-01T00:00:00+00:00"
        created.status.start_time = now
        updated = await created.async_update(with_status=True)
        assert updated.status.start_time.root.isoformat() == now
        await job.async_remove()
        await ns.async_remove()
