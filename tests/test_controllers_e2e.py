"""Live controller behavior across the repository's Kubernetes/provider CI matrix."""

import asyncio
import importlib.util
import os
from importlib.metadata import version
from pathlib import Path

import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace

from cloudcoil import patches
from cloudcoil.controller import Controller, ResourceKey, ensure_finalizer, remove_finalizer
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


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
async def test_live_manager_shared_watches_and_lease_handoff(test_config):
    from cloudcoil.controller import LeaderElection, Manager

    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-manager-"}).async_create()
        tasks = []
        stops = [asyncio.Event(), asyncio.Event()]
        seen = [[asyncio.Event(), asyncio.Event()] for _ in range(2)]
        managers = []
        try:
            await ConfigMap(metadata={"name": "settings", "namespace": ns.name}).async_create()
            for replica in range(2):
                controllers = []
                for subscriber in range(2):

                    async def reconcile(req, replica=replica, subscriber=subscriber):
                        if req.name == "settings":
                            assert managers[replica].leader_election.is_leader
                            assert not managers[1 - replica].ready
                            seen[replica][subscriber].set()

                    controllers.append(Controller(ConfigMap, reconcile, namespace=ns.name))
                managers.append(
                    Manager(
                        *controllers,
                        config=test_config,
                        leader_election=LeaderElection(
                            "controller-test",
                            namespace=ns.name,
                            identity=f"replica-{replica}",
                            lease_duration=5,
                            renew_deadline=3,
                            retry_period=0.5,
                        ),
                    )
                )
            tasks.append(asyncio.create_task(managers[0].run(stop=stops[0])))
            await managers[0].wait_ready(timeout=30)
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in seen[0])), 30)
            assert managers[0].informer_count == 1
            tasks.append(asyncio.create_task(managers[1].run(stop=stops[1])))
            await asyncio.sleep(1)
            assert managers[1].healthy and not managers[1].ready
            assert managers[1].informer_count == 0
            stops[0].set()
            await asyncio.wait_for(tasks[0], 20)
            await managers[1].wait_ready(timeout=30)
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in seen[1])), 30)
            assert managers[1].informer_count == 1
            assert not managers[0].ready
            assert "cloudcoil_leader_election_acquisitions_total 1\n" in managers[1].metrics()
            stops[1].set()
            await asyncio.wait_for(tasks[1], 20)
            response = await test_config.async_client.get(
                f"/apis/coordination.k8s.io/v1/namespaces/{ns.name}/leases/controller-test"
            )
            assert response.status_code == 200
            assert not response.json()["spec"].get("holderIdentity")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
async def test_live_returned_crd_patches_spec_and_status_without_write_loop(test_config):
    from uuid import uuid4

    from cloudcoil.models.kubernetes.apiextensions.v1 import CustomResourceDefinition

    from cloudcoil.resources import get_dynamic_resource

    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-return-"}).async_create()
        group = f"test-{uuid4().hex[:12]}.cloudcoil.dev"
        crd = None
        task = None
        writes = []
        attempts = []
        observed = asyncio.Event()
        stop = asyncio.Event()

        async def record(response):
            request = response.request
            if request.method == "PATCH" and f"/namespaces/{ns.name}/widgets/" in request.url.path:
                attempts.append((request.url.path, response.status_code))
                if response.is_success:
                    writes.append(request.url.path)

        test_config.async_client.event_hooks["response"].append(record)
        try:
            crd = await CustomResourceDefinition.model_validate(
                {
                    "metadata": {"name": f"widgets.{group}"},
                    "spec": {
                        "group": group,
                        "scope": "Namespaced",
                        "names": {"plural": "widgets", "singular": "widget", "kind": "Widget"},
                        "versions": [
                            {
                                "name": "v1",
                                "served": True,
                                "storage": True,
                                "subresources": {"status": {}},
                                "schema": {
                                    "openAPIV3Schema": {
                                        "type": "object",
                                        "properties": {
                                            "spec": {
                                                "type": "object",
                                                "properties": {"replicas": {"type": "integer"}},
                                            },
                                            "status": {
                                                "type": "object",
                                                "additionalProperties": {"type": "string"},
                                            },
                                        },
                                    }
                                },
                            }
                        ],
                    },
                }
            ).async_create()
            async with asyncio.timeout(30):
                while True:
                    current = await CustomResourceDefinition.async_get(crd.name)
                    if current.status and any(
                        cond.type == "Established" and cond.status == "True"
                        for cond in current.status.conditions or []
                    ):
                        break
                    await asyncio.sleep(0.1)
            await asyncio.to_thread(test_config.refresh_api_resources)
            widget_type = get_dynamic_resource("Widget", f"{group}/v1")
            await widget_type(
                metadata={"name": "example", "namespace": ns.name}, spec={"replicas": 1}
            ).async_create()

            async def reconcile(request):
                obj = request.resource
                if obj is None:
                    return None
                if obj.raw.get("status", {}).get("phase") == "Ready":
                    observed.set()
                obj["spec"]["replicas"] = 2
                obj["status"] = {"phase": "Ready"}
                return obj

            controller = Controller(widget_type, reconcile, config=test_config, namespace=ns.name)
            task = asyncio.create_task(controller.run(stop=stop))
            await controller.wait_ready(timeout=30)
            await asyncio.wait_for(observed.wait(), 30)
            result = await widget_type.async_get("example", ns.name)
            assert result["spec"] == {"replicas": 2}
            assert result["status"] == {"phase": "Ready"}
            # The watch can briefly expose the intermediate main-write snapshot.
            # A stale follow-up status attempt is safely rejected and may be retried.
            assert all(200 <= code < 300 or code in (409, 422) for _, code in attempts)
            # Process another explicit pass over the persisted object: no new PATCH,
            # including rejected attempts, once the cache contains the final status.
            attempt_count = len(attempts)
            observed.clear()
            controller.enqueue(ResourceKey("example", ns.name))
            await asyncio.wait_for(observed.wait(), 10)
            stop.set()
            await asyncio.wait_for(task, 20)
            assert len(attempts) == attempt_count
            assert len(writes) == 2
            assert not writes[0].endswith("/status") and writes[1].endswith("/status")
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            test_config.async_client.event_hooks["response"].remove(record)
            if crd is not None:
                await crd.async_remove()
            await ns.async_remove()
