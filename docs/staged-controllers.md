# Stages, conditions and Events

Use an ordinary reconcile function for a small controller, `Stages` for ordered
prerequisites, and `Cases` for mutually exclusive branches. All use the existing
Controller, watches, clients, ownership checks and retry queue. Cases execute a
short ordered loop of ordinary Python functions; there is no code generation or DSL.

## Sequential stages

Give your custom resource a status derived from `ReconcileStatus`. Additional status
fields need defaults so an absent status can be initialized.

```python
class WidgetStatus(ReconcileStatus):
    ready_replicas: int = Field(default=0, alias="readyReplicas")

# On Widget: status: WidgetStatus | None = None

async def configure(request: Request[Widget]) -> None:
    await request.ensure(ConfigMap(data={"message": request.object.spec.message}))

async def available(request: Request[Widget]) -> Wait | None:
    ready = count_current_replicas(request)  # Your workload observation.
    request.set_status(ready_replicas=ready)
    if ready < request.object.spec.replicas:
        return Wait("RollingOut", f"{ready} replicas ready", requeue_after=10)

controller = Controller(
    Widget,
    Stages(
        Stage("ConfigurationReady", configure),
        Stage("WorkloadAvailable", available),
    ),
).owns(ConfigMap, Deployment)
```

Import `Controller, Request, ReconcileStatus, Stage, Stages, Wait` from
`cloudcoil.controller`. The complete
[Widget example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/widget_operator.py)
defines the CRD and ensures a ConfigMap, Deployment and Service. It reads the
Deployment live after writing, and checks updated/available replicas and observed
generation so an old cached rollout cannot make the new configuration look Ready.

| Handler outcome | Behavior |
| --- | --- |
| `None` | Mark this stage True and continue. |
| `Wait(reason, message, requeue_after=30)` | Stop; mark this stage False, later stages Unknown and Ready False; save and schedule another pass. |
| Exception | Stop, report failure status and retry with exponential backoff/jitter. |
| `TerminalError(...)` | Report failure; no automatic error retry. A later input/dependency event or resync can retry. |
| Timeout | Report failure and retry. Shutdown cancellation propagates without a failure write. |

Every pass starts at stage one, including after Ready and after a restart. Conditions
describe current observations; they are not checkpoints that skip drift repair.
Actions must be idempotent. Skipped downstream conditions become Unknown rather than
retaining stale success. `Ready` is reserved for the aggregate condition.

Missing/deleting primary objects do not enter stages. `request.object` provides the
non-optional resource, so every step need not repeat an absence guard. A stage returns
only None or Wait; successful primary edits are saved automatically. For resources
without a compatible status model use `Stages(..., report_status=False)`; it does not
inject custom status into built-in resources. Explicit Events remain available.

## First-match cases

```python
cases = Cases[Widget]()

@cases.case("Suspended", when=lambda req: req.object.spec.suspended, priority=100)
async def suspended(request: Request[Widget]) -> Wait:
    return Wait("Suspended", "Reconciliation is suspended", requeue_after=300)

@cases.case("DependencyMissing", when=dependency_missing, priority=50)
async def missing(request: Request[Widget]) -> Wait:
    return Wait("MissingDependency", "Waiting for configuration")

@cases.otherwise("Configured")
async def configure(request: Request[Widget]) -> None:
    await request.ensure(desired_child(request.object))

controller = Controller(Widget, cases).owns(ConfigMap)
```

The runnable [conditional config example](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/conditional_config.py)
includes its CRD and reverse dependency watch.

- Only the first matching action runs; waiting does not fall through.
- Predicates are synchronous, side-effect-free reads returning bool. Evaluation
  stops at the first match. Predicate errors use the same failure/retry path.
- Omit all priorities for registration order. Otherwise every case needs a distinct
  integer priority; higher runs first. Mixed/duplicate priorities are rejected.
  Pass a Cases instance to registration functions in other modules. Priorities
  order handlers, not arbitrary Python import side effects.
- The optional `otherwise` is always last. No match without a fallback raises
  TerminalError rather than silently reporting success.
- Duplicate names and registrations after startup fail explicitly. Cases report
  their outcome through Ready; branch labels do not become condition types.
  Success uses the case name as Ready's reason; Events retain it as their action.
- Normal Python `match` works in ordinary reconcilers too. The request status helpers
  and `return Wait(...)` do not require using Cases.

