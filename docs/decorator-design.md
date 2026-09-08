# Decorator registration contract

Controllers are scoped registries. Applications include them explicitly, or create
and include them with `app.controller(Model, owns=(...))`. Registration performs no
network I/O. Completed definitions are validated for manifest generation and frozen
before execution.

- `@controller.reconcile(every=...)` receives a present, non-deleting resource and
  optional `Context[Model]`. Ordinary Python describes the flow.
- `@controller.stage(condition=..., depends=...)` registers an automatic stage.
  Dependencies reference registered functions or named stage scopes. A unique order
  is required; missing dependencies, cycles and ambiguity are errors.
- `controller.stage("configuration", condition=...)` creates a scope whose
  `@case(when=..., after=...)` and `@otherwise()` handlers select one branch.
  Root controllers support the same case dispatch. A fallback is mandatory.
- A controller has one entrypoint: reconciliation, stages, or cases. A stage has
  either one handler or cases. No numeric priorities or separate step abstraction
  are needed by the decorator API.
- Every reconciliation repairs current state from the beginning. Conditions are
  observations, never durable execution checkpoints. Waiting stops the pass.
- `raise Wait(reason, message, after=...)` represents expected pending work.
  Ordinary exceptions retry with backoff; `TerminalError` waits for another input.
- Context status/condition helpers validate and stage reports. Events are queued,
  bounded, and best effort. Explicit reports may persist on failure; partial primary
  spec/metadata edits never do. Returning the primary resource commits successful
  edits. Previously performed child writes are not rolled back.
- `ReconcileStatus` opts a CR into aggregate Ready reporting. Stage cases report
  their outcome on the enclosing condition, without creating branch conditions.
- `@controller.finalize(key)` persists the finalizer before provisioning, rechecks
  deletion, retries idempotent cleanup, and removes the finalizer after success.
  Cache absence is never permission for destructive cleanup.
- `@controller.watch(Model)` registers a dependency mapper. Old and new versions
  are mapped on updates; owner watches follow `owns` declarations automatically.
- `@controller.validate()` / `@controller.mutate()` use `AdmissionRequest[Model]`.
  Application-level variants accept a payload model and optional subresource target.
  Admission registration does not imply resource ownership or CRD installation.
- `@app.lifespan()` pairs per-process startup and shutdown around handler execution,
  including non-leader replicas. `scope="leader"` enters only after acquisition and
  exits after workers stop, before lease release. Optional `LifecycleEvent` reports
  startup/acquisition and is updated to shutdown/loss/failure before cleanup. Use
  try/finally around yield for cleanup on cancellation. Leadership loss remains
  fatal; the existing manager does not silently reacquire in-process. Offline
  manifest generation does not enter either lifespan.

Implementation will retain the existing low-level runtime while migrating examples
and documentation to the decorator interface, with meaningful runtime and typing
tests for ordering, nested dispatch, reporting, finalizers and lifecycle failures.
