"""Offline installation manifests and explicit Kubernetes access declarations."""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from cloudcoil.crd import CRD, _resource_options
from cloudcoil.resources import Resource

if TYPE_CHECKING:
    from cloudcoil.admission import AdmissionWebhook
    from cloudcoil.controller import Controller, LeaderElection
    from cloudcoil.operator._server import WebhookServer


Scope = Literal["Namespaced", "Cluster"]
_READ = ("get", "list", "watch")


def _label(value: str, description: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", value
    ):
        raise ValueError(f"{description} must be a Kubernetes DNS label")
    return value


@dataclass(frozen=True)
class RBACRule:
    """Additional access, with offline API metadata for generated resource classes.

    Custom resources use their CRD declaration; generated models carry API metadata.
    Older models require ``plural`` and ``scope`` once. Namespaced access defaults to the operator's namespace;
    use ``all_namespaces=True`` explicitly for a cluster-wide grant. ``subresources``
    selects those endpoints instead of the main resource. Reconcile and admission
    function bodies cannot be inspected to infer their additional access needs.
    """

    resource: type[Resource]
    verbs: tuple[str, ...]
    plural: str | None = None
    scope: Scope | None = None
    namespace: str | None = None
    all_namespaces: bool = False
    subresources: tuple[str, ...] = ()
    resource_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.resource, type) or not issubclass(self.resource, Resource):
            raise TypeError("RBACRule.resource must be a Resource class")
        for field in ("verbs", "subresources", "resource_names"):
            values = getattr(self, field)
            if isinstance(values, str) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ValueError(f"RBACRule.{field} must contain nonempty strings")
            object.__setattr__(self, field, tuple(sorted(set(values))))
        if not self.verbs:
            raise ValueError("RBACRule.verbs must not be empty")
        if self.plural is not None:
            _label(self.plural, "Resource plural")
        if self.scope not in (None, "Namespaced", "Cluster"):
            raise ValueError("RBACRule.scope must be Namespaced or Cluster")
        if self.namespace is not None:
            _label(self.namespace, "RBAC namespace")
        if self.namespace is not None and self.all_namespaces:
            raise ValueError("RBACRule.namespace and all_namespaces are mutually exclusive")
        if self.scope == "Cluster" and self.namespace is not None:
            raise ValueError("Cluster resources cannot have a namespaced RBACRule")
        if self.resource_names and set(self.verbs) & {"create", "deletecollection"}:
            raise ValueError("Kubernetes cannot restrict create/deletecollection by resource_names")
        for subresource in self.subresources:
            _label(subresource, "Subresource")


@dataclass(frozen=True)
class _Identity:
    group: str
    plural: str
    scope: Scope
    status: bool = False


