import os
from importlib.metadata import version

import pytest

from cloudcoil.client.errors import ResourceNotFound
from cloudcoil.models.kubernetes import core

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
cluster_provider = os.environ.get("CLUSTER_PROVIDER", "kind")


@pytest.fixture()
@pytest.mark.configure_test_cluster(
    version=f"v{k8s_version}",
    provider=cluster_provider,
)
def test_namespace(test_config):
    """Create test namespace that's cleaned up after each test"""
    with test_config:
        ns = core.v1.Namespace(
            metadata=dict(generate_name="cloudcoil-test-", labels={"test": "true"})
        ).create()
        yield ns.name
        try:
            ns.remove()
        except ResourceNotFound:
            pass


@pytest.fixture()
@pytest.mark.configure_test_cluster(
    version=f"v{k8s_version}",
    provider=cluster_provider,
)
def test_configmap(test_config, test_namespace):
    """Create test configmap that's cleaned up after each test"""
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-cm", namespace=test_namespace), data={"key": "value"}
        ).create()
        yield cm
        try:
            cm.remove()
        except ResourceNotFound:
            pass


def test_create_configmap(test_config, test_namespace):
    with test_config:
        # Test basic creation
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-create", namespace=test_namespace), data={"key": "value"}
        ).create()

        assert cm.metadata.name == "test-create"
        assert cm.data["key"] == "value"


def test_create_with_generate_name(test_config, test_namespace):
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(generate_name="test-gen-", namespace=test_namespace),
            data={"key": "value"},
        ).create()

        assert cm.metadata.name.startswith("test-gen-")
        assert cm.data["key"] == "value"


def test_create_dry_run(test_config, test_namespace):
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-dry-run", namespace=test_namespace), data={"key": "value"}
        ).create(dry_run=True)

        assert cm.metadata.name == "test-dry-run"
        with pytest.raises(ResourceNotFound):
            core.v1.ConfigMap.get("test-dry-run", namespace=test_namespace)


def test_get_configmap(test_config, test_namespace, test_configmap):
    with test_config:
        cm = core.v1.ConfigMap.get(test_configmap.name, namespace=test_namespace)
        assert cm.metadata.name == test_configmap.name
        assert cm.data["key"] == "value"


def test_get_nonexistent(test_config, test_namespace):
    with test_config:
        with pytest.raises(ResourceNotFound):
            core.v1.ConfigMap.get("nonexistent", namespace=test_namespace)


def test_update_configmap(test_config, test_namespace, test_configmap):
    with test_config:
        test_configmap.data["key"] = "updated"
        test_configmap.data["new_key"] = "new_value"
        updated = test_configmap.update()

        assert updated.data["key"] == "updated"
        assert updated.data["new_key"] == "new_value"


def test_update_dry_run(test_config, test_namespace, test_configmap):
    with test_config:
        test_configmap.data["key"] = "dry-run-value"
        dry_run = test_configmap.update(dry_run=True)

        assert dry_run.data["key"] == "dry-run-value"
        fresh = core.v1.ConfigMap.get(test_configmap.name, namespace=test_namespace)
        assert fresh.data["key"] == "value"


def test_delete_configmap(test_config, test_namespace):
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-delete", namespace=test_namespace), data={"key": "value"}
        ).create()

        cm.remove()
        with pytest.raises(ResourceNotFound):
            core.v1.ConfigMap.get(cm.name, namespace=test_namespace)


def test_remove_configmap(test_config, test_namespace):
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-remove", namespace=test_namespace), data={"key": "value"}
        ).create()

        cm.remove()
        with pytest.raises(ResourceNotFound):
            cm = core.v1.ConfigMap.get(cm.name, namespace=test_namespace)
            assert not cm


def test_list_configmaps(test_config, test_namespace):
    with test_config:
        # Create test resources
        for i in range(3):
            core.v1.ConfigMap(
                metadata=dict(
                    name=f"test-list-{i}", namespace=test_namespace, labels={"test": "true"}
                ),
                data={"key": f"value{i}"},
            ).create()

        # Test list with label selector
        cms = core.v1.ConfigMap.list(namespace=test_namespace, label_selector="test=true")
        assert len(cms.items) == 3


def test_list_with_field_selector(test_config, test_namespace):
    with test_config:
        cm = core.v1.ConfigMap(
            metadata=dict(name="test-field-select", namespace=test_namespace), data={"key": "value"}
        ).create()

        cms = core.v1.ConfigMap.list(
            namespace=test_namespace, field_selector=f"metadata.name={cm.name}"
        )
        assert len(cms.items) == 1
        assert cms.items[0].metadata.name == cm.name


def test_delete_all_configmaps(test_config, test_namespace):
    with test_config:
        # Create batch of resources
        for i in range(3):
            core.v1.ConfigMap(
                metadata=dict(
                    name=f"test-delete-all-{i}",
                    namespace=test_namespace,
                    labels={"batch": "delete-all"},
                ),
                data={"key": f"value{i}"},
            ).create()

        output = core.v1.ConfigMap.delete_all(
            namespace=test_namespace, label_selector="batch=delete-all"
        )
        assert len(output.items) == 3
        remaining = core.v1.ConfigMap.list(
            namespace=test_namespace, label_selector="batch=delete-all"
        )
        assert len(remaining.items) == 0


@pytest.mark.asyncio
async def test_async_crud_operations(test_config, test_namespace):
    with test_config:
        # Create
        cm = await core.v1.ConfigMap(
            metadata=dict(name="test-async", namespace=test_namespace), data={"key": "value"}
        ).async_create()

        assert cm.metadata.name == "test-async"

        # Get
        fetched = await core.v1.ConfigMap.async_get("test-async", namespace=test_namespace)
        assert fetched.data["key"] == "value"

        # Update
        fetched.data["key"] = "updated"
        updated = await fetched.async_update()
        assert updated.data["key"] == "updated"

        # List
        cms = await core.v1.ConfigMap.async_list(namespace=test_namespace)
        count = 0
        async for _ in cms:
            count += 1
        assert count > 0

        # Delete
        await fetched.async_remove()
        with pytest.raises(ResourceNotFound):
            await core.v1.ConfigMap.async_get("test-async", namespace=test_namespace)
