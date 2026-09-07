# Admission policies

Use admission to default or validate an incoming Kubernetes write. Policies can apply
to built-in resources and external CRDs without a controller or ownership.

## Standalone policies

```python
from cloudcoil.admission import AdmissionDenied, AdmissionRequest, AdmissionWebhook
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.application import Application
from cloudcoil.application import WebhookServer

policies = AdmissionWebhook()

@policies.validating(Deployment, path="/replica-limit")
async def replica_limit(request: AdmissionRequest[Deployment]) -> None:
    obj = request.resource
    if obj is not None and obj.spec is not None:
        replicas = obj.spec.replicas if obj.spec.replicas is not None else 1
        if replicas > 10:
            raise AdmissionDenied("At most ten replicas are allowed")

app = Application(
    "deployment-policy",
    admission=policies,
    webhook=WebhookServer(tls_secret="deployment-policy-tls"),
)

if __name__ == "__main__":
    app.main()
```

Follow [deployment and TLS setup](operators.md#generate-install-run) to install it.
Installing admission does not scan or repair stored objects; subsequent matching
requests are checked. The [complete Deployment policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_existing.py)
also covers `/scale`, immutable fields, DELETE and live policy reads.

## Policies on your resource

The same callbacks can live on a [custom resource](custom-resources.md). Inside the class:

```python
from typing import Self
from cloudcoil.admission import mutating, validating

@classmethod
@validating()
async def validate_message(cls, request: AdmissionRequest[Self]) -> None:
    if request.resource is not None and not request.resource.spec.message.strip():
        raise AdmissionDenied("Message must contain a non-whitespace character")
```

An `Application` discovers policies on its CRDs. For standalone ASGI hosting use
`AdmissionWebhook(config=config).register(Widget)`.

## Callback contract

Keep policies on the resource class with `@mutating()` and `@validating()` then register one or more models with `admission.register(Widget, Other)`.
Use `@classmethod` outermost; `@staticmethod` also works. Class methods receive
`AdmissionRequest[Self]`, so inherited policies remain typed to the concrete model
and DELETE does not require a current instance. Normal Python method shadowing
applies: overriding a method without the admission decorator removes that policy.
Registration is atomic and rejects duplicate paths.

The plural and scope come from `@custom_resource`. Default paths use the operation,
DNS group components, version, plural, and method name; for example
`/mutate/examples/cloudcoil/dev/v1alpha1/widgets/default-labels`. A decorator's
`path=` can override it. Explicit functions remain supported for existing resource
models or policies kept in another module:

```python
@policies.validating(Deployment, path="/additional-check")
async def additional_check(request: AdmissionRequest[Deployment]) -> None:
    if request.name.startswith("reserved-"):
        raise AdmissionDenied("Names beginning with reserved- are reserved")
```

Handlers are async. `AdmissionRequest[T]` provides the typed current and old
resources, operation, dry-run flag, user information, and the original object.
Mutation returns a modified resource; `None` produces no mutation. Validation
returns `None` to allow or raises `AdmissionDenied` to reject with an explanation.
An explicit denial is a normal admission decision, distinct from a server failure.
A valid AdmissionReview whose resource fails Pydantic validation is also denied
with code 422, including when the registration uses `failure_policy="Ignore"`.
Malformed envelopes and unexpected handler failures remain transport/server errors
subject to Kubernetes's configured failure policy.

The runtime speaks `admission.k8s.io/v1`, echoes the request UID, and generates the
base64 JSON Patch response expected by Kubernetes. It does not persist the
returned resource through a Kubernetes client: the API server applies the admission patch as
part of the pending request. Keep handlers fast and free of external side effects,
including on dry-run. The generated registration declares `sideEffects: None`.
[Kubernetes admission request/response protocol](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/#webhook-request-and-response).

Pydantic normalization alone is not a mutation; explicitly change and return the
resource when the stored value should change. The mutation patch contains the
handler's changes without removing fields unknown
to the typed model or adding unchanged Pydantic defaults. When defaulting a nested
field beneath an omitted parent, explicitly assign the parent object as well so
Pydantic records the field as set. List changes that cannot
safely preserve unmodeled data fail explicitly. Admission is pre-persistence: newly
created objects need not have the UID/resourceVersion required by controller write
helpers. Do not call `mutate` or return reconciliation `Result` objects here.

Registration defaults to CREATE and UPDATE. DELETE validation can be registered
explicitly and uses `old_resource` when `resource` is absent. Same-kind subresources
can be registered explicitly. CONNECT, differing-kind subresources such as scale,
conversion webhooks, and automatic discovery of equivalent API versions are outside
this increment; configurations use exact matching.

## Operations, subresources and namespace selection

| Operation | `resource` | `old_resource` |
| --- | --- | --- |
| CREATE | Proposed object | `None` |
| UPDATE | Proposed object | Previous object |
| DELETE | `None` | Object being deleted |

These snapshots come from the API server. An informer lookup is not a substitute
for `old_resource`. Reads bypass admission; callbacks must not write external state,
even during dry runs.

Subresources require explicit routes. A Scale payload has a different kind from its
Deployment endpoint:

```python
from cloudcoil.models.kubernetes.autoscaling.v1 import Scale

@policies.validating(
    Scale, target=Deployment, subresource="scale",
    path="/scale-limit", operations=("UPDATE",),
)
async def scale_limit(request: AdmissionRequest[Scale]) -> None:
    obj = request.resource
    if obj is not None and obj.spec is not None and (obj.spec.replicas or 0) > 10:
        raise AdmissionDenied("At most ten replicas are allowed")
```

Routes infer plural and scope from current generated models or custom-resource
metadata. Older models can supply `resource=` and `scope=`. Registrations match exact
API versions and subresources.

Namespaced routes follow matching controller namespaces, or the operator namespace
for admission-only applications. Set `namespace_selector={"matchLabels": {"policy": "enabled"}}`
on a route to select namespaces explicitly, or `{}` for all namespaces. Explicit
selectors are preserved. RBAC for live reads must cover the selected scope.

See [live clients and informer reads](reads.md#admission-caches) for per-replica caches.

## API client and request context

Use `await request.client(ResourceType)` for a live typed client of **any** kind,
just as in a reconciler. It defaults to the admission namespace and shares the
operator connection without changing the Config or another request's client:

```python
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

# Inside Widget:
@classmethod
@validating()
async def check_policy(cls, request: AdmissionRequest[Self]) -> None:
    if request.resource is None:
        return
    policies = await request.client(ConfigMap)
    policy = await policies.get("widget-policy")
    limit = int((policy.data or {}).get("maxLength", "200"))
    if len(request.resource.spec.message) > limit:
        raise AdmissionDenied(f"Namespace policy limits messages to {limit} characters")
```

`Application` supplies the Config and manages its lifetime. For standalone hosting,
use `AdmissionWebhook(config=config).register(Widget)` and keep that Config alive
until requests have drained. Pure handlers need no Config; requesting a client
without one raises a clear error. `request.config` is available for advanced use.
The optional second `AsyncAPIClient[Self]` handler argument remains supported, but
`request.client(...)` works for both primary and unrelated resources without extra
handler signatures.

Client discovery and live reads happen asynchronously within the admission
timeout. `request` also carries `old_resource`, `dry_run`, `user_info`, `options`,
and raw current/previous objects. Read-only lookups work during dry runs; keep
callbacks free of external writes. A lookup and subsequent API-server persistence
are not an atomic transaction. Declare additional read access with `RBACRule`.

## Standalone ASGI hosting

`AdmissionWebhook` is a dependency-free ASGI application. Serve it with your existing
ASGI server and TLS setup; installing Cloudcoil does not install or start an HTTP
server. For an application named `admission` in `my_webhooks.py`:

```bash
uv run --extra kubernetes --with uvicorn uvicorn my_webhooks:admission \
  --host 0.0.0.0 --port 9443 \
  --ssl-certfile /certs/tls.crt --ssl-keyfile /certs/tls.key
```

Generate registration manifests that match the configured handler paths:

```python
from pathlib import Path

configurations = admission.configurations(
    name="widgets.examples.cloudcoil.dev",
    service_name="widget-webhook",
    service_namespace="operators",
    ca_bundle=Path("/certs/ca.crt").read_bytes(),
)
```

`ca_bundle` is PEM bytes, encoded for Kubernetes by the generator. A Service should
route its HTTPS port to the ASGI server's TLS port. The certificate must cover
`widget-webhook.operators.svc`. Supply certificates through your certificate
manager or deployment process; this library does not provision certificates or
rotate them. Kubernetes verifies the serving certificate against the configured
CA. [Webhook service references and TLS](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/#contacting-the-webhook).

Bring up the server and its Service before applying webhook configurations. Generated
configurations fail closed by default, so registering an unavailable webhook blocks
matching writes. During removal, delete the webhook registrations before the
serving workload. Restrict access to the admission listener using your network/TLS
configuration, and keep registrations scoped to the resources and operations needed.

Serve admission on every webhook replica. It should remain available independently
of which reconciliation manager holds the Lease. A separate webhook workload is a
straightforward arrangement: controller standby readiness intentionally remains
false, so its readiness should not decide whether a webhook replica receives traffic.
The ASGI application's lifecycle and request limits are independent of `Manager`.
Requests are bounded by `max_body_bytes` (4 MiB by default) and the registered
`timeout_seconds` (5 by default, 1–30 allowed). Disconnects and cancellation stop and
join the handler. `GET /healthz` can be used to probe the serving application.
