# Application deployment

`Application` brings resource definitions, controller RBAC, admission hosting, and the
controller manager into one application definition. Use `app.main()` instead
of writing argument parsing, signal handling, or client cleanup for each operator.

```python
from cloudcoil.application import Application
from cloudcoil.controller import Context
from cloudcoil.admission import AdmissionRequest
from cloudcoil.application import RBACRule, WebhookServer

app = Application(
    "widgets",
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("widget-policy",)),),
    webhook=WebhookServer(tls_secret="widgets-tls"),
    leader_election=True,
)

widgets = app.controller(Widget, owns=(ConfigMap, Deployment, Service))

@widgets.reconcile()
async def reconcile(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_deployment(widget))

@widgets.validate()
async def validate(request: AdmissionRequest[Widget]) -> None:
    ...  # Raise AdmissionDenied for an invalid request.

if __name__ == "__main__":
    app.main()
```

The [complete Widget example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py)
defines the resource, policies, reconciler, and operator in one module. It maintains
an owned ConfigMap, Deployment and Service using `ctx.ensure(...)`, with decorated stages and automatic status reporting. The
[local demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets) includes
a Dockerfile, TLS setup, installation, drift repair and admission policy checks.
Handwritten resources inherit normal client operations; for explicit access use
`client = await Widget.async_client(config)` and `await client.get("example")`.

