"""Tests for cloudcoil package."""

import pytest

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.kinds.core import v1 as corev1


@pytest.mark.configure_test_cluster(cluster_name="test-cloudcoil-v1.31", remove=False)
def test_e2e(test_config):
    with test_config:
        assert corev1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
        output = corev1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        name = output.metadata.name
        assert corev1.Namespace.get(name).metadata.name == name
        output.metadata.annotations = {"test": "test"}
        output = output.update()
        assert output.metadata.annotations == {"test": "test"}
        assert output.remove(dry_run=True).metadata.name == name
        assert corev1.Namespace.delete(name, grace_period_seconds=0).status.phase == "Terminating"


@pytest.mark.configure_test_cluster(
    cluster_name="test-cloudcoil-v1.30", remove=False, version="v1.30.8"
)
async def test_async_e2e(test_config):
    with test_config:
        assert (
            await corev1.Service.async_get("kubernetes", "default")
        ).metadata.name == "kubernetes"
        output = await corev1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        name = output.metadata.name
        assert (await corev1.Namespace.async_get(name)).metadata.name == name
        output.metadata.annotations = {"test": "test"}
        output = await output.async_update()
        assert output.metadata.annotations == {"test": "test"}
        assert (await output.async_remove(dry_run=True)).metadata.name == name
        assert (
            await corev1.Namespace.async_delete(name, grace_period_seconds=0)
        ).status.phase == "Terminating"
