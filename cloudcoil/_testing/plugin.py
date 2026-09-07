import os
import random
import string

try:
    import pytest
except ImportError:
    raise ImportError("Please install pytest to enable the testing fixtures")


from cloudcoil._testing.clusters import (
    K3DCluster,
    KindCluster,
)
from cloudcoil.client import Config


@pytest.fixture
def test_cluster(request):
    """Create a cluster; an explicit image overrides the requested Kubernetes version.

    ``CLOUDCOIL_K8S_IMAGE`` selects an image for a CI matrix independently of the
    installed model package, for the provider selected by ``CLUSTER_PROVIDER``
    (default ``kind``). A marker's ``provider`` and ``k8s_image`` take precedence;
    switching provider in a marker also ignores the other provider's image.
    ``version`` is the legacy spelling of ``k8s_version``.
    """
    parameters = {}
    if "configure_test_cluster" in request.keywords:
        parameters = dict(request.keywords["configure_test_cluster"].kwargs)

    default_provider = os.environ.get("CLUSTER_PROVIDER", "kind")
    provider = parameters.get("provider", default_provider)
    k8s_version = parameters.get("k8s_version", parameters.get("version"))
    k8s_image = parameters.get("k8s_image")
    if not k8s_image and provider == default_provider:
        k8s_image = os.environ.get("CLOUDCOIL_K8S_IMAGE")
    remove = parameters.get("remove", True)
    cluster_name = parameters.get(
        "cluster_name", f"test-cluster-{''.join(random.choices(string.ascii_lowercase, k=5))}"
    )

    if provider == "k3d":
        provider = K3DCluster(
            cluster_name,
            remove,
            parameters.get("k3d_version"),
            k8s_version,
            k8s_image,
        )
    elif provider == "kind":
        provider = KindCluster(
            cluster_name,
            remove,
            parameters.get("kind_version"),
            k8s_version,
            k8s_image,
        )
    else:
        raise ValueError(f"Unsupported cluster provider: {provider}")

    provider.create_cluster()
    kubeconfig_path = provider.get_kubeconfig()
    yield kubeconfig_path
    if remove:
        provider.remove_cluster()


@pytest.fixture
def test_config(test_cluster):
    yield Config(kubeconfig=test_cluster)
