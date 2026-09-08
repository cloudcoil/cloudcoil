# Controller and admission patterns

Start with the [pattern guide](../../docs/patterns.md) for runnable commands, sample
resources, and the choice of ownership, dependencies, live reads and informer caches.
The [published guide](https://cloudcoil.github.io/cloudcoil/patterns/) has the same content.

| Pattern | Example | Reads and writes |
| --- | --- | --- |
| One CR manages several child kinds | [Widget](../widget_operator.py) | `ensure` ConfigMap, Deployment and Service; decorated stages and automatic status |
| Ordered stages and rollout readiness | [Widget](../widget_operator.py) | Named stages; automatic conditions, Events, waiting and error retries |
| Cases within a stage | [Conditional config](conditional_config.py) | Suspend, wait, or configure; then run a dependent checksum stage |
| Watch dependencies without owning them | [Dependency rollout](dependency_rollout.py) | Cache-get referenced ConfigMaps; reverse-map changes to opted-in Deployments |
| Aggregate existing resources | [Workload summary](workload_summary.py) | Cache-list Pods by labels; report CR status; no Pod writes |
| Variable number of children and pruning | [Child set](child_set.py) | Ensure desired ConfigMaps; cache-list old children; delete with UID/version guards |
| External resources and periodic repair | [Finalizers](finalizers.py) | Persist finalizer before side effects; retry idempotent cleanup; timed requeue |
| Several controllers in one process | [Multiple controllers](multiple_controllers.py) | Shared runtime and clients, leader election, separate reconcilers |
| Admission on existing built-in resources | [Deployment policy](admission_existing.py) | Live-read namespace policy; defaults, immutable label, delete protection, `/scale` |
| Admission on someone else's CRD | [Database policy](admission_external_crd.py) | Compare UPDATE snapshots; no CRD installation or ownership |
| Admission with informer reads | [Pod policy](admission_cached.py) | Per-replica Namespace cache; live fallback on a miss |

The [lifespan example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/lifespan.py)
shows process and leader scopes, typed acquisition/loss/shutdown events, and cleanup ordering.
