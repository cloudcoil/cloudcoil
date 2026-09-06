"""Install against a recording API transport, including partial rollout failures."""

import json
from copy import deepcopy

import httpx
import pytest

from cloudcoil.client import Config
from cloudcoil.errors import ResourceConflict
from cloudcoil.operator._install import install


def objects():
    return [
        {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "widgets.example.com"},
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": "widgets", "namespace": "operators"},
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "widgets", "namespace": "operators"},
            "spec": {"replicas": 1},
        },
        {
            "apiVersion": "admissionregistration.k8s.io/v1",
            "kind": "ValidatingWebhookConfiguration",
            "metadata": {"name": "widgets.operators.cloudcoil.io"},
        },
    ]


def established():
    return {
        "metadata": {"name": "widgets.example.com"},
        "status": {"conditions": [{"type": "Established", "status": "True"}]},
    }


def deployment_status(**updates):
    return {
        "metadata": {"generation": 2},
        "status": {
            "observedGeneration": 2,
            "replicas": 1,
            "updatedReplicas": 1,
            "availableReplicas": 1,
            **updates,
        },
    }


@pytest.fixture
async def api(monkeypatch):
    clients = []

    async def make(handler):
        config = Config(server="https://cluster.invalid")
        await config.async_client.aclose()
        config.async_client = httpx.AsyncClient(
            base_url="https://cluster.invalid", transport=httpx.MockTransport(handler)
        )
        refreshed = []
        monkeypatch.setattr(config, "refresh_api_resources", lambda: refreshed.append(True))
        clients.append(config)
        return config, refreshed

    yield make
    for config in clients:
        await config.async_client.aclose()
        config.client.close()


async def test_ssa_order_establishes_crd_then_rolls_out_before_webhooks(api):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "PATCH":
            assert request.headers["Content-Type"] == "application/apply-patch+yaml"
            assert dict(request.url.params) == {"fieldManager": "widgets-manager", "force": "false"}
            return httpx.Response(200, json=json.loads(request.content))
        if "/customresourcedefinitions/" in request.url.path:
            return httpx.Response(200, json=established())
        return httpx.Response(200, json=deployment_status())

    config, refreshed = await api(handler)
    await install(
        config,
        objects(),
        field_manager="widgets-manager",
        timeout=3,
        force=False,
        wait_deployment=True,
    )
    assert [(request.method, request.url.path.split("/")[-2]) for request in requests] == [
        ("PATCH", "customresourcedefinitions"),
        ("GET", "customresourcedefinitions"),
        ("PATCH", "serviceaccounts"),
        ("PATCH", "deployments"),
        ("GET", "deployments"),
        ("PATCH", "validatingwebhookconfigurations"),
    ]
    assert refreshed == [True]
    assert requests[2].url.path == "/api/v1/namespaces/operators/serviceaccounts/widgets"
    assert requests[3].url.path == "/apis/apps/v1/namespaces/operators/deployments/widgets"


@pytest.mark.parametrize(
    "not_ready",
    [
        deployment_status(replicas=2),  # Old ready pod plus new unready pod.
        deployment_status(observedGeneration=1),
        deployment_status(availableReplicas=0),
        deployment_status(updatedReplicas=0),
    ],
)
async def test_rollout_waits_for_current_revision_available_without_old_replicas(api, not_ready):
    gets = 0
    enabled = False

    def handler(request):
        nonlocal gets, enabled
        if request.method == "GET":
            gets += 1
            return httpx.Response(200, json=not_ready if gets == 1 else deployment_status())
        if "validatingwebhookconfigurations" in request.url.path:
            assert gets == 2, "Webhook enabled before the current Deployment was ready"
            enabled = True
        return httpx.Response(200, json={})

    config, refreshed = await api(handler)
    await install(
        config, objects()[2:], field_manager="manager", timeout=3, force=False, wait_deployment=True
    )
    assert enabled and gets == 2
    assert refreshed == []


async def test_crd_must_establish_before_runtime_objects_are_applied(api):
    gets = 0
    applied = []

    def handler(request):
        nonlocal gets
        if request.method == "GET":
            gets += 1
            return httpx.Response(200, json=established() if gets == 2 else {"status": {}})
        manifest = json.loads(request.content)
        if manifest["kind"] == "ServiceAccount":
            assert gets == 2
        applied.append(manifest["kind"])
        return httpx.Response(200, json={})

    config, refreshed = await api(handler)
    await install(
        config,
        objects()[:2],
        field_manager="manager",
        timeout=3,
        force=False,
        wait_deployment=False,
    )
    assert applied == ["CustomResourceDefinition", "ServiceAccount"]
    assert refreshed == [True]


async def test_rejected_crd_name_stops_installation_without_rollback(api):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "GET":
            obj = established()
            obj["status"]["conditions"].append({"type": "NamesAccepted", "status": "False"})
            return httpx.Response(200, json=obj)
        return httpx.Response(200, json={})

    config, refreshed = await api(handler)
    with pytest.raises(RuntimeError, match="CRD name rejected"):
        await install(
            config, objects(), field_manager="manager", timeout=3, force=False, wait_deployment=True
        )
    assert methods == ["PATCH", "GET"]
    assert not refreshed


@pytest.mark.parametrize("force", [False, True])
async def test_apply_conflicts_surface_without_retry_or_rollback(api, force):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(409, json={"message": "field owned by another manager"})

    config, refreshed = await api(handler)
    with pytest.raises(ResourceConflict):
        await install(
            config, objects(), field_manager="manager", timeout=3, force=force, wait_deployment=True
        )
    assert len(requests) == 1
    assert requests[0].url.params["force"] == str(force).lower()
    assert not refreshed


async def test_rollout_timeout_leaves_foundation_without_registering_webhooks(api):
    methods = []

    def handler(request):
        methods.append((request.method, request.url.path))
        assert "validatingwebhookconfigurations" not in request.url.path
        if request.method == "GET":
            return httpx.Response(200, json=deployment_status(replicas=2))
        return httpx.Response(200, json={})

    config, refreshed = await api(handler)
    with pytest.raises(TimeoutError):
        await install(
            config,
            objects()[1:],
            field_manager="manager",
            timeout=0.05,
            force=False,
            wait_deployment=True,
        )
    assert [method for method, _ in methods] == ["PATCH", "PATCH", "GET"]
    assert not refreshed


async def test_apply_is_repeatable_and_does_not_mutate_desired_manifests(api):
    patches = []

    def handler(request):
        patches.append(json.loads(request.content))
        return httpx.Response(200, json={})

    config, _ = await api(handler)
    manifests = objects()[1:2]
    original = deepcopy(manifests)
    for _ in range(2):
        await install(
            config,
            manifests,
            field_manager="manager",
            timeout=3,
            force=False,
            wait_deployment=False,
        )
    assert manifests == original
    assert patches == [original[0], original[0]]
