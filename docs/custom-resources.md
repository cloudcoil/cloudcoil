# Custom resources and admission

Define a resource once, then use its type to generate a CRD, run a controller, and
register admission webhooks. The runtime uses the same Pydantic model throughout.
The [controller guide](controllers.md) covers reconciliation, returned-resource
patches, status, retries, leadership, and health endpoints.

## Define and generate

```python
from typing import Annotated, Literal, Self

from pydantic import Field

from cloudcoil.admission import (
    AdmissionDenied, AdmissionRequest, AdmissionWebhook, mutating, validating,
)
from cloudcoil.crd import CRD, PrinterColumn, custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource


class WidgetSpec(BaseModel):
    message: str = Field(min_length=1, max_length=200)


class WidgetStatus(BaseModel):
    phase: Annotated[Literal["Ready"], PrinterColumn(name="Phase")] = "Ready"
    observed_generation: int | None = Field(default=None, alias="observedGeneration")


@custom_resource(plural="widgets", short_names=("wd",))
class Widget(Resource):
    api_version: Literal["examples.cloudcoil.dev/v1alpha1"] = Field(
        default="examples.cloudcoil.dev/v1alpha1", alias="apiVersion"
    )
    kind: Literal["Widget"] = "Widget"
    spec: WidgetSpec
    status: WidgetStatus | None = None


    @classmethod
    @mutating()
    async def default_labels(cls, request: AdmissionRequest[Self]) -> Self | None:
        obj = request.resource
        if obj is not None and obj.metadata is not None:
            obj.metadata.labels = {
                "app.kubernetes.io/managed-by": "cloudcoil",
                **(obj.metadata.labels or {}),
            }
        return obj

    @classmethod
    @validating()
    async def validate_message(cls, request: AdmissionRequest[Self]) -> None:
        if request.resource is not None and not request.resource.spec.message.strip():
            raise AdmissionDenied("spec.message must contain a non-whitespace character")


crd = CRD(Widget)
admission = AdmissionWebhook().register(Widget)
print(crd.to_yaml())
manifest = crd.manifest()  # Ordinary dictionary; no cluster access.
```

Group, version, and kind come from the model. Explicit plural names avoid guessing
English plurals. Keep the `apiVersion` alias when overriding `api_version`, and use
aliases such as `observedGeneration` for fields whose Kubernetes names differ from
Python names. Generation checks that validation and serialization agree on names.
`PrinterColumn` on an `Annotated` field infers its serialized JSONPath and scalar
type, including nested models and aliases; a `date-time` field becomes a `date`
column. Inferred columns are followed by the default Age column. Explicit
`CRD(Widget, columns=[...])` replaces them; `columns=[]` disables all columns.
Collection-item columns need an explicit `json_path`.

The class decorator preserves the Pydantic model and stores metadata only. It does
not create a controller, install the CRD, or register a global webhook. Each concrete
subclass declares its own plural. Existing models can still use
`CRD(Widget, plural="widgets", ...)`; constructor options override class metadata.

The initial generator emits one served/storage version in
`apiextensions.k8s.io/v1`. It enables the status subresource when the model has a
status field, with an explicit override available. Keep status optional with a
`None` default: the API server removes status during normal creates. A required
status field would prevent initial creation. Scope and CRD installation permissions
are independent of a controller's watch namespace.

`CRD` generation does not install anything. Review the emitted manifest and apply it
with your normal deployment workflow. Updating an existing CRD is an API change:
consider stored objects and compatibility before narrowing its schema. Multiple
served versions, conversion webhooks, and storage-version migration are later
milestones.

## Schema behavior

