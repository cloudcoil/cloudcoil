"""Offline access generation must preserve Kubernetes namespace boundaries."""

import base64
from dataclasses import FrozenInstanceError
from typing import Literal, Self

import pytest
from pydantic import BaseModel, Field

from cloudcoil.admission import AdmissionRequest, AdmissionWebhook, validating
from cloudcoil.controller import Controller, LeaderElection, Request
from cloudcoil.crd import CRD, custom_resource
from cloudcoil.operator._manifests import RBACRule, build_manifests
from cloudcoil.operator._server import WebhookServer
from cloudcoil.resources import Resource


class WidgetStatus(BaseModel):
    ready: bool = False


@custom_resource(plural="widgets")
class Widget(Resource):
    api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
    kind: Literal["Widget"] = "Widget"
    status: WidgetStatus | None = None

    @classmethod
    @validating()
    async def validate_admission(cls, request: AdmissionRequest[Self]) -> None:
        return None


@custom_resource(plural="fleets", scope="Cluster")
class Fleet(Resource):
    api_version: Literal["example.com/v1"] = Field(default="example.com/v1", alias="apiVersion")
    kind: Literal["Fleet"] = "Fleet"


class ConfigMap(Resource):
    api_version: Literal["v1"] = Field(default="v1", alias="apiVersion")
    kind: Literal["ConfigMap"] = "ConfigMap"


async def reconcile(request: Request[Widget]) -> None:
    return None


def manifests(*controllers, **kwargs):
    return build_manifests(
        name="widgets",
        namespace="operators",
        controllers=controllers,
        crds=(CRD(Widget),),
        **kwargs,
    )


def policy(documents, kind, namespace=None):
    return [
        rule
        for document in documents
        if document["kind"] == kind and document["metadata"].get("namespace") == namespace
        for rule in document["rules"]
    ]


def configmap_rule(verbs=("create", "patch"), **kwargs):
    return RBACRule(ConfigMap, verbs, plural="configmaps", scope="Namespaced", **kwargs)


def test_primary_and_secondary_permissions_follow_distinct_namespaces():
    controller = Controller(Widget, reconcile, namespace="tenant").owns(ConfigMap)
    documents = manifests(controller, rules=(configmap_rule(namespace="tenant"),))
    assert not policy(documents, "ClusterRole")
    rules = policy(documents, "Role", "tenant")
    assert {tuple(rule["resources"]): set(rule["verbs"]) for rule in rules} == {
        ("widgets",): {"get", "list", "watch", "patch"},
        ("widgets/status",): {"patch"},
        ("configmaps",): {"get", "list", "watch", "create", "patch"},
    }
    assert {rule["apiGroups"][0] for rule in rules} == {"", "example.com"}
    binding = next(doc for doc in documents if doc["kind"] == "RoleBinding")
    assert binding["metadata"]["namespace"] == "tenant"
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "widgets", "namespace": "operators"}
    ]
    assert not any("customresourcedefinitions" in rule["resources"] for rule in rules)


def test_unknown_builtin_requires_explicit_offline_metadata():
    with pytest.raises(ValueError, match="Offline RBAC needs plural and scope for ConfigMap"):
        manifests(Controller(Widget, reconcile).owns(ConfigMap))
    with pytest.raises(ValueError, match="Provide both plural and scope"):
        manifests(rules=(RBACRule(ConfigMap, ("get",), plural="configmaps"),))


def test_cluster_owner_watches_namespaced_children_across_namespaces():
    controller = Controller(Fleet, reconcile).owns(Widget)
    documents = manifests(controller)
    rules = policy(documents, "ClusterRole")
    assert {tuple(rule["resources"]): set(rule["verbs"]) for rule in rules} == {
        ("fleets",): {"get", "list", "watch", "patch"},
        ("widgets",): {"get", "list", "watch"},
    }
    assert not policy(documents, "Role", "operators")


def test_all_namespaces_watch_does_not_expand_explicit_write_permission():
    documents = manifests(
        Controller(Widget, reconcile, all_namespaces=True).owns(ConfigMap),
        rules=(configmap_rule(),),
    )
    cluster = policy(documents, "ClusterRole")
    assert next(rule for rule in cluster if rule["resources"] == ["configmaps"])["verbs"] == [
        "get",
        "list",
        "watch",
    ]
    assert policy(documents, "Role", "operators") == [
        {"apiGroups": [""], "resources": ["configmaps"], "verbs": ["create", "patch"]}
    ]
    explicit = manifests(rules=(configmap_rule(all_namespaces=True),))
    assert policy(explicit, "ClusterRole")[0]["verbs"] == ["create", "patch"]


def test_explicit_status_disable_does_not_grant_status_patch():
    documents = build_manifests(
        name="widgets",
        namespace="operators",
        controllers=(Controller(Widget, reconcile),),
        crds=(CRD(Widget, status=False),),
    )
    assert all(
        rule["resources"] != ["widgets/status"] for rule in policy(documents, "Role", "operators")
    )


def test_leader_permissions_use_dedicated_namespace_and_named_lease():
    documents = manifests(
        Controller(Widget, reconcile),
        leader_election=LeaderElection("widgets", namespace="elections"),
    )
    assert policy(documents, "Role", "elections") == [
        {"apiGroups": ["coordination.k8s.io"], "resources": ["leases"], "verbs": ["create"]},
        {
            "apiGroups": ["coordination.k8s.io"],
            "resources": ["leases"],
            "verbs": ["get", "update"],
            "resourceNames": ["widgets"],
        },
    ]


