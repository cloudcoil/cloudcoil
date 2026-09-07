"""Admission-only operator for existing Deployments. No Deployment ownership or CRD install."""

from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.autoscaling.v1 import Scale
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.admission import AdmissionDenied, AdmissionRequest, AdmissionWebhook
from cloudcoil.operator import Operator, RBACRule, WebhookServer


def build_operator() -> Operator:
    policies = AdmissionWebhook()

    @policies.mutating(Deployment, path="/default-deployment")
    async def default_team(request: AdmissionRequest[Deployment]) -> Deployment | None:
        obj = request.resource
        if obj is not None and obj.metadata is not None:
            obj.metadata.labels = {"team": "unassigned", **(obj.metadata.labels or {})}
        return obj

    @policies.validating(Deployment, path="/validate-deployment")
    async def cap_replicas(request: AdmissionRequest[Deployment]) -> None:
        obj = request.resource
        if obj is None or obj.spec is None:
            return
        client = await request.client(ConfigMap)
        policy = await client.get("deployment-policy")
        limit = int((policy.data or {}).get("maxReplicas", "10"))
        if (obj.spec.replicas if obj.spec.replicas is not None else 1) > limit:
            raise AdmissionDenied(f"Namespace policy allows at most {limit} replicas")
        # request.old_resource is the admission UPDATE snapshot, not a cache lookup.
        old = request.old_resource
        previous_team = (old.metadata.labels or {}).get("team") if old and old.metadata else None
        new_team = (obj.metadata.labels or {}).get("team") if obj.metadata else None
        if previous_team is not None and previous_team != new_team:
            raise AdmissionDenied("An existing Deployment's team label cannot change")

    @policies.validating(
        Scale,
        target=Deployment,
        subresource="scale",
        path="/validate-scale",
        operations=("UPDATE",),
    )
    async def cap_scale(request: AdmissionRequest[Scale]) -> None:
        obj = request.resource
        if obj is None or obj.spec is None:
            return
        client = await request.client(ConfigMap)
        policy = await client.get("deployment-policy")
        limit = int((policy.data or {}).get("maxReplicas", "10"))
        if (obj.spec.replicas if obj.spec.replicas is not None else 0) > limit:
            raise AdmissionDenied(f"Namespace policy allows at most {limit} replicas")

    @policies.validating(Deployment, path="/protect-delete", operations=("DELETE",))
    async def protect_delete(request: AdmissionRequest[Deployment]) -> None:
        old = request.old_resource  # DELETE has no request.resource.
        if (
            old
            and old.metadata
            and (old.metadata.annotations or {}).get("patterns.cloudcoil.dev/protect") == "true"
        ):
            raise AdmissionDenied("Remove the protection annotation before deleting")

    return Operator(
        "deployment-policy",
        admission=policies,
        rules=(RBACRule(ConfigMap, ("get",), resource_names=("deployment-policy",)),),
        webhook=WebhookServer(tls_secret="deployment-policy-tls"),
    )


if __name__ == "__main__":
    build_operator().main()