def build_manifests(
    *,
    name: str,
    namespace: str,
    controllers: Sequence[Controller[Any]],
    crds: Sequence[CRD],
    admission: AdmissionWebhook | None = None,
    rules: Sequence[RBACRule] = (),
    leader_election: LeaderElection | None = None,
    webhook: WebhookServer | None = None,
    image: str | None = None,
    command: Sequence[str] | None = None,
    replicas: int = 1,
) -> list[dict[str, Any]]:
    """Build CRDs, runtime RBAC, and optional deployment/webhook installation.

    No clients are created and no discovery runs. Installation privileges are
    deliberately absent from the operator ServiceAccount: installation is done
    with the caller's credentials before starting the runtime.
    """
    _label(name, "Operator name")
    _label(namespace, "Operator namespace")
    crd_documents = {crd.resource: crd.manifest() for crd in crds}
    crd_names = [crd_documents[crd.resource]["metadata"]["name"] for crd in crds]
    if len(set(crd_names)) != len(crd_names):
        raise ValueError(
            "CRDs must have distinct metadata.name values; multi-version CRDs are not supported"
        )
    if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1:
        raise ValueError("replicas must be a positive integer")
    if image is not None and (not isinstance(image, str) or not image.strip()):
        raise ValueError("image must be nonempty")
    if command is not None and (
        isinstance(command, str)
        or not command
        or any(not isinstance(arg, str) or not arg for arg in command)
    ):
        raise ValueError("command must be a nonempty sequence of arguments")
    if image is None and command is not None:
        raise ValueError("command requires image")

    identities: dict[tuple[str, str], _Identity] = {}

    def register(resource: type[Resource], identity: _Identity) -> None:
        gvk = resource.gvk()
        key = (gvk.group, gvk.kind)
        previous = identities.get(key)
        if previous is not None and (previous.plural, previous.scope) != (
            identity.plural,
            identity.scope,
        ):
            raise ValueError(f"Conflicting plural/scope declarations for {gvk.group}/{gvk.kind}")
        identities[key] = _Identity(
            identity.group,
            identity.plural,
            identity.scope,
            identity.status or bool(previous and previous.status),
        )

    for crd in crds:
        spec = crd_documents[crd.resource]["spec"]
        register(
            crd.resource,
            _Identity(
                spec["group"],
                crd.plural,
                crd.scope,
                any("status" in version.get("subresources", {}) for version in spec["versions"]),
            ),
        )
    # A decorated watch dependency may be externally installed, without being one
    # of the CRDs this operator owns and installs.
    for resource in [
        *(controller.resource for controller in controllers),
        *(watch.resource for controller in controllers for watch in controller._watches),
        *(rule.resource for rule in rules),
    ]:
        api = resource.__dict__.get("__cloudcoil_api__")
        if api is not None:
            register(resource, _Identity(resource.gvk().group, **api))
        options = _resource_options(resource)
        if options is not None and (resource.gvk().group, resource.gvk().kind) not in identities:
            register(
                resource,
                _Identity(
                    resource.gvk().group,
                    options.plural,
                    options.scope,
                    options.status is True
                    or (options.status is None and "status" in resource.model_fields),
                ),
            )
    for rule in rules:
        if rule.plural is not None and rule.scope is not None:
            register(rule.resource, _Identity(rule.resource.gvk().group, rule.plural, rule.scope))
        elif rule.plural is not None or rule.scope is not None:
            key = (rule.resource.gvk().group, rule.resource.gvk().kind)
            previous = identities.get(key)
            if previous is None:
                raise ValueError(f"Provide both plural and scope for {rule.resource.__name__}")
            register(
                rule.resource,
                _Identity(
                    previous.group, rule.plural or previous.plural, rule.scope or previous.scope
                ),
            )

    def identity(resource: type[Resource]) -> _Identity:
        gvk = resource.gvk()
        result = identities.get((gvk.group, gvk.kind))
        if result is None:
            raise ValueError(
                f"Offline RBAC needs plural and scope for {resource.__name__}; add RBACRule({resource.__name__}, verbs=(...), plural=..., scope=...)"
            )
        return result

    # Namespace None denotes a ClusterRole; each namespaced bucket gets a Role.
    grants: dict[str | None, dict[tuple[str, str, tuple[str, ...]], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    def grant(
        api: _Identity,
        verbs: Sequence[str],
        target_namespace: str | None,
        subresources: Sequence[str] = (),
        names: tuple[str, ...] = (),
    ) -> None:
        target = None if api.scope == "Cluster" else target_namespace
        for endpoint in (
            tuple(f"{api.plural}/{sub}" for sub in subresources) if subresources else (api.plural,)
        ):
            grants[target][(api.group, endpoint, names)].update(verbs)

    for controller in controllers:
        primary = identity(controller.resource)
        watch_options = controller._options
        watched_namespace = (
            None if watch_options.all_namespaces else (watch_options.namespace or namespace)
        )
        if watched_namespace is not None:
            _label(watched_namespace, "Controller namespace")
        grant(primary, (*_READ, "patch"), watched_namespace)
        if primary.status:
            grant(primary, ("patch",), watched_namespace, ("status",))
        for watch in controller._watches:
            grant(
                identity(watch.resource),
                (*_READ, "create", "patch") if watch.mapper is None else _READ,
                None if primary.scope == "Cluster" else watched_namespace,
            )
    for rule in rules:
        api = identity(rule.resource)
        if api.scope == "Cluster" and rule.namespace is not None:
            raise ValueError("Cluster resources cannot have a namespaced RBACRule")
        grant(
            api,
            rule.verbs,
            None if rule.all_namespaces else rule.namespace or namespace,
            rule.subresources,
            rule.resource_names,
        )
    if leader_election is not None:
        lease_namespace = leader_election.namespace or namespace
        _label(lease_namespace, "Leader election namespace")
        lease = _Identity("coordination.k8s.io", "leases", "Namespaced")
        grant(lease, ("create",), lease_namespace)
        grant(lease, ("get", "update"), lease_namespace, names=(leader_election.name,))

    manifests = sorted(crd_documents.values(), key=lambda document: document["metadata"]["name"])
    manifests.append(
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": name, "namespace": namespace},
        }
    )
    for target in sorted(grants, key=lambda target: (target is not None, target or "")):
        # Include the installation namespace in cluster object names, avoiding
        # collisions when the same operator is installed into several namespaces.
        role_name = f"{name}.{namespace}"
        role_kind = "ClusterRole" if target is None else "Role"
        metadata = {"name": role_name, **({"namespace": target} if target is not None else {})}
        policy_rules = []
        for (group, endpoint, names), verbs in sorted(grants[target].items()):
            policy_rules.append(
                {
                    "apiGroups": [group],
                    "resources": [endpoint],
                    "verbs": sorted(verbs),
                    **({"resourceNames": list(names)} if names else {}),
                }
            )
        manifests.extend(
            [
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": role_kind,
                    "metadata": metadata.copy(),
                    "rules": policy_rules,
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": f"{role_kind}Binding",
                    "metadata": metadata.copy(),
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": role_kind,
                        "name": role_name,
                    },
                    "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": namespace}],
                },
            ]
        )

    labels = {"app.kubernetes.io/name": name}
    if webhook is not None:
        _label(webhook.tls_secret, "TLS Secret name")
        if admission is None:
            raise ValueError("WebhookServer requires an AdmissionWebhook")
        manifests.append(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name, "namespace": namespace},
                "spec": {
                    "selector": labels.copy(),
                    "ports": [
                        {"name": "webhook", "port": webhook.service_port, "targetPort": "webhook"}
                    ],
                },
            }
        )
    if image is not None:
        container: dict[str, Any] = {
            "name": "operator",
            "image": image,
            "args": ["run"],
            "env": [
                {
                    "name": "CLOUDCOIL_NAMESPACE",
                    "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}},
                }
            ],
        }
        if command is not None:
            container["command"] = list(command)
        pod_spec: dict[str, Any] = {"serviceAccountName": name, "containers": [container]}
        if webhook is not None:
            cert = PurePosixPath(webhook.certfile)
            key_path = PurePosixPath(webhook.keyfile)
            if (
                not cert.is_absolute()
                or not key_path.is_absolute()
                or cert.parent != key_path.parent
                or cert == key_path
                or cert.parent == PurePosixPath("/")
                or ".." in cert.parts
                or ".." in key_path.parts
            ):
                raise ValueError(
                    "Deployment TLS files must be distinct absolute paths in the same non-root directory"
                )
            container["ports"] = [{"name": "webhook", "containerPort": webhook.port}]
            container["readinessProbe"] = {
                "httpGet": {"path": "/readyz", "port": "webhook", "scheme": "HTTPS"}
            }
            container["volumeMounts"] = [
                {"name": "webhook-tls", "mountPath": str(cert.parent), "readOnly": True}
            ]
            pod_spec["volumes"] = [
                {
                    "name": "webhook-tls",
                    "secret": {
                        "secretName": webhook.tls_secret,
                        "items": [
                            {"key": "tls.crt", "path": cert.name},
                            {"key": "tls.key", "path": key_path.name},
                        ],
                    },
                }
            ]
        manifests.append(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": namespace},
                "spec": {
                    "replicas": replicas,
                    "selector": {"matchLabels": labels.copy()},
                    "template": {"metadata": {"labels": labels.copy()}, "spec": pod_spec},
                },
            }
        )
    if webhook is not None and admission is not None:
        manifests.extend(
            admission.configurations(
                name=f"{name}.{namespace}.cloudcoil.io",
                service_name=name,
                service_namespace=namespace,
                ca_bundle=webhook.ca_bundle,
                service_port=webhook.service_port,
            )
        )
    return manifests
