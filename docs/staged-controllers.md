# Staged reconciliation

Implementation plan for the optional stage API. Ordinary reconcile functions stay
the simplest choice for small controllers.

## Contract

- Re-evaluate desired and observed state on every pass. A completed stage is not a
  durable instruction pointer: earlier stages must repair drift after restarts.
- Compose named stages in explicit order. Each successful stage continues; waiting
  or failure stops the pass. Offer ordered, first-match cases for mutually exclusive
  actions, using the same execution and error handling.
- Register cases on an instance before startup. Explicit priorities may order
  separately registered cases, with duplicate priorities rejected so module import
  order cannot silently decide execution. Predicates inspect state without writes.
- Status conditions describe current observations, with stable transition times and
  observedGeneration. Status updates preserve unrelated fields and conditions.
- Waits are normal progress, exceptions retry with the existing exponential backoff,
  and TerminalError suppresses automatic retry until a later input/event/resync.
- Failure reporting persists only deliberate status changes, never half-edited spec
  or metadata. Status patch conflicts retry reconciliation from a fresh snapshot.
- Kubernetes Events are best-effort diagnostics. Deduplicate/rate-limit repeated
  events; event delivery failure must not replay successful provisioning.
- Primary status writes must not turn failures or waits into immediate busy loops.
  Preserve spec, deletion, metadata, child and dependency notifications.
- Keep finalizer persistence before external provisioning, cleanup before finalizer
  removal, and retry-safe external operations. Never infer deletion from cache absence.

## Existing example coverage

The Widget operator benefits from named ensure/readiness stages; workload summary
benefits from condition/status helpers. The dependency reloader and ConfigMap mirror
remain small reconcile functions. Child-set pruning remains an explicit ownership-
guarded loop. External finalizers keep their live-read persistence boundary.
Multiple controllers continue sharing Application. Admission examples retain the
separate request/response lifecycle and must not emit reconciliation side effects.

## Delivery and verification

1. Condition/status helpers, transition stability and preservation tests.
2. Event recording with bounded deduplication and delivery-failure tests.
3. Ordered stages/cases, wait/failure outcomes, automatic status reporting and
   workqueue regression tests (including own-status updates and conflicts).
4. Runnable examples and API documentation; regression/type/lint checks.

References: [Kubernetes API conventions](https://github.com/kubernetes/community/blob/main/contributors/devel/sig-architecture/api-conventions.md),
[controller-runtime outcomes](https://pkg.go.dev/sigs.k8s.io/controller-runtime/pkg/reconcile),
[Kopf error handling](https://docs.kopf.dev/en/stable/errors/).
