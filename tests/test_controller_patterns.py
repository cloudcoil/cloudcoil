"""Exercise the shipped pattern examples and their cache/admission contracts."""

import base64
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace, Pod, Service

from cloudcoil.admission import AdmissionRequest
from cloudcoil.caching import AsyncInformer, CachedResources
from cloudcoil.caching._types import InformerOptions
from cloudcoil.client import APIClient, AsyncAPIClient
from cloudcoil.controller import Request, ResourceKey
from cloudcoil.errors import ResourceConflict


def informer(resource, *objects, namespaced=True):
    client = Mock(kind=resource, namespaced=namespaced)
    result = AsyncInformer(client, InformerOptions(max_items=0))
    result._started = True
    result._sync_event.set()
    result._store.replace(list(objects))
    return result


def deployment(name="app", team=None, replicas=1):
    return Deployment.model_validate(
        {
            "metadata": {
                "name": name,
                "namespace": "tenant",
                "uid": name,
                "resourceVersion": "1",
                "labels": {"team": team} if team else {},
            },
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "containers": [
                            {
                                "name": "web",
                                "image": "nginx:stable",
                                "envFrom": [{"configMapRef": {"name": "settings"}}],
                            }
                        ],
                    },
                },
            },
        }
    )


def test_cache_reads_are_scoped_copied_and_never_silently_unsynced():
    first = ConfigMap(
        metadata={"name": "a", "namespace": "one", "labels": {"app": "x", "tier": "web"}},
        data={"key": "value"},
    )
    second = ConfigMap(metadata={"name": "a", "namespace": "two", "labels": {"app": "x"}})
    source = informer(ConfigMap, first, second)
    reader = CachedResources(source, "one")
    assert reader.get("missing") is None
    assert len(reader.list(labels={"app": "x", "tier": "web"})) == 1
    assert len(reader.list(all_namespaces=True)) == 2
    assert reader.get("a", "two").namespace == "two"
    reader.get("a").data["key"] = "edited"
    reader.list()[0].metadata.labels.clear()
    assert first.data == {"key": "value"} and first.metadata.labels["app"] == "x"
    source._sync_event.clear()
    with pytest.raises(RuntimeError, match="synced"):
        reader.list()
    source._sync_event.set()
    source._watch._error = RuntimeError("forbidden")
    with pytest.raises(RuntimeError, match="failed"):
        reader.get("a")
    with pytest.raises(ValueError, match="not watched"):
        Request(ResourceKey("a", "one"), first).cached(Pod)


async def test_reloader_uses_cached_dependency_and_returns_only_template_change():
    from examples.patterns import dependency_rollout as pattern

    obj = deployment()
    config = ConfigMap(
        metadata={"name": "settings", "namespace": "tenant"}, data={"value": "first"}
    )
    source = informer(ConfigMap, config)
    request = Request(ResourceKey("app", "tenant"), obj, _informers={ConfigMap: source})
    result = await pattern.reconcile(request)
    digest = result.spec.template.metadata.annotations[pattern.DIGEST]
    assert await pattern.reconcile(request) == result
    config.data["value"] = "second"
    changed = await pattern.reconcile(request)
    assert changed.spec.template.metadata.annotations[pattern.DIGEST] != digest
    assert changed.spec.template.spec.containers[0].image == "nginx:stable"
    controller = pattern.controller()
    controller.config = SimpleNamespace(namespace="tenant")
    controller._readers[Deployment] = informer(Deployment, obj, deployment("other"))
    assert controller._watches[0].mapper(config) == [
        ResourceKey("app", "tenant"),
        ResourceKey("other", "tenant"),
    ]