Install `cloudcoil[operator,kubernetes]` for the shared HTTPS runtime. Uvicorn is an
optional dependency; manifest generation and controller-only operators do not
start or require an HTTP server. Until supported Kubernetes model packages are
published, follow the [model generation instructions](getting-started.md#install).

## Generate, install, run

The same executable has three commands:

```bash
# Offline: no kubeconfig, discovery, or API requests.
python app.py manifests --image example/widgets:v1 > operator.yaml

# Apply with your installation credentials; wait for CRDs and Deployment rollout.
python app.py install --image example/widgets:v1

# Run with the Pod's ServiceAccount or your local kubeconfig.
python app.py run
```

The container image must contain your application and dependencies, with its
entry point set to execute the module (for example `ENTRYPOINT ["python", "app.py"]`).
The generated Deployment adds `run` as its arguments. Alternatively pass
`--command "python app.py"` alongside `--image`. Cloudcoil does not build or publish
the image. `--replicas 2` generates two replicas; configure leader election when
only one reconciliation manager should be active.

The namespace defaults to an explicitly supplied Config's namespace, then
`CLOUDCOIL_NAMESPACE`, then `default`. An explicit `namespace=` overrides that
choice and must match a supplied Config. Generated Pods receive their namespace
through the downward API. For the runnable example:

```bash
export CLOUDCOIL_NAMESPACE=operators
export CLOUDCOIL_WEBHOOK_CA_FILE=/certs/ca.crt
python examples/widget_operator.py manifests --image example/widgets:v1
python examples/widget_operator.py install --image example/widgets:v1
```

Create the namespace and `widgets-tls` Secret first. The Secret contains `tls.crt`
and `tls.key`; the certificate must cover `widgets.operators.svc`. The shared CLI accepts `--ca-file` (or `CLOUDCOIL_WEBHOOK_CA_FILE`) for manifests
and installation, so it can start in the Pod using
the mounted certificate and key without that environment variable. TLS defaults
to `/var/run/cloudcoil/tls/tls.crt` and `tls.key`, port 9443, behind Service port 443.
Certificate issuance and rotation remain with your certificate/deployment tooling;
restart Pods after replacing serving certificates. Private keys never appear in
generated manifests. [Kubernetes webhook TLS requirements](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/#contacting-the-webhook).

`install` uses server-side apply with a named field manager. It waits for each
CRD's `Established` condition, applies runtime RBAC and the Service/Deployment,
waits for the current Deployment revision to be available, then enables admission
registrations and refreshes discovery. Existing field ownership conflicts fail;
`--force` explicitly takes ownership. `--timeout` bounds the whole installation.
Failures leave already applied objects for inspection and retry; installation
does not delete or roll back resources.

For CRD/RBAC setup without webhook registration or a Deployment:

```bash
python app.py manifests --without-webhooks
python app.py install --without-webhooks
```

Installing webhook registration requires an image so the installer can wait for
the serving Deployment. For an externally managed server, export manifests and
apply them through your deployment system in the same order. During removal,
remove admission registrations before removing their server.

## Resources and permissions

Decorated primary resources are automatically included as CRDs. Add other owned
definitions through `resources=(OtherResource, CRD(...))`. Watched dependencies
are not automatically installed: they may belong to another operator. Repeated
definitions of the same CRD name fail, including competing single-version models.

RBAC inference covers the framework's own operations:

| Access | Generated permissions |
| --- | --- |
| Primary resource | get, list, watch, patch |
| Enabled primary status | patch on `/status` |
| Owned children (`owns`) | get, list, watch, create, patch |
| Referenced dependencies (`watch`) | get, list, watch |
| Leader election | create Leases; get/update the named Lease |
| Arbitrary reconcile/webhook client calls | Declare with `RBACRule` |

CRDs and newly generated models provide exact plurals and scope. Older generated
models need these declared once in an `RBACRule`, or can be regenerated.
This avoids guessing irregular plurals or accidentally granting cluster-wide
access. Namespaced rules default to the operator namespace. Use `namespace=` for
another namespace or `all_namespaces=True` explicitly; `scope="Cluster"` describes
cluster-scoped resources. Controller `namespace`/`all_namespaces` settings drive
watch permissions, and cluster-scoped owners may watch children across namespaces.
Namespaced admission registrations follow the primary controller namespaces unless a route supplies an explicit
`namespace_selector`;
webhook-only resources default to the operator namespace. Cluster resources and
all-namespace controllers retain cluster-wide admission matching.
Owned-child write permissions follow the controller watch scope. A mapped
`watch` only grants read access and does not expand separate write permissions. `subresources=("status",)` targets only those endpoints;
`resource_names=("settings",)` restricts named operations where Kubernetes permits it.

Runtime ServiceAccounts receive no implicit permission to install CRDs, edit RBAC,
or register webhooks. Run `install` using an identity permitted to perform setup;
the deployed application runs `run` with its generated ServiceAccount. The client
does not inspect Python function bodies to infer arbitrary API access.
[Kubernetes RBAC rules](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

## Lifecycle and embedding

`await app.run(stop=event)` embeds the runtime without replacing signal
handlers. `app.main()` supplies SIGINT/SIGTERM handling. Owned clients close
after workers and webhook requests have stopped; a supplied Config stays open.
Fatal component errors stop sibling components and propagate. Each operator and
controller runs once; use a new instance for a restart.

Webhook serving runs on every replica independently of manager leadership.
HTTPS `/readyz` measures admission availability, and `/controllers/readyz`
measures controller readiness; standby replicas continue receiving admission
traffic. `/healthz` and `/metrics` are available on the same listener. For an
operator without webhooks, pass `health=HealthServer(...)` to expose the manager's
health server. `app.manager` becomes available during startup for direct
manager readiness and metrics access.

Controllers use `await ctx.client(ResourceType)` and admission uses
`await request.client(ResourceType)` for a live client of any kind, defaulting to the request namespace and sharing the operator
connection. Callbacks do not manage connections or their lifetime.

All managed controllers share the operator Config. For controllers targeting
different clusters, use separate operators or the lower-level `Manager` API.
The lower-level `CRD`, `AdmissionWebhook`, and `Manager` remain usable independently.

## Common patterns

The [pattern examples](patterns.md) cover informer get/list,
shared dependencies, existing-resource aggregation, child pruning, finalizers,
multiple controllers, and admission on built-in or externally defined resources.
Use `ctx.cached(Kind)` for controller snapshots and `await ctx.client(Kind)` for
live API access. Register standalone policies with `@app.validate(Model)` and
`@app.mutate(Model)` without adding a CRD or controller.


## Lifespan decorators

```python
from collections.abc import AsyncIterator
from cloudcoil.application import LifecycleEvent, LifecycleType

@app.lifespan()
async def process(event: LifecycleEvent) -> AsyncIterator[None]:
    async with provider:
        yield

@app.lifespan(scope="leader")
async def leadership(event: LifecycleEvent) -> AsyncIterator[None]:
    # Lease is acquired and renewed while this scope is active.
    await leader_services.start()
    try:
        yield
    finally:
        # Reconciliation workers have stopped. Read the updated exit event here.
        if event.type == LifecycleType.LEADERSHIP_LOST:
            logger.warning("Lost leadership: %s", event.error)
        await leader_services.stop()
```

Each scope has one async-generator hook, taking zero arguments or a LifecycleEvent.
Compose multiple resources with async with/AsyncExitStack inside it. Use finally for
cleanup on cancellation; statements after an unguarded yield can be skipped.

| Scope | Entry event | Exit event | Lifetime |
| --- | --- | --- | --- |
| process (default) | STARTUP | SHUTDOWN, FAILURE, or LEADERSHIP_LOST | Every replica, around webhook and controller execution |
| leader | LEADERSHIP_ACQUIRED | SHUTDOWN, LEADERSHIP_LOST, or FAILURE | After lease acquisition, before controller startup; exits after workers stop, before lease release |

The same event object's type/error are updated before cleanup; identity identifies
the election participant. A leader scope requires configured leader election and
at least one controller. Standbys enter only the process scope. Offline manifests
and installation do not enter either scope. Hooks register before runtime starts;
late registration fails. Startup must complete before handlers are started.

On loss the runtime cancels and joins workers, runs leader cleanup, attempts guarded
lease release, and exits. It does not reacquire within the same manager instance.
Cleanup after loss must not assume lease ownership or delete shared external state.
Lifecycle hooks manage process services; resource finalizers manage object deletion.
See the [lifecycle example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/lifespan.py).

## Definition validation

An initially empty Application is valid while decorators register components.
Manifest generation validates the completed registry offline; run validates and
freezes it before network startup. Include reusable groups with app.include(group),
or create/include them together with app.controller(Model, ...). Duplicate inclusion,
ambiguous stage/case order, missing fallbacks, conflicting routes and missing webhook
hosting configuration fail explicitly. Registration does not execute handler code.
