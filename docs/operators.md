# Operator entry point

`Operator` brings resource definitions, controller RBAC, admission hosting, and the
controller manager into one application definition. Use `operator.main()` instead
of writing argument parsing, signal handling, or client cleanup for each operator.

```python
from cloudcoil.controller import Controller
from cloudcoil.operator import Operator, RBACRule, WebhookServer

operator = Operator(
    "widgets",
    Controller(Widget, reconcile).owns(ConfigMap, Deployment, Service),
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("widget-policy",)),),
    webhook=WebhookServer(tls_secret="widgets-tls"),
    leader_election=True,
)

if __name__ == "__main__":
    operator.main()
```

The [complete Widget example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py)
defines the resource, policies, reconciler, and operator in one module. It maintains
an owned ConfigMap, Deployment and Service using `request.ensure(...)`, and returns
the Widget with updated status for automatic patching. The
[local demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets) includes
a Dockerfile, TLS setup, installation, drift repair and admission policy checks.
Handwritten resources inherit normal client operations; for explicit access use
`client = await Widget.async_client(config)` and `await client.get("example")`.

Install `cloudcoil[operator,kubernetes]` for the shared HTTPS runtime. Uvicorn is an
optional dependency; manifest generation and controller-only operators do not
start or require an HTTP server. Until supported Kubernetes model packages are
published, follow the [model generation instructions](https://github.com/cloudcoil/cloudcoil#-installation).

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
`--command python app.py` alongside `--image`. Cloudcoil does not build or publish
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
Owned-child write permissions follow the controller watch scope. A mapped
`watch` only grants read access and does not expand separate write permissions. `subresources=("status",)` targets only those endpoints;
`resource_names=("settings",)` restricts named operations where Kubernetes permits it.

Runtime ServiceAccounts receive no implicit permission to install CRDs, edit RBAC,
or register webhooks. Run `install` using an identity permitted to perform setup;
the deployed application runs `run` with its generated ServiceAccount. The client
does not inspect Python function bodies to infer arbitrary API access.
[Kubernetes RBAC rules](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

## Lifecycle and embedding

`await operator.run(stop=event)` embeds the runtime without replacing signal
handlers. `operator.main()` supplies SIGINT/SIGTERM handling. Owned clients close
after workers and webhook requests have stopped; a supplied Config stays open.
Fatal component errors stop sibling components and propagate. Each operator and
controller runs once; use a new instance for a restart.

Webhook serving runs on every replica independently of manager leadership.
HTTPS `/readyz` measures admission availability, and `/controllers/readyz`
measures controller readiness; standby replicas continue receiving admission
traffic. `/healthz` and `/metrics` are available on the same listener. For an
operator without webhooks, pass `health=HealthServer(...)` to expose the manager's
health server. `operator.manager` becomes available during startup for direct
manager readiness and metrics access.

Controllers and webhooks both use `await request.client(ResourceType)` for a live
client of any kind, defaulting to the request namespace and sharing the operator
connection. Callbacks do not manage connections or their lifetime.

All managed controllers share the operator Config. For controllers targeting
different clusters, use separate operators or the lower-level `Manager` API.
The lower-level `CRD`, `AdmissionWebhook`, and `Manager` remain usable independently.
