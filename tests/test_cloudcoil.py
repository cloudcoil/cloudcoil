"""Tests for cloudcoil package."""

import pytest

from cloudcoil.models.core import v1 as corev1


@pytest.mark.configure_test_cluster(cluster_name="test-version", remove=False)
def test_version(test_clientset):
    with test_clientset:
        assert corev1.Service.get("kubernetes", "default").metadata.name == "kubernetes"
