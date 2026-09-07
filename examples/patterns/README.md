# Controller and admission patterns

These are executable applications, with tested callbacks, informer reads and generated
manifests. Run commands from the repository root with the development dependencies and
current generated Kubernetes models installed (see [the Widget demo](../widgets/README.md)).

| Pattern | Example | Reads and writes |
| --- | --- | --- |
| One CR manages several child kinds | [Widget](../widget_operator.py) | `ensure` ConfigMap, Deployment and Service; return parent status |
| Watch dependencies without owning them | [Dependency rollout](dependency_rollout.py) | Cache-get referenced ConfigMaps; reverse-map changes to opted-in Deployments |
| Aggregate existing resources | [Workload summary](workload_summary.py) | Cache-list Pods by labels; return CR status; no Pod writes |
| Variable number of children and pruning | [Child set](child_set.py) | Ensure desired ConfigMaps; cache-list old children; delete with UID/version guards |
| External resources and periodic repair | [Finalizers](finalizers.py) | Persist finalizer before side effects; retry idempotent cleanup; timed requeue |
| Several controllers in one process | [Multiple controllers](multiple_controllers.py) | Shared runtime and clients, leader election, separate reconcilers |
| Admission on existing built-in resources | [Deployment policy](admission_existing.py) | Live-read namespace policy; defaults, immutable label, delete protection, `/scale` |
| Admission on someone else's CRD | [Database policy](admission_external_crd.py) | Compare UPDATE snapshots; no CRD installation or ownership |
| Admission with informer reads | [Pod policy](admission_cached.py) | Per-replica Namespace cache; live fallback on a miss |

## Run and generate manifests

Every module has the same entry point:

```sh
export CLOUDCOIL_NAMESPACE=default
uv run --no-sync python -m examples.patterns.workload_summary manifests
uv run --no-sync python -m examples.patterns.workload_summary install
uv run --no-sync python -m examples.patterns.workload_summary run
```

`install` applies CRDs and RBAC using your current credentials. `run` stays in the
foreground and uses those credentials. For deployment, put the module and cloudcoil
in an image, and add `--image IMAGE --command "python -m examples.patterns.workload_summary"`
to `manifests` or `install`. The runtime appends `run`. Use the generated ServiceAccount
and RBAC when deploying; a local administrator's kubeconfig does not test runtime permissions.

Admission examples also require a TLS Secret and a PEM CA file supplied through
`--ca-file`. The certificate must cover `<operator-name>.<namespace>.svc`. See
[demo.sh](../widgets/demo.sh) for certificate creation, in-cluster installation and
real API-server admission checks, including the Deployment policy and `/scale`.

Create a Workload to summarize existing Pods:

```yaml
apiVersion: patterns.cloudcoil.dev/v1alpha1
kind: Workload
metadata:
  name: web
spec:
  selector:
    app: web
```

For the reloader, label an existing Deployment
`patterns.cloudcoil.dev/reloader=true` and reference a ConfigMap using a volume
(including projected volumes), `envFrom`, or `env.valueFrom`. Updates to that
ConfigMap change the pod-template digest. Removing a reference also recomputes it.

For a variable child set:

```yaml
apiVersion: patterns.cloudcoil.dev/v1alpha1
kind: Bundle
metadata:
  name: settings
spec:
  entries:
    frontend: hello
    backend: world
```

Removing `backend` from `spec.entries` prunes its owned ConfigMap. Deleting the
Bundle lets Kubernetes garbage-collect its children. The external-resource example
uses a demo-only in-memory provider; replace it with a durable API adapter before
using it for real external resources.

## Informer reads versus API reads

```python
# Inside a reconciler: local, synchronous, copied snapshots.
config = request.cached(ConfigMap).get("settings")
pods = request.cached(Pod).list(labels={"app": "web"})

# Live API access to any kind, using the shared Config and request namespace.
client = await request.client(Secret)
secret = await client.get("credentials")
```

Register informer kinds with `Controller(...).watch(Kind, mapper=...)` or
`.owns(Kind, ...)`. The primary kind is already registered. Mappers can use
`controller.cached(PrimaryKind)` to find dependents. Primary sync completes before
secondary handlers start. Updates map both old and new objects, so changing a label
or reference wakes up both sets of affected parents. Initial LISTs also reconcile
resources that existed before the operator started.

