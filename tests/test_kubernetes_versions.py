"""Shared metadata and resources added by the latest Kubernetes schema."""

from importlib import import_module
from importlib.metadata import version

import pytest

from cloudcoil.apimachinery import GroupResource, ListMeta


def test_latest_shared_metadata_round_trip():
    metadata = ListMeta.model_validate(
        {"resourceVersion": "42", "shardInfo": {"selector": "shard=one"}}
    )
    assert metadata.shard_info.selector == "shard=one"
    assert metadata.model_dump(by_alias=True, exclude_none=True) == {
        "resourceVersion": "42",
        "shardInfo": {"selector": "shard=one"},
    }
    assert GroupResource.builder().group("apps").resource("deployments").build() == (
        GroupResource(group="apps", resource="deployments")
    )


@pytest.mark.skipif(
    tuple(map(int, version("cloudcoil.models.kubernetes").split(".")[:2])) < (1, 37),
    reason="Runs with the generated Kubernetes 1.37 models in CI",
)
def test_latest_generated_resource_imports_and_builders():
    migration = import_module("cloudcoil.models.kubernetes.storagemigration.v1")
    certificates = import_module("cloudcoil.models.kubernetes.certificates.v1")
    resource = (
        migration.StorageVersionMigration.builder()
        .metadata(lambda meta: meta.name("example"))
        .spec(
            lambda spec: spec.resource(lambda target: target.group("apps").resource("deployments"))
        )
        .build()
    )
    assert resource.gvk().api_version == "storagemigration.k8s.io/v1"
    assert resource.model_dump(by_alias=True)["spec"]["resource"] == {
        "group": "apps",
        "resource": "deployments",
    }
    assert certificates.PodCertificateRequest.gvk().api_version == "certificates.k8s.io/v1"
