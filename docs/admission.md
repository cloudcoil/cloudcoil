# Admission policies

Use admission to default or validate an incoming Kubernetes write. Policies can apply
to built-in resources and external CRDs without a controller or ownership.

## Standalone policies

```python
from cloudcoil.admission import AdmissionDenied, AdmissionRequest
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.application import Application, WebhookServer

app = Application(
    "deployment-policy",
    webhook=WebhookServer(tls_secret="deployment-policy-tls"),
)

@app.validate(Deployment, path="/replica-limit")
async def replica_limit(request: AdmissionRequest[Deployment]) -> None:
    obj = request.resource
    if obj is not None and obj.spec is not None:
        replicas = obj.spec.replicas if obj.spec.replicas is not None else 1
        if replicas > 10:
            raise AdmissionDenied("At most ten replicas are allowed")

if __name__ == "__main__":
    app.main()
```

Follow [deployment and TLS setup](operators.md#generate-install-run) to install it.
Installing admission does not scan or repair stored objects; subsequent matching
requests are checked. The [complete Deployment policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_existing.py)
also covers `/scale`, immutable fields, DELETE and live policy reads.

## Scoped policies

A controller group supplies its primary resource type. Using the Widget definition
from the [custom resource guide](custom-resources.md):

```python
from cloudcoil.controller import Context
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

widgets = app.controller(Widget, owns=(ConfigMap,))

@widgets.reconcile()
async def reconcile(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(ConfigMap(data={"message": widget.spec.message}))

@widgets.validate()
async def validate_message(request: AdmissionRequest[Widget]) -> None:
    if request.resource is not None and not request.resource.spec.message.strip():
        raise AdmissionDenied("Message must contain text")
```

Decorated handlers take exactly one `AdmissionRequest`. Default paths are stable
names derived from the handler, target and subresource. Set `path=` for a specific route;
duplicate paths across groups fail before serving. Registration performs no network I/O.

## Callback contract

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
can be registered explicitly. CONNECT, conversion webhooks, and automatic discovery of equivalent API versions
are outside this API; configurations use exact matching. Differing-kind subresources
such as scale declare their parent with target=.

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

@app.validate(
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

## Mutation and client reads

Mutation returns the changed payload; validation returns `None` or raises
`AdmissionDenied`. For example, add a label only when it is absent:

```python
@app.mutate(Deployment)
async def default_team(request: AdmissionRequest[Deployment]) -> Deployment | None:
    obj = request.resource
    if obj is not None and obj.metadata is not None:
        obj.metadata.labels = {"team": "unassigned", **(obj.metadata.labels or {})}
    return obj
```

Use `await request.client(ResourceType)` for a live client of any kind. It shares
the application's Config and defaults to the admission namespace, without changing
the shared configuration. Declare those reads in Application `rules`, for example:

```python
from cloudcoil.application import RBACRule
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

policy_rule = RBACRule(ConfigMap, ("get",), resource_names=("deployment-policy",))
```

Pass `rules=(policy_rule,)` when constructing the Application. Inside a handler,
`client = await request.client(ConfigMap)` followed by
`policy = await client.get("deployment-policy")` performs the live lookup.
Client discovery and reads are subject to the admission timeout. A lookup and the
pending write are not an atomic cross-resource transaction.

`request.cached(Kind)` reads a separately configured per-replica cache; see
[admission caches](reads.md#admission-caches). It does not use a leader's controller
informers. The [existing Deployment policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_existing.py)
combines defaulting, immutable fields, DELETE, `/scale` and a live namespace policy.

## Resource-local policies and standalone hosting

Existing resource-local class/static methods using @validating()/@mutating() remain
available. Application discovers them on installed CRD models; use @classmethod
outermost and AdmissionRequest[Self] for inherited policies. The optional second
injected client belongs to that low-level interface only. For standalone ASGI hosting,
AdmissionWebhook(config=config).register(Widget) remains supported.

`AdmissionWebhook` is an ASGI application with no required server dependency. Serve it with your existing
ASGI server and TLS setup; installing Cloudcoil does not install or start an HTTP
server. For an ASGI object named `admission` in `my_webhooks.py`:

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
