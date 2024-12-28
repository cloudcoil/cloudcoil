"""Tests for cloudcoil package."""

import pytest

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.kinds.core import v1 as corev1


@pytest.mark.configure_test_cluster(cluster_name="test-cloudcoil", remove=False)
def test_e2e(test_client_set):
    with test_client_set:
        assert corev1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
        output = corev1.Namespace(metadata=ObjectMeta(generate_name="test-")).create()
        name = output.metadata.name
        assert corev1.Namespace.get(name).metadata.name == name
        assert output.remove().metadata.name == name
        assert corev1.Namespace.delete(name).status.phase == "Terminating"


@pytest.mark.configure_test_cluster(cluster_name="test-cloudcoil", remove=False)
async def test_async_e2e(test_client_set):
    with test_client_set:
        assert (
            await corev1.Service.async_get("kubernetes", "default")
        ).metadata.name == "kubernetes"
        output = await corev1.Namespace(metadata=ObjectMeta(generate_name="test-")).async_create()
        name = output.metadata.name
        assert (await corev1.Namespace.async_get(name)).metadata.name == name
        assert (await output.async_remove()).metadata.name == name
        assert (await corev1.Namespace.async_delete(name)).status.phase == "Terminating"
