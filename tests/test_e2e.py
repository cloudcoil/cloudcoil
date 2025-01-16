"""Tests for cloudcoil package."""

import asyncio
import os
import threading
import time
from importlib.metadata import version

import pytest

import cloudcoil.models.kubernetes as k8s
from cloudcoil.apimachinery import ObjectMeta

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
cluster_provider = os.environ.get("CLUSTER_PROVIDER", "kind")


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_e2e(test_config):
    from cloudcoil.resources import get_dynamic_resource

    with test_config:
        assert k8s.core.v1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
        output = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        name = output.metadata.name
        assert k8s.core.v1.Namespace.get(name).metadata.name == name
        output.metadata.annotations = {"test": "test"}
        output = output.update()
        assert output.metadata.annotations == {"test": "test"}
        assert output.remove(dry_run=True).metadata.name == name
        for i in range(3):
            k8s.core.v1.ConfigMap(
                metadata=dict(
                    name=f"test-list-{i}", namespace=output.name, labels={"test": "true"}
                ),
                data={"key": f"value{i}"},
            ).create()

        # Test list with label selector
        cms = k8s.core.v1.ConfigMap.list(namespace=output.name, label_selector="test=true")
        assert len(cms.items) == 3
        k8s.core.v1.ConfigMap.delete_all(namespace=output.name, label_selector="test=true")
        assert not k8s.core.v1.ConfigMap.list(
            namespace=output.name, label_selector="test=true"
        ).items

        # Test dynamic ConfigMap
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        cm = DynamicConfigMap(
            metadata={"name": "test-cm", "namespace": output.name}, data={"key": "value"}
        )

        created = cm.create()
        assert created["data"]["key"] == "value"

        fetched = DynamicConfigMap.get("test-cm", output.name)
        assert fetched.raw.get("data", {}).get("key") == "value"

        fetched["data"]["new_key"] = "new_value"
        updated = fetched.update()
        assert updated.raw.get("data", {}).get("new_key") == "new_value"

        DynamicConfigMap.delete("test-cm", output.name)

        # Setup watch before deletion
        events = []

        def watch_func():
            with test_config:  # Ensure config is active in the thread
                events.extend(k8s.core.v1.Namespace.watch(field_selector=f"metadata.name={name}"))

        watch_thread = threading.Thread(target=watch_func)
        watch_thread.start()
        time.sleep(1)  # Give the watch time to establish

        # Delete the namespace and observe events
        assert (
            k8s.core.v1.Namespace.delete(name, grace_period_seconds=0).status.phase == "Terminating"
        )

        # Wait for the watch thread to receive events
        time.sleep(2)
        assert any(
            event[0] == "MODIFIED" and event[1].status.phase == "Terminating" for event in events
        )

        assert (
            k8s.core.v1.Namespace.delete(name, grace_period_seconds=0).status.phase == "Terminating"
        )
        assert len(k8s.core.v1.Pod.list(all_namespaces=True, limit=1)) > 1
        assert len(k8s.core.v1.Pod.list(all_namespaces=True, limit=1).items) == 1


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-async-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_e2e(test_config):
    from cloudcoil.resources import get_dynamic_resource

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
        for i in range(3):
            await k8s.core.v1.ConfigMap(
                metadata=dict(
                    name=f"test-list-{i}", namespace=output.name, labels={"test": "true"}
                ),
                data={"key": f"value{i}"},
            ).async_create()

        # Test list with label selector
        cms = await k8s.core.v1.ConfigMap.async_list(
            namespace=output.name, label_selector="test=true"
        )
        assert len(cms.items) == 3
        await k8s.core.v1.ConfigMap.async_delete_all(
            namespace=output.name, label_selector="test=true"
        )
        assert not (
            await k8s.core.v1.ConfigMap.async_list(
                namespace=output.name, label_selector="test=true"
            )
        ).items

        # Test dynamic resources
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        cm = DynamicConfigMap(
            metadata={"name": "test-cm", "namespace": output.name}, data={"key": "value"}
        )

        created = await cm.async_create()
        assert created["data"]["key"] == "value"
        fetched = DynamicConfigMap.get("test-cm", output.name)
        assert fetched.raw.get("data", {}).get("key") == "value"

        fetched["data"]["new_key"] = "new_value"
        updated = await fetched.async_update()
        assert updated.raw.get("data", {}).get("new_key") == "new_value"

        await DynamicConfigMap.async_delete("test-cm", output.name)

        # Setup watch before deletion
        events = []

        async def watch_func():
            with test_config:  # Ensure config is active in the thread
                async for event in await k8s.core.v1.Namespace.async_watch(  # async_watch returns AsyncGenerator directly
                    field_selector=f"metadata.name={name}"
                ):
                    events.append(event)

        asyncio.create_task(watch_func())
        await asyncio.sleep(1)  # Give the watch time to establish

        # Delete the namespace and observe events
        assert (
            await k8s.core.v1.Namespace.async_delete(name, grace_period_seconds=0)
        ).status.phase == "Terminating"

        # Wait for events
        await asyncio.sleep(2)
        assert any(
            event[0] == "MODIFIED" and event[1].status.phase == "Terminating" for event in events
        )

        assert (
            await k8s.core.v1.Namespace.async_delete(name, grace_period_seconds=0)
        ).status.phase == "Terminating"
        assert len(await k8s.core.v1.Pod.async_list(all_namespaces=True, limit=1)) > 1
        assert len((await k8s.core.v1.Pod.async_list(all_namespaces=True, limit=1)).items) == 1
