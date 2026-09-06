"""Live controller behavior across the repository's Kubernetes/provider CI matrix."""

import asyncio
import importlib.util
import os
from importlib.metadata import version
from pathlib import Path

import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace

from cloudcoil import patches
from cloudcoil.controller import Controller, ensure_finalizer, remove_finalizer
from cloudcoil.errors import APIError, ResourceNotFound

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])


def example_reconciler():
    path = Path(__file__).resolve().parents[1] / "examples" / "configmap_controller.py"
    spec = importlib.util.spec_from_file_location("configmap_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reconcile


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
async def test_live_controller_mirrors_and_repairs_owned_children(test_config):
    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-controller-"}).async_create()
        stop = asyncio.Event()
        task = None
        try:
            source = await ConfigMap(
                metadata={
                    "name": "settings",
                    "namespace": ns.name,
                    "labels": {"example.com/mirror": "true"},
                },
                data={"message": "initial"},
            ).async_create()
            controller = Controller(
                ConfigMap,
                example_reconciler(),
                config=test_config,
                namespace=ns.name,
                label_selector="example.com/mirror=true",
                workers=2,
            ).owns(ConfigMap)
            task = asyncio.create_task(controller.run(stop=stop))
            await controller.wait_ready(timeout=30)

            async def expect_child(data, *, previous_uid=None):
                async with asyncio.timeout(60):
                    while True:
                        if task.done():
                            await task
                            pytest.fail("Controller stopped unexpectedly")
                        try:
                            child = await ConfigMap.async_get("settings-mirror", ns.name)
                            if child.data == data and child.metadata.uid != previous_uid:
                                return child
                        except ResourceNotFound:
                            pass
                        await asyncio.sleep(0.1)

            child = await expect_child({"message": "initial"})
            assert child.metadata.owner_references[0].uid == source.metadata.uid
            # A source present before controller startup must still reconcile.
            original = await ConfigMap.async_get("settings", ns.name)
            desired = original.model_copy(deep=True)
            desired.data = {"message": "updated"}
            await original.async_patch(patches.diff(original, desired))
            child = await expect_child({"message": "updated"})
            # Secondary events repair drift and recreate a deleted child.
            child.data = {"message": "drifted"}
            await child.async_update()
            child = await expect_child({"message": "updated"})
            await child.async_remove()
            await expect_child({"message": "updated"}, previous_uid=child.metadata.uid)
            stop.set()
            await asyncio.wait_for(task, timeout=20)
            assert not controller.ready
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
async def test_live_optimistic_patch_and_finalizer_lifecycle(test_config):
    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-finalizer-"}).async_create()
        obj = None
        try:
            obj = await ConfigMap(
                metadata={"name": "settings", "namespace": ns.name}, data={"key": "before"}
            ).async_create()
            obj = await ensure_finalizer(obj, "cloudcoil.dev/test")
            assert obj.metadata.finalizers == ["cloudcoil.dev/test"]
            assert (
                await ensure_finalizer(obj, "cloudcoil.dev/test")
            ).resource_version == obj.resource_version
            desired = obj.model_copy(deep=True)
            desired.data = {"key": "after"}
            patch = patches.diff(obj, desired)
            updated = await obj.async_patch(patch)
            assert updated.data == {"key": "after"}
            with pytest.raises(APIError):
                await obj.async_patch(patch)  # The resourceVersion test must reject a stale write.
            await updated.async_remove()
            deleting = await ConfigMap.async_get("settings", ns.name)
            assert deleting.metadata.deletion_timestamp is not None
            await remove_finalizer(deleting, "cloudcoil.dev/test")
            async with asyncio.timeout(30):
                while True:
                    try:
                        await ConfigMap.async_get("settings", ns.name)
                    except ResourceNotFound:
                        break
                    await asyncio.sleep(0.1)
        finally:
            # Prevent a failed assertion from stranding a finalizer in the test cluster.
            if obj is not None:
                try:
                    current = await ConfigMap.async_get("settings", ns.name)
                    await remove_finalizer(current, "cloudcoil.dev/test")
                except ResourceNotFound:
                    pass
            await ns.async_remove()
