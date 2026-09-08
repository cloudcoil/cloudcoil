"""Opt-in eventually-consistent namespace policy, cached on every admission replica."""

from cloudcoil.models.kubernetes.core.v1 import Namespace, Pod

from cloudcoil.admission import AdmissionDenied, AdmissionRequest
from cloudcoil.application import Application, RBACRule, WebhookServer
from cloudcoil.caching import Cache


def build_app() -> Application:
    app = Application(
        "namespace-policy",
        cache=Cache(
            resources=[Namespace], mode="strict", wait_for_sync=True, max_items_per_resource=0
        ),
        rules=(RBACRule(Namespace, ("get", "list", "watch")),),
        webhook=WebhookServer(tls_secret="namespace-policy-tls"),
    )

    @app.validate(
        Pod,
        path="/namespace-policy",
        namespace_selector={"matchLabels": {"patterns.cloudcoil.dev/enforce": "true"}},
    )
    async def namespace_policy(request: AdmissionRequest[Pod]) -> None:
        namespace = request.cached(Namespace).get(request.namespace)
        if namespace is None:
            # Cache absence is not proof of deletion: verify with a live read.
            client = await request.client(Namespace)
            namespace = await client.get(request.namespace)
        labels = namespace.metadata.labels or {} if namespace.metadata else {}
        if labels.get("patterns.cloudcoil.dev/allow-pods") != "true":
            raise AdmissionDenied(
                "Namespace must opt in with patterns.cloudcoil.dev/allow-pods=true"
            )

    return app


if __name__ == "__main__":
    build_app().main()
