import os
import random
import threading
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
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_basic_crud(test_config):
    with test_config:
        assert k8s.core.v1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
        output = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        name = output.metadata.name
        assert k8s.core.v1.Namespace.get(name).metadata.name == name
        output.metadata.annotations = {"test": "test"}
        output = output.update()
        assert output.metadata.annotations == {"test": "test"}
        assert output.remove(dry_run=True).metadata.name == name
        output.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_list_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        for i in range(3):
            k8s.core.v1.ConfigMap(
                metadata=dict(name=f"test-list-{i}", namespace=ns.name, labels={"test": "true"}),
                data={"key": f"value{i}"},
            ).create()

        cms = k8s.core.v1.ConfigMap.list(namespace=ns.name, label_selector="test=true")
        assert len(cms.items) == 3
        k8s.core.v1.ConfigMap.delete_all(namespace=ns.name, label_selector="test=true")
        assert not k8s.core.v1.ConfigMap.list(namespace=ns.name, label_selector="test=true").items
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_dynamic_resources(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        cm = DynamicConfigMap(
            metadata={"name": "test-cm", "namespace": ns.name}, data={"key": "value"}
        )

        created = cm.create()
        assert created["data"]["key"] == "value"

        fetched = DynamicConfigMap.get("test-cm", ns.name)
        assert fetched.raw.get("data", {}).get("key") == "value"

        fetched["data"]["new_key"] = "new_value"
        updated = fetched.update()
        assert updated.raw.get("data", {}).get("new_key") == "new_value"

        DynamicConfigMap.delete("test-cm", ns.name)
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_save_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()

        # Test regular save
        cm = k8s.core.v1.ConfigMap(
            metadata=dict(name="test-save", namespace=ns.name), data={"key": "value"}
        )
        saved = cm.save()
        assert saved.metadata.name == "test-save"
        assert saved.data["key"] == "value"

        saved.data["key"] = "new-value"
        updated = saved.save()
        assert updated.data["key"] == "new-value"
        saved.remove()

        # Test dynamic save
        DynamicConfigMap = get_dynamic_resource("ConfigMap", "v1")
        dynamic_cm = DynamicConfigMap(
            metadata={"name": "test-dynamic-save", "namespace": ns.name}, data={"key": "value"}
        )
        saved_dynamic = dynamic_cm.save()
        assert saved_dynamic["data"]["key"] == "value"

        saved_dynamic["data"]["key"] = "updated"
        updated_dynamic = saved_dynamic.save()
        assert updated_dynamic.raw["data"]["key"] == "updated"
        DynamicConfigMap.delete("test-dynamic-save", ns.name)
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_wait_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        cm = k8s.core.v1.ConfigMap(
            metadata=dict(name="test-wait", namespace=ns.name), data={"key": "initial"}
        ).create()

        def update_cm():
            with test_config:
                time.sleep(random.randint(1, 3))
                cm.data["key"] = "updated"
                cm.update()

        update_thread = threading.Thread(target=update_cm)
        update_thread.start()

        def check_updated(event_type, obj):
            if event_type != "MODIFIED":
                return None
            return obj.data.get("key") == "updated"

        cm.wait_for(check_updated, timeout=5)
        update_thread.join()

        start_time = time.time()
        with pytest.raises(WaitTimeout):
            cm.wait_for(lambda event_type, _: event_type == "DELETED", timeout=1)
        assert time.time() - start_time < 2

        cm.remove()
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_watch_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        events = []

        def watch_func():
            with test_config:
                events.extend(
                    k8s.core.v1.Namespace.watch(field_selector=f"metadata.name={ns.name}")
                )

        watch_thread = threading.Thread(target=watch_func)
        watch_thread.start()
        time.sleep(1)

        ns.metadata.annotations = {"test": "test"}
        ns.update()
        time.sleep(1)

        assert (
            k8s.core.v1.Namespace.delete(ns.name, grace_period_seconds=0).status.phase
            == "Terminating"
        )

        time.sleep(2)
        assert any(
            event[0] == "MODIFIED" and event[1].status.phase == "Terminating" for event in events
        )


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_scale_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()

        # Create a deployment
        deployment = k8s.apps.v1.Deployment(
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
        ).create()

        # Test scaling
        scaled = deployment.scale(replicas=3)
        assert scaled.spec.replicas == 3

        # Verify actual replicas
        current = k8s.apps.v1.Deployment.get("test-scale", ns.name)
        assert current.spec.replicas == 3

        deployment.remove()
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_crd_scale_operations(test_config):
    with test_config:
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()

        # First delete the CRD if it exists
        try:
            k8s.apiextensions.v1.CustomResourceDefinition.delete("webservices.cloudcoil.io")
        except Exception:
            pass

        crd_path = Path(__file__).parent / "data" / "scale_crd.yaml"
        crd = parse_file(crd_path)
        crd = crd.create()

        def check_established(event_type, obj):
            if event_type != "MODIFIED":
                return None
            return any(
                cond.type == "Established" and cond.status == "True"
                for cond in obj.status.conditions or []
            )

        crd.wait_for(check_established, timeout=10)
        test_config.refresh_api_resources()
        # Create a custom resource
        DynamicWebService = get_dynamic_resource("WebService", "cloudcoil.io/v1alpha1")
        webservice = DynamicWebService(
            metadata={"name": "test-scale", "namespace": ns.name},
            spec={"image": "nginx:latest", "size": 3},
            status={"phase": "Pending"},
        )
        created = webservice.create()
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
        assert "status" in created.model_dump(mode="json", by_alias=True)
        updated = created.update_status()
        assert updated["status"]["availableReplicas"] == 2
        assert updated["status"]["currentSize"] == 3

        # Test scale subresource
        scaled = created.scale(replicas=5)
        assert scaled["spec"]["size"] == 5

        # Verify actual replicas
        current = DynamicWebService.get("test-scale", ns.name)
        assert current["spec"]["size"] == 5

        DynamicWebService.delete("test-scale", ns.name)
        crd.remove()
        ns.remove()
