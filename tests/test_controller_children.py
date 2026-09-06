"""Child convergence and request-scoped clients without a Kubernetes cluster."""

from unittest.mock import AsyncMock

import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace, Service

from cloudcoil.admission import AdmissionRequest
from cloudcoil.client import Config
from cloudcoil.controller import Request, ResourceKey, TerminalError
from cloudcoil.errors import ResourceConflict, ResourceNotFound


@pytest.fixture
def setup():
    parent = ConfigMap(metadata={"name": "site", "namespace": "tenant", "uid": "parent"})
    client = AsyncMock(namespaced=True, default_namespace="wrong-namespace")
    config = AsyncMock(spec=Config)
    config.async_client_for.return_value = client
    request = Request(ResourceKey("site", "tenant"), parent, config=config)
    return request, client


def existing(parent, resource=ConfigMap, **fields):
    return resource.model_validate(
        {
            "metadata": {
                "name": "site",
                "namespace": "tenant",
                "uid": "child",
                "resourceVersion": "7",
                "ownerReferences": [
                    {
                        "apiVersion": parent.api_version,
                        "kind": parent.kind,
                        "name": parent.name,
                        "uid": "parent",
                        "controller": True,
                    }
                ],
            },
            **fields,
        }
    )


async def test_create_defaults_identity_and_ownership_without_mutating_input(setup):
    request, client = setup
    client.get.side_effect = ResourceNotFound("missing")
    desired = ConfigMap(data={"page": "hello"})
    client.create.side_effect = lambda obj: obj
    child = await request.ensure(desired)
    assert child.name == "site" and child.namespace == "tenant"
    assert child.metadata.owner_references[0].uid == "parent"
    assert desired.metadata is None
    client.patch.assert_not_called()


async def test_patch_only_supplied_fields_and_skip_noop(setup):
    request, client = setup
    current = existing(request.resource, data={"page": "old", "external": "keep"})
    client.get.return_value = current
    await request.ensure(ConfigMap(data={"page": "new"}))
    assert client.patch.call_args.args[1] == [
        {"op": "test", "path": "/metadata/uid", "value": "child"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "7"},
        {"op": "replace", "path": "/data/page", "value": "new"},
    ]
    assert current.data == {"page": "old", "external": "keep"}
    client.patch.reset_mock()
    assert await request.ensure(ConfigMap(data={"page": "old"})) is current
    client.patch.assert_not_called()


async def test_service_preserves_allocated_fields_and_replaces_lists(setup):
    request, client = setup
    client.get.return_value = existing(
        request.resource,
        Service,
        spec={
            "clusterIP": "10.0.0.1",
            "ports": [{"port": 80}],
            "selector": {"app": "site"},
        },
    )
    await request.ensure(Service.model_validate({"spec": {"ports": [{"port": 8080}]}}))
    changes = client.patch.call_args.args[1][2:]
    assert changes == [{"op": "replace", "path": "/spec/ports", "value": [{"port": 8080}]}]


async def test_explicit_none_removes_field(setup):
    request, client = setup
    client.get.return_value = existing(request.resource, data={"page": "old"})
    await request.ensure(ConfigMap(data=None))
    assert client.patch.call_args.args[1][-1] == {"op": "remove", "path": "/data"}


@pytest.mark.parametrize(
    "case",
    [
        "foreign",
        "unowned",
        "deleting",
        "cross_namespace",
        "cluster_child",
        "absent",
        "unsaved",
        "parent_deleting",
    ],
)
async def test_refuses_unsafe_ownership(setup, case):
    request, client = setup
    current = existing(request.resource)
    client.get.return_value = current
    desired = ConfigMap()
    error = ValueError
    if case == "foreign":
        current.metadata.owner_references[0].uid = "someone-else"
        error = TerminalError
    elif case == "unowned":
        current.metadata.owner_references = []
        error = TerminalError
    elif case == "deleting":
        current.metadata.deletion_timestamp = "2026-01-01T00:00:00Z"
        error = RuntimeError
    elif case == "cross_namespace":
        desired.metadata = {"namespace": "elsewhere"}
    elif case == "cluster_child":
        desired = Namespace()
        client.namespaced = False
    elif case == "absent":
        request = Request(request.key, None, request.config)
    elif case == "unsaved":
        request.resource.metadata.uid = None
    elif case == "parent_deleting":
        request.resource.metadata.deletion_timestamp = "2026-01-01T00:00:00Z"
        error = TerminalError
    with pytest.raises(error):
        await request.ensure(desired)
    client.create.assert_not_called()
    client.patch.assert_not_called()


async def test_conflicts_propagate_to_controller_retry(setup):
    request, client = setup
    client.get.return_value = existing(request.resource, data={"page": "old"})
    client.patch.side_effect = ResourceConflict("raced", status_code=409)
    with pytest.raises(ResourceConflict):
        await request.ensure(ConfigMap(data={"page": "new"}))


async def test_both_request_types_use_typed_live_clients_and_request_namespace(setup):
    request, client = setup
    assert await request.client(Service) is client
    request.config.async_client_for.assert_awaited_with(Service, cached=False)
    assert client.default_namespace == "tenant"
    admission = AdmissionRequest[ConfigMap](
        uid="review",
        operation="CREATE",
        resource=request.resource,
        old_resource=None,
        namespace="admission-tenant",
        dry_run=True,
    )
    with pytest.raises(RuntimeError, match="config"):
        await admission.client(Service)
    admission._config = request.config
    assert await admission.client(Service) is client
    assert client.default_namespace == "admission-tenant"
    client.create.assert_not_called()