def test_deployment_wires_service_account_https_and_existing_secret_only():
    ca_bundle = b"-----BEGIN CERTIFICATE-----\nPUBLIC\n-----END CERTIFICATE-----"
    documents = manifests(
        Controller(Widget, reconcile),
        admission=AdmissionWebhook().register(Widget),
        webhook=WebhookServer(ca_bundle=ca_bundle, tls_secret="widgets-tls"),
        image="example.com/widgets:v1",
        command=("python", "-m", "widgets"),
        replicas=2,
    )
    assert documents[-1]["kind"] == "ValidatingWebhookConfiguration"
    configuration = documents[-1]["webhooks"][0]["clientConfig"]
    assert configuration["caBundle"] == base64.b64encode(ca_bundle).decode()
    assert configuration["service"] == {
        "name": "widgets",
        "namespace": "operators",
        "path": "/validate/example/com/v1/widgets/validate_admission",
        "port": 443,
    }
    service = next(doc for doc in documents if doc["kind"] == "Service")
    deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
    pod = deployment["spec"]["template"]
    assert service["spec"]["selector"] == pod["metadata"]["labels"]
    assert pod["spec"]["serviceAccountName"] == "widgets"
    container = pod["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "widgets"]
    assert container["args"] == ["run"]
    assert container["readinessProbe"]["httpGet"] == {
        "path": "/readyz",
        "port": "webhook",
        "scheme": "HTTPS",
    }
    secret = pod["spec"]["volumes"][0]["secret"]
    assert secret["secretName"] == "widgets-tls"
    assert not any(doc["kind"] == "Secret" for doc in documents)
    assert "PRIVATE KEY" not in repr(documents)


def test_generation_is_deterministic_and_return_values_are_independent():
    controller = Controller(Widget, reconcile).owns(ConfigMap)
    first = manifests(controller, rules=(configmap_rule(),))
    second = manifests(controller, rules=(configmap_rule(),))
    assert first == second
    first[0]["metadata"]["name"] = "changed"
    assert second[0]["metadata"]["name"] == "widgets.example.com"
    second[-1]["metadata"]["name"] = "changed"
    assert first[-1]["metadata"]["name"] != "changed"


def test_conflicting_plural_or_scope_fails_before_granting_access():
    with pytest.raises(ValueError, match="Conflicting plural/scope"):
        manifests(rules=(RBACRule(Widget, ("get",), plural="wrong", scope="Namespaced"),))
    with pytest.raises(ValueError, match="Conflicting plural/scope"):
        manifests(
            rules=(
                configmap_rule(),
                RBACRule(ConfigMap, ("get",), plural="configmaps", scope="Cluster"),
            )
        )


def test_explicit_named_subresource_access_is_not_expanded():
    documents = manifests(
        rules=(
            RBACRule(
                Widget,
                ("get", "patch"),
                namespace="tenant",
                subresources=("scale",),
                resource_names=("one",),
            ),
        )
    )
    assert policy(documents, "Role", "tenant") == [
        {
            "apiGroups": ["example.com"],
            "resources": ["widgets/scale"],
            "verbs": ["get", "patch"],
            "resourceNames": ["one"],
        }
    ]


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"namespace": "tenant", "all_namespaces": True}, "mutually exclusive"),
        ({"verbs": ()}, "must not be empty"),
        ({"verbs": "get"}, "nonempty strings"),
        ({"verbs": ("create",), "resource_names": ("one",)}, "cannot restrict"),
        ({"plural": "Things"}, "DNS label"),
        ({"subresources": ("status/extra",)}, "DNS label"),
    ],
)
def test_invalid_rbac_declarations_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        RBACRule(Widget, **{"verbs": ("get",), **kwargs})


def test_rule_captures_immutable_caller_sequences():
    verbs = ["patch", "get", "get"]
    rule = RBACRule(Widget, verbs)
    verbs.append("delete")
    assert rule.verbs == ("get", "patch")
    with pytest.raises(FrozenInstanceError):
        rule.namespace = "different"


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"replicas": 0}, "positive integer"),
        ({"image": ""}, "nonempty"),
        ({"command": ("python",)}, "requires image"),
        ({"image": "image", "command": "python"}, "sequence"),
        ({"webhook": WebhookServer()}, "requires an AdmissionWebhook"),
        (
            {
                "image": "image",
                "webhook": WebhookServer(certfile="/tls.crt", keyfile="/tls.key"),
                "admission": AdmissionWebhook(),
            },
            "same non-root directory",
        ),
    ],
)
def test_invalid_installation_options_are_rejected(kwargs, match):
    with pytest.raises(ValueError, match=match):
        manifests(**kwargs)


def test_two_crd_versions_cannot_silently_overwrite_one_another():
    class WidgetV2(Widget):
        api_version: Literal["example.com/v2"] = Field(default="example.com/v2", alias="apiVersion")

    with pytest.raises(ValueError, match="distinct metadata.name"):
        build_manifests(
            name="widgets",
            namespace="operators",
            controllers=(),
            crds=(CRD(Widget), CRD(WidgetV2, plural="widgets")),
        )
