# Stages, cases, conditions and Events

Start with one `@controller.reconcile()` function. Choose stages when separate
progress conditions help explain an operator, and cases for mutually exclusive
behaviors. All use the same clients, ownership checks, reporting and retry queue.
There is no separate step abstraction, code generation or workflow checkpoint store.

## Sequential stages

Define a status derived from `ReconcileStatus`; additional fields need defaults so
new resources can initialize status. This opts into automatic Ready reporting.

```python
from cloudcoil.controller import Context, Controller, ReconcileStatus, Wait

class WidgetStatus(ReconcileStatus):
    ready_replicas: int = 0

# On Widget: status: WidgetStatus | None = None
widgets = Controller(Widget, owns=(ConfigMap, Deployment))

@widgets.stage(condition="ConfigurationReady")
async def configure(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_config(widget))

@widgets.stage(depends=configure, condition="DeploymentApplied")
async def deploy(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_deployment(widget))

@widgets.stage(depends=deploy, condition="WorkloadAvailable")
async def available(widget: Widget, ctx: Context[Widget]) -> None:
    assert widget.name is not None
    deployment = await ctx.get(Deployment, widget.name)
    if not rollout_complete(deployment):
        raise Wait("RollingOut", "Waiting for the current rollout", after=10)
```

The [Widget example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py)
includes the CRD, resource builders and admission handlers. Its readiness check
compares observed generation and updated/available replicas with current intent.
A live read after preceding writes avoids accepting an old cached rollout as Ready.

`depends=` accepts a registered function or a tuple of functions. A named stage
scope can also be referenced. Dependencies must establish a unique order; missing
references, cycles, repeated condition names and ambiguous order fail offline during
manifest generation or before workers start. Import order never resolves ties.
Execution is serial. A wait or error stops the pass, including later stages.

Every pass starts at the first stage, including after Ready and after restart.
Conditions record current observations; they are not checkpoints. Handlers must be
idempotent. A stage returns None or raises Wait; it does not implicitly save primary
spec/metadata mutations. Use explicit status helpers and owned-child operations.

## Cases within a stage

A stage can contain one handler or a case group:

```python
configuration = widgets.stage("configuration", condition="ConfigurationReady")

@configuration.case(when=is_suspended)
async def suspended(widget: Widget) -> None:
    raise Wait("Suspended", after=300)

@configuration.case(when=input_missing, after=suspended)
async def missing(widget: Widget) -> None:
    raise Wait("InputMissing", after=30)

@configuration.otherwise()
async def configure(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_config(widget))

@widgets.stage(depends=configuration, condition="DeploymentApplied")
async def deploy(widget: Widget, ctx: Context[Widget]) -> None:
    await ctx.ensure(desired_deployment(widget))
```

Use this configuration stage **instead of** the first sequence's configure stage.
Only the first matching case runs. `after=` orders predicate evaluation, not handler
execution. It accepts a function or tuple, and must establish a unique order. An
`otherwise()` fallback is mandatory. Predicates take `(resource)` or `(resource, ctx)`,
return bool synchronously, and must have no side effects. Errors in predicates retry
through the normal controller path; waiting never falls through to another case.

A selected case reports on its enclosing stage condition. For example, missing input
sets ConfigurationReady=False with reason InputMissing; successful configuration
sets it True with reason configure. Branch names never become separate conditions.
The [conditional configuration example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/conditional_config.py)
then runs a dependent checksum stage, including live reads and a reverse dependency watch.

## Root cases

The same `case()` and `otherwise()` decorators are available directly on a controller:

```python
configs = Controller(ApplicationConfig, owns=(ConfigMap,))

@configs.case(when=is_suspended)
async def suspended(config: ApplicationConfig) -> None:
    raise Wait("Suspended", after=300)

@configs.otherwise()
async def configure(config: ApplicationConfig, ctx: Context[ApplicationConfig]) -> None:
    await ctx.ensure(desired_config(config))
```

Root cases report through Ready. Each controller has exactly one entrypoint:
reconcile, stages, or root cases. Cases can nest within stages, but arbitrary recursive
workflows are not supported. For two simple guards, ordinary if statements in a
reconcile handler may be easier to read.

