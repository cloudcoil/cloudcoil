# Patterns

These are executable applications, with tested callbacks, informer reads and generated
manifests. Run commands from the repository root with the development dependencies and
current generated Kubernetes models installed (see [the Widget demo](https://github.com/cloudcoil/cloudcoil/tree/main/examples/widgets)).

| Pattern | Example | Reads and writes |
| --- | --- | --- |
| Mirror objects of the same kind | [ConfigMap mirror](https://github.com/cloudcoil/cloudcoil/blob/main/examples/configmap_controller.py) | Ensure missing children; guarded replacement of the complete data map |
| One CR manages several child kinds | [Widget](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py) | `ensure` ConfigMap, Deployment and Service; decorated stages and automatic status |
| Cases within a stage | [Conditional configuration](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/conditional_config.py) | First-match branches with a dependent checksum stage |
| Watch dependencies without owning them | [Dependency rollout](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/dependency_rollout.py) | Cache-get referenced ConfigMaps; reverse-map changes to opted-in Deployments |
| Aggregate existing resources | [Workload summary](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/workload_summary.py) | Cache-list Pods by labels; report CR status; no Pod writes |
| Variable number of children and pruning | [Child set](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/child_set.py) | Ensure desired ConfigMaps; cache-list old children; delete with UID/version guards |
| External resources and periodic repair | [Finalizers](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/finalizers.py) | Persist finalizer before side effects; retry idempotent cleanup; timed requeue |
| Several controllers in one process | [Multiple controllers](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/multiple_controllers.py) | Shared runtime and clients, leader election, separate reconcilers |
| Admission on existing built-in resources | [Deployment policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_existing.py) | Live-read namespace policy; defaults, immutable label, delete protection, `/scale` |
| Admission on someone else's CRD | [Database policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_external_crd.py) | Compare UPDATE snapshots; no CRD installation or ownership |
| Admission with informer reads | [Pod policy](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/admission_cached.py) | Per-replica Namespace cache; live fallback on a miss |

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
[demo.sh](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widgets/demo.sh) for certificate creation, in-cluster installation and
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

## Read and write contracts

See [live clients and informer reads](reads.md), [reconciliation and children](controllers.md),
and [admission policies](admission.md) for the shared contracts. Each example declares
its dependencies and additional RBAC explicitly. Cache scans and reverse dependency
maps are linear; the framework does not currently expose custom indexes.

## Verification

`tests/test_controller_patterns.py` exercises these callbacks, ownership guards,
cache isolation and scopes, old/new admission snapshots, Scale payload targeting,
and manifests for every example. `tests/test_controllers.py` exercises cached reads
inside the running controller and mapper lifecycle. Public APIs are checked by
mypy and pyright. The packaged Widget demo additionally exercises TLS, generated
RBAC, API-server admission, readiness and the existing-Deployment policy in kind.

## ConfigMap mirror

The [mirror example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/configmap_controller.py)
also uses the shared entry point:

```sh
CLOUDCOIL_NAMESPACE=default uv run --no-sync python examples/configmap_controller.py manifests
CLOUDCOIL_NAMESPACE=default uv run --no-sync python examples/configmap_controller.py run
```

Label a source `example.com/mirror=true`; its child is named `<source>-mirror`.
Unlike `ensure` map merging, this example intentionally replaces the entire child
data map to remove keys deleted from the source. It uses `mutate` for that guarded
replacement. Leader election and probes on port 8080 are configured on the Application;
the example no longer needs its own signal handling or separate CLI flags.


The [lifespan example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/lifespan.py)
shows process and leader scopes, typed acquisition/loss/shutdown events, and cleanup ordering.
