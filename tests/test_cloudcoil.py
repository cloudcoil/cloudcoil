"""Tests for cloudcoil package."""

import pytest

from cloudcoil.models.apimachinery import v1 as metav1
from cloudcoil.models.core import v1 as corev1


@pytest.mark.configure_test_cluster(cluster_name="test-version", remove=False)
def test_version(test_clientset):
    with test_clientset:
        assert corev1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
        output = corev1.Namespace(metadata=metav1.ObjectMeta(generate_name="test-")).create()
        name = output.metadata.name
        assert corev1.Namespace.get(name).metadata.name == name
        assert output.remove().metadata.name == name
        assert corev1.Namespace.delete(name).status.phase == "Terminating"