## Outcomes and retries

| Outcome | Behavior |
| --- | --- |
| Return normally | Stage succeeds; continue. A normal/root-case handler may return its primary resource or Result. |
| `raise Wait(reason, message, after=30)` | Pending, not failure. Stop, mark active condition False, later conditions Unknown and Ready False; schedule another pass. |
| Ordinary exception | Stop, report failure, retry with backoff and jitter. |
| `TerminalError(...)` | Report failure; no automatic error retry. A later input or resync can retry. |
| Reconciliation timeout | Report failure and retry. |
| Shutdown cancellation | Stop and propagate cancellation without a failure write. |

Wait defaults to 30 seconds and requires a finite positive delay. Watches can wake
work sooner. Errors use the existing 1-second base/60-second cap with jitter.
`@reconcile(every=60)` schedules drift repair after success; explicit Result timers,
waits and errors take precedence. No retry resumes halfway through a stage sequence.

## Status helpers

```python
ctx.set_status(ready_replicas=2, endpoint="https://example.com")
ctx.condition("DependenciesReady", False, reason="InputMissing")
```

Helpers validate the declared Pydantic model, accept field names and aliases, reject
typos and preserve unrelated fields. ReconcileStatus declares conditions as a CRD
map list keyed by type. `get_condition(obj, "Ready")` returns an independent copy.
Automatic conditions (Ready and stage conditions) are reserved: a Context cannot
also write those names. `report_status=False` disables automatic reporting;
`report_status=True` requires a ReconcileStatus subclass with defaultable fields.
Built-in resource statuses are not opted into automatic reporting by default.

Condition observedGeneration describes the primary generation examined.
lastTransitionTime changes only when True/False/Unknown changes. Reason, message and
generation changes preserve it. Stable observations skip status PATCHes.
Top-level observedGeneration means examined, not necessarily successfully completed.

Explicit status reports persist even when the handler returns None or fails. On
failure, partial primary spec/metadata edits are not saved. Child writes already
performed cannot be rolled back. Failure reports name the stage/exception class;
tracebacks stay in logs. Avoid secrets in explicit status and Event messages.

Returning a modified primary resource from a normal/root-case handler saves its
successful changes. Standalone update_status/set_condition helpers remain available
for local edits. Discovery routes status writes to the status subresource, with
UID/resourceVersion guards. A conflict retries the whole reconciliation. Failed
status persistence retries even when the original business error was terminal.

Controllers with automatic reporting ignore primary status-only watch changes by
default to keep their own reports from bypassing backoff. Other controllers still
receive status updates. Override with `status_updates=True/False`. Spec, metadata,
deletion, children, dependencies and unchanged-version resyncs remain inputs.

## Kubernetes Events

```python
ctx.event("BackupStarted", "Creating a backup")
ctx.event("ProviderUnavailable", "Will retry", type="Warning")
```

Context.event queues reporting without I/O. Events flush after status persistence,
with a bounded queue, recorder suppression/rate limits and a total flush time budget
(`event_flush_timeout=2` on Controller). Recorder timeout bounds each Event request;
the flush budget bounds the whole batch. Increase both explicitly for slower delivery.
They do not consume the handler deadline, and delivery failure does not retry
business operations. Status and Events are not an atomic transaction.

Events are enabled by default; Application grants create on events.k8s.io/events.
Set `events=False` to disable recording and its RBAC grant, or supply an EventRecorder.
Namespaced objects record in their namespace; cluster objects use the configured
recorder/application namespace. Repeated UID/reason/action combinations are suppressed.
Stage truth/reason transitions produce Normal Events; failures produce Warning Events.
Suppression is process-local, so restarts may duplicate Events. Events are diagnostics,
not durable work triggers or proof of exactly-once execution.

## Low-level compatibility

Existing Request callbacks, Stages/Stage/Cases constructors, returned Wait values,
Result and immediate `await request.event(...)` remain supported for embedding.
They retain their existing contracts; examples use the decorator API. Do not mix a
constructor reconciler with decorated reconciliation/finalizer handlers.
For external cleanup, prefer the [finalize decorator](controllers.md#finalizers).
