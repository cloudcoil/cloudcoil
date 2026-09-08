# Lifespans and leadership

Use `@app.lifespan()` for process resources such as shared connections. Use
`@app.lifespan(scope="leader")` for services that should run only while this replica
holds the controller Lease. For cleanup tied to a Kubernetes object's deletion,
use a [finalizer](controllers.md#finalizers).

## Register startup and cleanup together

A lifespan is an async generator: setup runs before `yield`, and cleanup belongs
in `finally` so it also runs when the application is cancelled. This complete
example logs both process and leadership transitions:

```python
import logging
from collections.abc import AsyncIterator

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.application import Application, LifecycleEvent, LifecycleType

logger = logging.getLogger(__name__)
app = Application("config-observer", leader_election=True)
configs = app.controller(ConfigMap, label_selector="example.com/observe=true")

@app.lifespan()
async def process(event: LifecycleEvent) -> AsyncIterator[None]:
    logger.info("Process starting")
    try:
        yield
    finally:
        logger.info("Process exiting: %s", event.type)

@app.lifespan(scope="leader")
async def leadership(event: LifecycleEvent) -> AsyncIterator[None]:
    logger.info("Leadership acquired: %s", event.identity)
    try:
        yield
    finally:
        if event.type == LifecycleType.LEADERSHIP_LOST:
            logger.warning("Leadership lost: %s", event.error)
        logger.info("Leader scope exiting: %s", event.type)

@configs.reconcile()
async def observe(config: ConfigMap) -> None:
    logger.info("Observed %s/%s", config.namespace, config.name)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.main()
```

A hook can take no arguments when it does not need an event. Each scope accepts
one hook; compose several connections with `async with` or `AsyncExitStack`
inside that hook. Do not add `@asynccontextmanager`: the application wraps the
generator. Setup must reach `yield` before dependent components start.

## Event contract

| Scope | Entry `event.type` | Exit `event.type` | Replicas |
| --- | --- | --- | --- |
| `process` (default) | `STARTUP` | `SHUTDOWN`, `FAILURE` or `LEADERSHIP_LOST` | Every running replica |
| `leader` | `LEADERSHIP_ACQUIRED` | `SHUTDOWN`, `LEADERSHIP_LOST` or `FAILURE` | The elected controller replica |

`event.scope` identifies the scope. The same event object's `type` and `error`
are updated before the yielded scope exits; read them inside cleanup instead of
saving the entry value. `error` is `None` for normal shutdown and carries the
exception for failure or leadership loss. `identity` identifies the election
participant for leader hooks; process hooks have no election identity.

Leader hooks require leader election and at least one controller. Standbys run
process hooks and serve admission, but do not enter leader hooks. Register hooks
before `run`; late registration fails. Manifest generation and installation do
not enter lifespans.

## Shutdown order

On normal stop, the runtime drains controller work within its shutdown budget,
then exits the leader hook and releases the Lease. Renewal continues during
normal draining and leader cleanup. Webhook requests and controllers finish
before the process hook closes its resources. Application-owned clients close
last; a caller-supplied Config remains the caller's responsibility.

On leadership loss, workers are cancelled and joined before leader cleanup.
Cleanup sees `LEADERSHIP_LOST`; lease release is attempted afterward with ownership
guards. Cleanup must tolerate already having lost ownership. Use it to stop local
services, not to delete shared state that a successor may be using.

Leadership loss ends this manager instance. It does not reacquire in-process;
restart the application to participate again. Other fatal component errors also
stop sibling components and propagate. Hook failures propagate rather than being
silently treated as successful shutdown.

Leases coordinate cooperative replicas; they cannot fence an external operation
that has already started. Keep handlers idempotent and cancellation-aware. See
[runtime election details](runtime.md#leader-election) for timing, permissions and
health behavior, and the [runnable lifespan pattern](https://github.com/cloudcoil/cloudcoil/blob/main/examples/patterns/lifespan.py).
