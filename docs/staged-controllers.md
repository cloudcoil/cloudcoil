# Stages, cases and reporting

Use one `@controller.reconcile()` function for ordinary Python control flow. Add
stages when separate progress conditions help explain the work. Add cases when
exactly one alternative should run. A stage can contain cases; there is no separate
step abstraction or persistent workflow checkpoint.

## Sequential stages

This complete operator turns a Settings object into an owned ConfigMap, then
reports the checksum of the configuration it reads back:

```python
import hashlib
import json

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.application import Application
from cloudcoil.controller import Context, ReconcileStatus, Wait
from cloudcoil.crd import custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

class SettingsSpec(BaseModel):
    message: str
    suspended: bool = False

class SettingsStatus(ReconcileStatus):
    checksum: str = ""

@custom_resource(api_version="examples.cloudcoil.dev/v1", plural="settings")
class Settings(Resource):
    spec: SettingsSpec
    status: SettingsStatus | None = None

app = Application("settings")
settings = app.controller(Settings, owns=(ConfigMap,))

@settings.stage(condition="ConfigurationReady")
async def configure(obj: Settings, ctx: Context[Settings]) -> None:
    if obj.spec.suspended:
        raise Wait("Suspended", after=300)
    await ctx.ensure(ConfigMap(data={"message": obj.spec.message}))

@settings.stage(depends=configure, condition="ChecksumReady")
async def checksum(obj: Settings, ctx: Context[Settings]) -> None:
    assert obj.name is not None
    config = await ctx.get(ConfigMap, obj.name)
    value = json.dumps(config.data or {}, sort_keys=True).encode()
    ctx.set_status(checksum=hashlib.sha256(value).hexdigest())

if __name__ == "__main__":
    app.main()
```

Save as `app.py`. `python app.py install` installs its CRD and RBAC;
`python app.py run` runs locally. Create a Settings object with
`spec: {message: hello}` to observe ConfigurationReady, ChecksumReady and Ready
conditions. See [deployment](operators.md) to run it in a Pod.

`ReconcileStatus` opts the resource into automatic conditions. Additional status
fields need defaults. `ctx.ensure` defaults the child name, namespace and owner
from the primary. The next stage reads live because an informer may not yet have
observed the preceding write.

`depends=` accepts a registered function, a named stage scope or a tuple of either.
The dependencies must establish one unique order. Missing references, cycles,
repeated condition names and ties fail during offline validation or before workers
start. Import order never resolves a tie. Stages run serially; waiting or failing
stops the pass before any later stage.

Every pass starts at the first stage, including after success and after restart.
Conditions record observations, not completed-once checkpoints. Handlers must be
idempotent. A stage returns `None` or raises `Wait`; it uses explicit status helpers
and child operations rather than returning primary spec/metadata edits.

## Cases within a stage

For a longer set of alternatives, replace the `configure` stage above with a named
scope. Keep the same resource definitions and change the checksum dependency to
`depends=configuration`:

```python
configuration = settings.stage("configuration", condition="ConfigurationReady")

@configuration.case(when=lambda obj: obj.spec.suspended)
async def suspended(obj: Settings) -> None:
    raise Wait("Suspended", after=300)

@configuration.case(when=lambda obj: not obj.spec.message.strip(), after=suspended)
async def missing_message(obj: Settings) -> None:
    raise Wait("InputMissing", "Set spec.message to non-empty text", after=30)

@configuration.otherwise()
async def configure(obj: Settings, ctx: Context[Settings]) -> None:
    await ctx.ensure(ConfigMap(data={"message": obj.spec.message}))
```

`after=` orders predicate evaluation. It accepts a case function or tuple and must
establish a unique order. Predicates take `(resource)` or `(resource, ctx)`, return
`bool` synchronously and have no side effects. Use a named predicate when that is
clearer than a lambda. Predicate exceptions retry like handler exceptions.

Only the first match runs. `@otherwise()` is required and runs when no case matches.
Waiting does not fall through. In this example a blank message reports
ConfigurationReady=False with reason InputMissing; successful configuration reports
ConfigurationReady=True. Branches do not create their own conditions.

A stage accepts either a handler or cases. Register this alternative instead of the
original configure stage; registering both would duplicate ConfigurationReady.
The [conditional configuration pattern](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/conditional_config.py)
shows this structure with dependency watches and a following checksum stage.

## Root cases

A controller can select a single branch without introducing stages. Using the same
Settings model, an alternative controller definition is:

```python
from cloudcoil.controller import Controller

settings = Controller(Settings, owns=(ConfigMap,))

@settings.case(when=lambda obj: obj.spec.suspended)
async def suspended(obj: Settings) -> None:
    raise Wait("Suspended", after=300)

@settings.otherwise()
async def configure(obj: Settings, ctx: Context[Settings]) -> None:
    await ctx.ensure(ConfigMap(data={"message": obj.spec.message}))
```

Include this group with `app.include(settings)` instead of the staged controller.
Root cases report through Ready. A controller has exactly one entrypoint:
reconcile, stages or root cases. Cases can live inside stages; they cannot recursively
contain stages or more cases. For a simple guard, an `if` inside reconcile is often
more readable.

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
ctx.set_status(checksum="observed-checksum")
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

## Explicit low-level APIs

`Request`, `Stages`, `Stage`, `Cases`, returned `Wait` values and immediate
`await request.event(...)` remain available for embedding. Their contracts differ
from queued Context reports; see [runtime and explicit writes](runtime.md#low-level-embedding)
and the [API reference](api.md). Use one registration style per controller.