async def test_workload_aggregates_existing_pods_and_maps_label_changes():
    from examples.patterns import workload_summary as pattern

    obj = pattern.Workload(
        metadata={"name": "summary", "namespace": "tenant", "generation": 2},
        spec=pattern.WorkloadSpec(selector={"app": "web"}),
    )
    pod = Pod.model_validate(
        {
            "metadata": {"name": "pod", "namespace": "tenant", "labels": {"app": "web"}},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }
    )
    other = Pod(metadata={"name": "other", "namespace": "other", "labels": {"app": "web"}})
    request = Request(
        ResourceKey("summary", "tenant"), obj, _informers={Pod: informer(Pod, pod, other)}
    )
    result = await pattern.reconcile(request)
    assert result.status.pods == result.status.ready == 1
    assert result.status.observed_generation == 2
    controller = pattern.controller()
    controller.config = SimpleNamespace(namespace="tenant")
    controller._readers[pattern.Workload] = informer(pattern.Workload, obj)
    mapper = controller._watches[0].mapper
    assert mapper(pod) == [ResourceKey("summary", "tenant")]
    pod.metadata.labels = {"app": "elsewhere"}
    assert mapper(pod) == []


@pytest.mark.parametrize(
    "observed,updated,total,available,complete",
    [
        (1, 1, 1, 1, False),
        (2, 0, 1, 1, False),
        (2, 1, 2, 1, False),
        (2, 1, 1, 0, False),
        (2, 1, 1, 1, True),
    ],
)
async def test_widget_stages_check_current_rollout(
    observed, updated, total, available, complete, monkeypatch
):
    from unittest.mock import AsyncMock

    from cloudcoil.controller import get_condition
    from examples import widget_operator as example

    obj = example.Widget(
        metadata={"name": "widget", "namespace": "tenant", "uid": "parent", "generation": 2},
        spec=example.WidgetSpec(message="hello"),
    )
    deployment = Deployment.model_validate(
        {
            "metadata": {"name": "widget", "generation": 2},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "widget"}},
                "template": {
                    "metadata": {"labels": {"app": "widget"}},
                    "spec": {"containers": [{"name": "web", "image": "nginx:stable"}]},
                },
            },
            "status": {
                "observedGeneration": observed,
                "updatedReplicas": updated,
                "replicas": total,
                "availableReplicas": available,
                "readyReplicas": 1,
            },
        }
    )
    ensure = AsyncMock()
    client = AsyncMock(return_value=SimpleNamespace(get=AsyncMock(return_value=deployment)))
    monkeypatch.setattr(Request, "ensure", ensure)
    monkeypatch.setattr(Request, "client", client)
    req = Request(ResourceKey("widget", "tenant"), obj)
    result = await example.reconcile(req)
    assert [type(call.args[0]) for call in ensure.call_args_list] == [
        ConfigMap,
        Deployment,
        Service,
    ]
    client.assert_awaited_once_with(Deployment)
    assert get_condition(obj, "Ready").status == ("True" if complete else "False")
    assert obj.status.phase == ("Ready" if complete else "Pending")
    assert result.requeue_after == (None if complete else 10)


async def test_conditional_example_suspension_dependency_and_convergence(monkeypatch):
    from unittest.mock import AsyncMock

    from cloudcoil.controller import get_condition
    from examples.patterns import conditional_config as example

    obj = example.ApplicationConfig(
        metadata={"name": "consumer", "namespace": "tenant", "uid": "parent", "generation": 1},
        spec=example.ConfigSpec(configMap="settings", suspended=True),
    )
    app = example.build_app()
    ensure = AsyncMock()
    monkeypatch.setattr(Request, "ensure", ensure)
    # Suspended short-circuits without even accessing an informer.
    req = Request(ResourceKey("consumer", "tenant"), obj)
    assert (await app.controllers[0].reconcile(req)).requeue_after == 300
    obj.spec.suspended = False
    req = Request(req.key, obj, _informers={ConfigMap: informer(ConfigMap)})
    assert (await app.controllers[0].reconcile(req)).requeue_after == 30
    assert get_condition(obj, "Ready").reason == "ConfigMapMissing"
    ensure.assert_not_awaited()
    source = ConfigMap(metadata={"name": "settings", "namespace": "tenant"}, data={"key": "value"})
    req = Request(req.key, obj, _informers={ConfigMap: informer(ConfigMap, source)})
    await app.controllers[0].reconcile(req)
    ensure.assert_awaited_once()
    assert ensure.call_args.args[0].data == source.data
    assert get_condition(obj, "Ready").status == "True"


