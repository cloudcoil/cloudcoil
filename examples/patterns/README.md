# Controller and admission examples

Each module is an executable Application using the decorator API. Start with the
[pattern catalog](../../docs/patterns.md) for the full comparison and sample resources.

## Run an example

From the repository root, complete the [checkout setup](../../docs/getting-started.md#run-the-checkout), then:

```sh
export CLOUDCOIL_NAMESPACE=default
uv run --no-sync python -m examples.patterns.workload_summary manifests
uv run --no-sync python -m examples.patterns.workload_summary install
uv run --no-sync python -m examples.patterns.workload_summary run
```

`manifests` is offline. `install` applies the CRD and RBAC; `run` uses your configured
cluster credentials. For Pod deployment, add an image and command as described in
the [deployment guide](../../docs/operators.md).

## Choose a starting point

- [Conditional configuration](conditional_config.py): cases inside a stage, then a dependent checksum stage.
- [Dependency rollout](dependency_rollout.py): watch referenced ConfigMaps and update existing Deployments.
- [Workload summary](workload_summary.py): list cached Pods and report status without owning them.
- [Child set](child_set.py): maintain and prune a variable set of owned resources.
- [Finalizers](finalizers.py): provision external state, repair periodically and clean up on deletion.
- [Multiple controllers](multiple_controllers.py): include reusable groups in one application.
- [Lifespan](lifespan.py): process and leader hooks with typed exit events.
- [Deployment policy](admission_existing.py): defaulting, validation, DELETE and `/scale`.
- [External CRD policy](admission_external_crd.py): validate another operator's resource without installing its CRD.
- [Cached policy](admission_cached.py): admission with a per-replica cache and explicit live fallback.

Admission examples need a TLS Secret and CA bundle; the
[Widget demo](../widgets/README.md) shows a complete deployment. The finalizer
example uses a demo-only in-memory provider; replace it with an idempotent durable
API adapter for real external resources.

For the shared execution and reporting rules, read
[controllers](../../docs/controllers.md), [stages and cases](../../docs/staged-controllers.md)
and [read contracts](../../docs/reads.md).