## Status helpers

```python
request.set_status(ready_replicas=2, endpoint="https://example.com")
request.condition("Ready", True, reason="Available", message="Serving", event=True)
```

Helpers validate the declared Pydantic status model, accept Python names/wire aliases,
reject typos and preserve unrelated fields and condition types. ReconcileStatus
declares conditions as a CRD map list keyed by type. `get_condition(obj, "Ready")`
returns an independent copy.

Condition observedGeneration comes from the primary snapshot. lastTransitionTime
changes only when True/False/Unknown changes; reason/message/generation changes
preserve it. Stable observations produce no status PATCH. Top-level
observedGeneration means the generation examined, not successful completion: check
Ready and its generation for readiness.

Request helpers explicitly opt into automatic status saving even when the handler
returns None or raises. On failure, only reported status is saved, never half-edited
spec/metadata. Automatic failure messages name the stage and exception class;
tracebacks stay in the existing logs. Do not put credentials or raw sensitive
provider responses in your explicit status or Event messages.

Standalone `update_status(obj, **fields)` and `set_condition(obj, ...)` perform
local edits and return the resource; return it from an ordinary reconciler to save.
These functions do not opt into automatic failure persistence.

UID/resourceVersion guards and status-subresource discovery are retained. Conflicts
retry reconciliation from fresh state. If failure reporting itself fails, even a
terminal business error retries. Successful transition Events flush after status
persistence; status and Events are not an atomic transaction.

For an immediate status write use existing `mutate(obj, callback, status=True)`.
Do not combine explicit primary writes with returned-primary/request-helper writes
against the old snapshot in the same attempt.

## Kubernetes Events

```python
await request.event("BackupStarted", "Creating a backup")
await request.event("ProviderUnavailable", "Will retry", type="Warning")
```

Controllers record Events by default and Application grants create on
events.k8s.io/events. `events=False` disables recording and its generated grant.
Customize with `events=EventRecorder("example.com/widgets", interval=60, max_keys=1024)`.

Namespaced objects record in their namespace. Cluster-scoped objects use the Config
namespace, or the recorder's explicit namespace. Match your runtime Config namespace
to your generated application namespace.

Stage truth/reason transitions produce Normal Events; failures produce Warning
Events. Message/generation-only changes do not emit transition Events. Repeated
UID/reason/action combinations are suppressed even if messages change. Memory,
traffic and delivery time are bounded. Suppression is process-local, not durable;
restarts may duplicate Events. Repeats are suppressed rather than aggregated into
Event series counts.

`request.event` returns True on delivery, False on suppression, disabled recording,
absent identity or delivery failure. API/transport failures log without triggering
business retries. Automatic Event delivery runs outside the reconciliation deadline
and cannot turn a successful write into failure. Explicit awaited calls still
consume callback time. Cancellation propagates. Events are diagnostics, not work
triggers, an audit log, or proof of exactly-once execution.

## Watches, retries and lifecycle

Staged controllers ignore primary status-only changes by default so their own failure
status cannot bypass retry backoff. Spec, labels, annotations, deletion and finalizers
remain inputs; child/dependency watches and same-version resyncs still run. Ordinary
reconcilers continue receiving all updates by default. Override with
`Controller(..., status_updates=True/False)`. Enable status inputs if another writer
maintains primary status your controller depends on; keep your reports stable.

Wait defaults to a positive 30-second timer, avoiding silent stalls on unwatched
dependencies. Declare owns/watch for timely progress. Errors retain the existing
1-second base, 60-second cap and jitter; meaningful new events supersede timers.

Stages skip deletion. Keep the existing
[finalizer pattern](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/finalizers.py)
for external resources: persist the finalizer before provisioning, recheck deletion
using the returned live object, perform idempotent cleanup, then remove the finalizer.
Neither a condition nor cache absence replaces these ordering requirements. A wrapper
that invokes Stages after handling finalizers must set status_updates=False explicitly
if it wants the staged update filter.
On a pass that explicitly writes a primary finalizer, return a scheduling-only
Result and enter stages on a later fresh pass; do not save staged status against
the snapshot from before that finalizer write.

Other patterns remain focused: dependency rollout stays a function, workload summary
uses status helpers, child-set pruning retains ownership guards, and multiple
controllers share Application. Admission keeps its separate request/response
lifecycle and does not run reconciliation stages or side effects.