async def test_child_set_prunes_only_owned_entries_with_identity_guards():
    from examples.patterns import child_set as pattern

    obj = pattern.Bundle(
        metadata={"name": "bundle", "namespace": "tenant", "uid": "parent"},
        spec=pattern.BundleSpec(entries={"a": "value"}),
    )

    def child(name, owner):
        return ConfigMap(
            metadata={
                "name": name,
                "namespace": "tenant",
                "uid": name,
                "resourceVersion": "4",
                "labels": {pattern.OWNER: "parent"},
                "ownerReferences": [
                    {
                        "apiVersion": obj.api_version,
                        "kind": obj.kind,
                        "name": "bundle",
                        "uid": owner,
                        "controller": True,
                    }
                ],
            }
        )

    stale, foreign = child("stale", "parent"), child("foreign", "someone-else")
    client = AsyncMock()
    request = SimpleNamespace(
        resource=obj,
        ensure=AsyncMock(),
        client=AsyncMock(return_value=client),
        cached=lambda model: CachedResources(informer(ConfigMap, stale, foreign), "tenant"),
    )
    await pattern.reconcile(request)
    assert request.ensure.await_count == 1
    client.delete.assert_awaited_once_with("stale", uid="stale", resource_version="4")


async def test_finalizer_is_persisted_before_external_work_and_removed_after_cleanup(monkeypatch):
    from examples.patterns import finalizers as pattern

    events = []
    obj = pattern.ExternalRecord(
        metadata={"name": "record", "namespace": "tenant", "uid": "id"},
        spec=pattern.RecordSpec(value="value"),
    )

    async def add(resource, name, **kwargs):
        events.append("finalizer")
        obj.metadata.finalizers = [name]
        return obj

    async def remove(resource, name, **kwargs):
        events.append("remove")
        return obj

    async def put(key, value):
        events.append("put")

    async def delete(key):
        events.append("delete")

    monkeypatch.setattr(pattern, "ensure_finalizer", add)
    monkeypatch.setattr(pattern, "remove_finalizer", remove)
    app = pattern.build_app(SimpleNamespace(put=put, delete=delete))
    request = Request(ResourceKey("record", "tenant"), obj)
    result = await app.controllers[0].reconcile(request)
    assert events == ["finalizer", "put"] and result.requeue_after == 60
    obj.metadata.deletion_timestamp = "2026-09-07T00:00:00Z"
    await app.controllers[0].reconcile(request)
    assert events[-2:] == ["delete", "remove"]


async def review(
    app, path, obj, *, old=None, operation="CREATE", namespace="tenant", expected_status=200
):
    model = obj or old
    route = app._routes[path]
    gvk = model.gvk()
    target = (route.target or route.model).gvk()
    payload = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "review",
            "operation": operation,
            "name": model.name,
            "namespace": namespace,
            "dryRun": True,
            "kind": {"group": gvk.group, "version": gvk.version, "kind": gvk.kind},
            "resource": {
                "group": target.group,
                "version": target.version,
                "resource": route.resource,
            },
            "subResource": route.subresource,
            "object": obj.model_dump(mode="json", by_alias=True, exclude_none=True)
            if obj
            else None,
            "oldObject": old.model_dump(mode="json", by_alias=True, exclude_none=True)
            if old
            else None,
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admission"
    ) as client:
        response = await client.post(path, json=payload)
        assert response.status_code == expected_status
        return response.json()["response"] if expected_status == 200 else response.json()


async def test_existing_resource_admission_shares_config_and_handles_create_update_delete():
    from examples.patterns.admission_existing import build_app

    app = build_app()
    api = AsyncMock(namespaced=True)
    api.get.return_value = ConfigMap(data={"maxReplicas": "2"})
    config = SimpleNamespace(async_client_for=AsyncMock(return_value=api))
    admission = app._admission(config)
    result = await review(admission, "/validate-deployment", deployment(replicas=3))
    assert not result["allowed"] and "2 replicas" in result["status"]["message"]
    assert api.default_namespace == "tenant"
    mutation = await review(admission, "/default-deployment", deployment())
    assert mutation["allowed"] and b"unassigned" in base64.b64decode(mutation["patch"])
    allowed = await review(
        admission,
        "/validate-deployment",
        deployment(team="unassigned"),
        old=deployment(),
        operation="UPDATE",
    )
    assert allowed["allowed"]  # Existing unlabeled Deployments can acquire the default.
    denied = await review(
        admission,
        "/validate-deployment",
        deployment(team="new"),
        old=deployment(team="old"),
        operation="UPDATE",
    )
    assert not denied["allowed"]
    protected = deployment()
    protected.metadata.annotations = {"patterns.cloudcoil.dev/protect": "true"}
    assert not (
        await review(admission, "/protect-delete", None, old=protected, operation="DELETE")
    )["allowed"]
    api.create.assert_not_called()
    assert app.admission._config is None  # Runtime binding did not mutate the definition.


