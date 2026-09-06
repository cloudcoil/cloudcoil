# Widget operator, end to end

A `Widget` serves its message through an owned ConfigMap, Deployment and Service.
The controller repairs edits and recreates deleted children. Kubernetes garbage
collection removes children when their Widget is deleted. A webhook adds a label
and checks an optional namespace policy using the same client API as reconciliation.

The implementation is in [`../widget_operator.py`](../widget_operator.py). It has
one resource declaration, one reconciler and one `Operator(...).main()` entry point.

## Run the whole demo

From a checkout of this PR, with Python 3.14, uv, Docker, kind, kubectl, rg and
openssl available:

```bash
bash examples/widgets/demo.sh
```

The script builds matching Kubernetes models and an operator image, creates a
`cloudcoil-widgets` kind cluster, provisions a demo TLS certificate, installs CRD,
RBAC, Deployment and admission registration, then creates a Widget and waits for
readiness. The controller runs with its generated ServiceAccount. The short-lived
certificate is for local demonstration; use your certificate tooling in production.

```bash
kubectl --context kind-cloudcoil-widgets -n widgets port-forward svc/hello 8080:80
# In another terminal:
curl http://localhost:8080
```

## Change desired state and repair drift

Use the demo context explicitly:

```bash
kubectl --context kind-cloudcoil-widgets -n widgets patch widget hello --type merge \
  -p '{"spec":{"message":"Updated through the CRD","replicas":2}}'
kubectl --context kind-cloudcoil-widgets -n widgets get widgets -w

# The operator recreates this ConfigMap. No manual enqueue/requeue is needed.
kubectl --context kind-cloudcoil-widgets -n widgets delete configmap hello
kubectl --context kind-cloudcoil-widgets -n widgets get configmaps -w
```

ConfigMap volume updates reach nginx asynchronously; allow Kubernetes time to
refresh the projected file. `status.phase` tracks Deployment availability and its
observed generation, not propagation of the projected content.

## Admission reads another resource

```bash
kubectl --context kind-cloudcoil-widgets -n widgets create configmap widget-policy \
  --from-literal=maxLength=10
kubectl --context kind-cloudcoil-widgets -n widgets patch widget hello --type merge \
  -p '{"spec":{"message":"This message exceeds the namespace policy"}}' --dry-run=server
```

The second command is rejected with the policy limit. The validator uses
`await request.client(ConfigMap)` and only reads. Delete the optional policy to
restore the CRD's 200-character limit. Policy changes affect subsequent admission;
they do not retroactively reject existing Widgets.

## Review or customize installation

After the generated models have been installed locally:

```bash
CLOUDCOIL_NAMESPACE=widgets uv run --no-sync python examples/widget_operator.py manifests \
  --without-webhooks > foundation.yaml
CLOUDCOIL_NAMESPACE=widgets uv run --no-sync python examples/widget_operator.py manifests \
  --image your-registry/widgets:v1 --ca-file /path/to/public-ca.crt > operator.yaml
```

The image must be available to the cluster. The namespace and `widgets-tls` Secret
must exist before `install`; its certificate must cover `widgets.widgets.svc`.
Use `install` with the same options to wait for CRDs and the Deployment before
registering webhooks. The runtime mounts the Secret; it does not need the public
CA file. See [operator documentation](../../docs/operators.md) for embedding and TLS.

`owns(ConfigMap, Deployment, Service)` declares watches and get/list/watch/create/
patch permissions. `request.ensure(...)` defaults child identity from the Widget,
sets the controller owner, and refuses to adopt an unrelated object with that name.
Omitted fields survive, maps merge, lists replace, and explicit `None` clears a
field. There is no automatic pruning: if a variable child set shrinks, delete the
obsolete children explicitly and declare the corresponding delete permission.
Use explicit names when managing multiple children of the same kind.

For a referenced dependency that belongs to another controller, use
`watch(Resource, mapper=...)` and `request.client(Resource)`; do not use `ensure`.

## Cleanup

```bash
kind delete cluster --name cloudcoil-widgets
```

The CI live test imports this exact reconciler and exercises three-child creation,
CR updates, drift repair, deletion/recreation, allocated Service field preservation,
status persistence and admission policy reads against Kubernetes.