Use `.owns` only for real owner references. Use `.watch` for shared dependencies or
existing resources you must not adopt. A watched kind receives read RBAC; owned
children also receive create/patch RBAC. Declare additional live-read/delete permissions
with `RBACRule`. Merely validating an object grants no CRUD permissions on it.

Cache reads never issue an API request or silently fall back. They require a running,
synced informer; an unwatched kind raises `ValueError`. Missing objects return `None`.
Objects are deep copies, so editing them does not alter the informer. Reads are
eventually consistent, and lists cover only the configured watch scope and selectors.
`namespace=` overrides the request namespace; `all_namespaces=True` means all *watched*
namespaces. These are linear scans with exact AND label matching, not server queries,
resource-version snapshots or indexed joins. For large dependency graphs an indexing
API would be a future extension; these examples intentionally expose that cost.

The queue coalesces keys and retries failures. A reconciliation may run again with
stale inputs, so use idempotent operations. Returning a changed resource patches it
(and its status subresource separately); `Result(requeue_after=60)` requests another
pass. For irreversible work, validate current state through live reads and use API
preconditions. The pruning example verifies ownership and guards DELETE with both
cached UID and resourceVersion, preventing deletion of a replacement object.

## Admission for existing or unowned resources

```python
policies = AdmissionWebhook()


@policies.validating(Deployment, path="/validate-deployment")
async def validate(request: AdmissionRequest[Deployment]) -> None:
    policy = await (await request.client(ConfigMap)).get("deployment-policy")
    # Compare request.resource and request.old_resource; raise AdmissionDenied.


operator = Operator(
    "deployment-policy",
    admission=policies,
    rules=(RBACRule(ConfigMap, ("get",), resource_names=("deployment-policy",)),),
    webhook=WebhookServer(tls_secret="deployment-policy-tls"),
)
```

There is no controller or CRD requirement. Decorators infer plural and scope from
current generated models or `@custom_resource` metadata. External CRD types used only
in admission do not install that CRD. For older models, supply `resource=` and `scope=`.

CREATE has a new object, UPDATE has new and old objects, and DELETE uses
`old_resource`. These snapshots come from the admission request, not an informer.
Existing objects are checked on subsequent matching requests; installing a webhook
does not scan or repair stored objects. Use a controller for retroactive remediation.

Subresources need explicit routes. The Deployment example registers
`validating(Scale, target=Deployment, subresource="scale", operations=("UPDATE",), ...)`
so the payload is `autoscaling/v1 Scale` while the admitted endpoint is
`apps/v1 deployments/scale`. Ordinary Deployment validation alone cannot cap scale
requests. Registrations use exact API versions and subresources, not wildcards.

Namespaced routes default to the operator namespace, or the matching controller's
watch namespaces when present. Cluster-scoped routes are not namespace-filtered.
Set `namespace_selector={"matchLabels": {"policy": "enabled"}}` on a route to
select namespaces explicitly, or `namespace_selector={}` for all namespaces.
The runtime preserves explicit selectors. Review generated selectors and RBAC
for your deployment scope. The
Deployment policy requires `deployment-policy` with `data.maxReplicas` in each
selected namespace; a missing/invalid policy fails closed.

For cache-backed admission, `request.cached(Kind)` requires an explicitly configured
`Cache(resources=[Kind], ...)` on the Operator or its shared Config. Each webhook
replica starts its own cache before serving; leader-only controller informers cannot
serve this purpose. Use one cache namespace or `None` for all namespaces, and
`max_items_per_resource=0` for an unbounded policy cache. A cache miss is not evidence
of absence. The Pod example selects namespaces labeled `patterns.cloudcoil.dev/enforce=true`
and requires `patterns.cloudcoil.dev/allow-pods=true` there. It falls back to a live read on misses; cached hits can
still be stale. Use live reads when decisions must reflect current policy. Reads
across objects are not an atomic admission transaction either way.

## Verification

`tests/test_controller_patterns.py` exercises these callbacks, ownership guards,
cache isolation and scopes, old/new admission snapshots, Scale payload targeting,
and manifests for every example. `tests/test_controllers.py` exercises cached reads
inside the running controller and mapper lifecycle. Public APIs are checked by
mypy and pyright. The packaged Widget demo additionally exercises TLS, generated
RBAC, API-server admission, readiness and the existing-Deployment policy in kind.