The generator translates Pydantic validation schemas into Kubernetes structural
OpenAPI schemas. Nested models are inlined, nullable fields use `nullable`, constants
become enums, and supported numeric/string/list bounds remain validations. Typed
maps and lists retain their item schemas. Explicit arbitrary JSON fields preserve
unknown values; ordinary object schemas are pruned by Kubernetes according to their
schema. See [Kubernetes structural schemas and pruning](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/#specifying-a-structural-schema).

Unsupported constructs raise `SchemaError` with the field path. Recursive models,
ambiguous unions, and constraints that Kubernetes cannot represent are not silently
converted into permissive schemas. Python validators are **not** exported: use a
validation webhook for Python business rules, or explicit Kubernetes CEL schema
extensions when appropriate. Pydantic may coerce input during local validation;
Kubernetes's schema validation does not promise the same coercions.

Use regular Pydantic `Field` annotations for bounds and aliases. `CEL` and
`ListType` express common Kubernetes-only extensions next to the type:

```python
from cloudcoil.crd import CEL, ListType


class Condition(BaseModel):
    type: str
    status: Literal["True", "False", "Unknown"]


class ExampleSpec(BaseModel):
    replicas: Annotated[int, Field(ge=0), CEL("self <= 10", "At most ten replicas")] = 1
    conditions: Annotated[list[Condition], ListType("map", keys=("type",))] = Field(
        default_factory=list
    )
```

`ListType("set")` and `ListType("atomic")` are also supported. Map keys use wire
names. CEL runs in Kubernetes, not in Pydantic; Python `field_validator` and
`model_validator` still apply when admission parses the typed resource.
`Field(json_schema_extra=...)` remains available for other Kubernetes extensions.
These must still be valid for the field's Kubernetes schema. Generation is not a CEL compiler; test your CRD
against the API-server versions you support. The repository's integration test
installs generated CRDs and checks schema validation and status operations.

## Admission handlers

Keep policies on the resource class with `@mutating()` and `@validating()` as
above, then register one or more models with `admission.register(Widget, Other)`.
Use `@classmethod` outermost; `@staticmethod` also works. Class methods receive
`AdmissionRequest[Self]`, so inherited policies remain typed to the concrete model
and DELETE does not require a current instance. Normal Python method shadowing
applies: overriding a method without the admission decorator removes that policy.
Registration is atomic and rejects duplicate paths.

The plural and scope come from `@custom_resource`. Default paths use the operation,
DNS group components, version, plural, and method name; for example
`/mutate/examples/cloudcoil/dev/v1alpha1/widgets/default_labels`. A decorator's
`path=` can override it. Explicit functions remain supported for existing resource
models or policies kept in another module:

```python
@admission.validating(Widget, resource="widgets", path="/additional-check")
async def additional_check(request: AdmissionRequest[Widget]) -> None:
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

## API client and request context

Add a second argument to a resource's bound handler when a policy needs a Kubernetes
lookup. The application injects `AsyncAPIClient[Self]` from an explicitly supplied
`Config`, alongside the complete admission context:

```python
from cloudcoil.client import AsyncAPIClient, Config

# Inside Widget:
@classmethod
@validating(operations=("UPDATE",))
async def protect_ready_spec(
    cls, request: AdmissionRequest[Self], client: AsyncAPIClient[Self]
) -> None:
    current = await client.get(request.name)
    if (
        current.status is not None
        and request.resource is not None
        and request.resource.spec.message != current.spec.message
    ):
        raise AdmissionDenied("A ready Widget's message cannot be changed")

# Supply the credentials and cluster explicitly in the application setup:
config = Config()
admission = AdmissionWebhook(config=config).register(Widget)
```

Pure handlers take just `request` and need no Config. Client-taking handlers fail
registration clearly if Config is absent. Registration performs no discovery;
client discovery and any lookup happen asynchronously within the webhook's timeout.
Injected clients bypass informer caches. For namespaced resources, the injected
client defaults to the admission request's namespace, so `await client.get(name)`
looks up that namespace without changing Config or clients for other requests. `request.config` exposes that same Config
for other types, for example
`await request.config.async_client_for(ConfigMap, cached=False)` after checking it
is not `None`. `request` also carries `old_resource`, `dry_run`, `user_info`,
`options`, and raw current/previous objects. Read-only lookups work during dry runs;
keep all callbacks free of external writes. Admission does not make a lookup and
subsequent API-server persistence atomic.

The caller owns the Config: keep it alive while the app serves, drain requests, and
close `config.client` and `config.async_client` during application shutdown.
Admission never installs a global/default Config and never closes caller clients.

## Serve and register

`AdmissionWebhook` is a dependency-free ASGI application. Serve it with your existing
ASGI server and TLS setup; installing Cloudcoil does not install or start an HTTP
server. For the runnable example:

```bash
uv run --extra kubernetes --with uvicorn uvicorn examples.widget_operator:admission \
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

## Runnable operator

[widget_operator.py](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py)
contains the model, CRD descriptor, mutator, validator, and controller in one module.
It maintains an owned ConfigMap with the Widget's message, repairs changes to that
child, and returns stable status containing the observed generation and child name.
It refuses to adopt an unrelated ConfigMap. Kubernetes owner references handle
child cleanup when the Widget is deleted.

From a checkout:

```bash
uv run --extra kubernetes python examples/widget_operator.py crd > widgets.crd.yaml
kubectl apply -f widgets.crd.yaml
uv run --extra kubernetes python examples/widget_operator.py controller --namespace default
```

Create a resource to reconcile:

```yaml
apiVersion: examples.cloudcoil.dev/v1alpha1
kind: Widget
metadata:
  name: greeting
  namespace: default
spec:
  message: Hello from Cloudcoil
```

For the admission example, serve the ASGI application with TLS, create its Service,
then generate and apply registration manifests:

```bash
uv run --extra kubernetes python examples/widget_operator.py webhook-config \
  --namespace operators --service widget-webhook --ca-file /certs/ca.crt \
  > widgets.webhooks.yaml
kubectl apply -f widgets.webhooks.yaml
```

The controller needs get/list/watch on Widgets and ConfigMaps, create/patch on
ConfigMaps, and patch on `widgets/status`. Lease election additionally needs the
Lease permissions described in the controller guide. Admission handlers in this
example need no Kubernetes API permissions. CRD and webhook-configuration
installation require separate cluster-level permissions; controller startup does
not install either automatically.