async def test_external_crd_admission_uses_old_object_without_installing_or_owning_crd():
    from examples.patterns.admission_external_crd import Database, DatabaseSpec, build_app

    app = build_app()
    old = Database(metadata={"name": "db", "namespace": "tenant"}, spec=DatabaseSpec(storageGiB=20))
    new = old.model_copy(deep=True)
    new.spec.storage_gib = 10
    result = await review(app._admission(), "/database-storage", new, old=old, operation="UPDATE")
    assert not result["allowed"]
    assert not app.crds and not app.controllers


async def test_admission_cache_requires_explicit_synced_replica_local_informer():
    from examples.patterns.admission_cached import build_app

    app = build_app()
    ns = Namespace(
        metadata={"name": "tenant", "labels": {"patterns.cloudcoil.dev/allow-pods": "true"}}
    )
    source = informer(Namespace, ns, namespaced=False)
    config = SimpleNamespace(
        cache=SimpleNamespace(
            enabled=True, resources=[Namespace], get_informer=Mock(return_value=source)
        )
    )
    admission = app._admission(config)
    pod = Pod(metadata={"name": "pod", "namespace": "tenant"})
    assert (await review(admission, "/namespace-policy", pod))["allowed"]
    ns.metadata.labels.clear()
    assert not (await review(admission, "/namespace-policy", pod))["allowed"]
    source._sync_event.clear()
    result = await review(admission, "/namespace-policy", pod, expected_status=500)
    assert "failed" in result["message"]
    request = AdmissionRequest[Pod](uid="id", operation="CREATE", resource=pod, old_resource=None)
    with pytest.raises(ValueError, match="preconfigured"):
        request.cached(Namespace)


@pytest.mark.parametrize(
    "module",
    [
        "dependency_rollout",
        "conditional_config",
        "workload_summary",
        "child_set",
        "finalizers",
        "admission_existing",
        "admission_external_crd",
        "admission_cached",
        "multiple_controllers",
    ],
)
def test_every_example_builds_offline_manifests(module):
    from dataclasses import replace

    app = importlib.import_module(f"examples.patterns.{module}").build_app()
    if app.webhook:
        app.webhook = replace(app.webhook, ca_bundle=b"-----BEGIN CERTIFICATE-----\npublic")
    documents = app.manifests(image="example/operator:v1")
    assert any(doc["kind"] == "Deployment" for doc in documents)
    if module.startswith("admission_"):
        assert not any(doc["kind"] == "CustomResourceDefinition" for doc in documents)
        assert any(doc["kind"].endswith("WebhookConfiguration") for doc in documents)


@pytest.mark.parametrize("sync", [True, False])
async def test_guarded_delete_sends_preconditions_and_surfaces_conflicts(sync):
    def handle(request):
        assert json.loads(request.content)["preconditions"] == {
            "uid": "old",
            "resourceVersion": "4",
        }
        assert request.url.params["dryRun"] == "All"
        return httpx.Response(409, json={"message": "UID differs"})

    transport = httpx.MockTransport(handle)
    options = dict(
        api_version="v1",
        kind=ConfigMap,
        resource="configmaps",
        subresources=[],
        default_namespace="tenant",
        namespaced=True,
    )
    if sync:
        with httpx.Client(transport=transport, base_url="https://cluster") as http:
            client = APIClient(client=http, **options)
            with pytest.raises(ResourceConflict):
                client.delete("old", dry_run=True, uid="old", resource_version="4")
    else:
        async with httpx.AsyncClient(transport=transport, base_url="https://cluster") as http:
            client = AsyncAPIClient(client=http, **options)
            with pytest.raises(ResourceConflict):
                await client.delete("old", dry_run=True, uid="old", resource_version="4")


async def test_scale_admission_targets_deployment_endpoint_with_scale_payload():
    from cloudcoil.models.kubernetes.autoscaling.v1 import Scale

    from examples.patterns.admission_existing import build_app

    app = build_app()
    api = AsyncMock(namespaced=True)
    api.get.return_value = ConfigMap(data={"maxReplicas": "2"})
    admission = app._admission(SimpleNamespace(async_client_for=AsyncMock(return_value=api)))
    old = Scale.model_validate(
        {"metadata": {"name": "app", "namespace": "tenant"}, "spec": {"replicas": 1}}
    )
    new = old.model_copy(deep=True)
    new.spec.replicas = 3
    result = await review(admission, "/validate-scale", new, old=old, operation="UPDATE")
    assert not result["allowed"] and "2 replicas" in result["status"]["message"]
    docs = admission.configurations(
        name="policy.example.com",
        service_name="policy",
        service_namespace="tenant",
        ca_bundle=b"-----BEGIN CERTIFICATE-----\npublic",
    )
    route = next(
        policy
        for doc in docs
        for policy in doc["webhooks"]
        if policy["clientConfig"]["service"]["path"] == "/validate-scale"
    )
    assert route["rules"] == [
        {
            "apiGroups": ["apps"],
            "apiVersions": ["v1"],
            "resources": ["deployments/scale"],
            "operations": ["UPDATE"],
            "scope": "Namespaced",
        }
    ]


def test_cache_configuration_honors_scope_and_unbounded_capacity():
    from cloudcoil.caching import Cache
    from cloudcoil.caching._types import ResourceCache

    cache = Cache(
        resources=[ConfigMap],
        namespaces=["tenant"],
        max_items_per_resource=0,
        per_resource={ConfigMap: ResourceCache(max_items=0, label_selector="app=demo")},
    )
    options = cache._create_options(ConfigMap, None)
    assert options.namespace == "tenant" and not options.all_namespaces
    assert options.max_items == 0 and options.label_selector == "app=demo"
    with pytest.raises(ValueError, match="outside"):
        cache._create_options(ConfigMap, "other")
    with pytest.raises(ValueError, match="one namespace"):
        Cache(namespaces=["one", "two"])


@pytest.mark.parametrize("selector", [{}, {"matchLabels": {"policy": "enabled"}}])
def test_explicit_admission_namespace_selector_is_preserved_and_copied(selector):
    from cloudcoil.admission import AdmissionWebhook
    from cloudcoil.application import Application, WebhookServer

    policies = AdmissionWebhook()

    @policies.validating(Pod, path="/pods", namespace_selector=selector)
    async def validate(request):
        pass

    app = Application(
        "policy",
        admission=policies,
        webhook=WebhookServer(tls_secret="policy-tls", ca_bundle=b"-----BEGIN CERTIFICATE-----"),
    )

    def registered():
        return next(
            doc for doc in app.manifests() if doc["kind"] == "ValidatingWebhookConfiguration"
        )["webhooks"][0]["namespaceSelector"]

    assert registered() == selector
    registered()["matchLabels"] = {"changed": "true"}
    assert registered() == selector
    selector["matchLabels"] = {"changed": "true"}
    assert registered() != selector


async def test_finalizer_example_does_not_provision_when_live_read_observes_deletion(monkeypatch):
    from examples.patterns import finalizers as pattern

    obj = pattern.ExternalRecord(
        metadata={"name": "record", "namespace": "tenant", "uid": "id"},
        spec=pattern.RecordSpec(value="value"),
    )
    deleting = obj.model_copy(deep=True)
    deleting.metadata.deletion_timestamp = "2026-09-07T00:00:00Z"
    deleting.metadata.finalizers = [pattern.FINALIZER]
    monkeypatch.setattr(pattern, "ensure_finalizer", AsyncMock(return_value=deleting))
    provider = SimpleNamespace(put=AsyncMock(), delete=AsyncMock())
    app = pattern.build_app(provider)
    result = await app.controllers[0].reconcile(Request(ResourceKey("record", "tenant"), obj))
    provider.put.assert_not_awaited()
    assert result.requeue_after == 0
