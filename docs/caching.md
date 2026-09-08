# Client caching and informers

For controller and admission callbacks, start with [explicit informer reads](reads.md).
This page covers cached clients and direct subscriptions outside the operator runtime.

## Cached resource methods

```python
from cloudcoil.caching import Cache
from cloudcoil.client import Config
from cloudcoil.models.kubernetes.core.v1 import Pod

config = Config(
    namespace="default",
    cache=Cache(
        resources=[Pod],
        namespaces=["default"],
        mode="strict",
        wait_for_sync=True,
        max_items_per_resource=0,
    ),
)

async def read_pods():
    async with config:
        return await Pod.async_list(namespace="default")
```

The context manages the cache lifecycle. Nested scopes share it until the last
scope exits; use separate Config instances for synchronous and asynchronous scopes.
`with config:` and `Pod.list(...)` provide the synchronous equivalent.

`mode="strict"` requires cache-backed reads. `mode="fallback"` allows API reads when
the cache cannot serve a request. Neither mode makes cached data strongly consistent.
Writes go to the API server; watches subsequently update cached state. Explicit live
clients use `await Pod.async_client(config, cached=False)`.

## Configuration

| Option | Meaning |
| --- | --- |
| `resources=[Pod, ...]` | Preconfigure informer kinds before startup |
| `namespaces=["default"]` | Watch one namespace; `None` watches all namespaces |
| `label_selector`, `field_selector` | Restrict the watch using server selectors |
| `resync_period` | Periodically relist resources |
| `wait_for_sync`, `sync_timeout` | Wait for initial snapshots and bound that wait |
| `max_items_per_resource` | Capacity per informer; `0` disables eviction |
| `per_resource` | Resource-specific selectors, resync and capacity |

The cache supports one namespace or all namespaces, not a disjoint namespace list.
A selector or capacity limit can exclude objects; an empty result is not proof of
cluster-wide absence. Use [live reads](reads.md) where that distinction matters.

`config.cache.status()` reports readiness and counts. `with config.cache.pause():`
temporarily bypasses caching. `strict_mode()` and `fallback_mode()` temporarily
change the read policy and restore it on exit.

## Direct subscriptions

Register handlers before entering the context so they receive initial objects:

```python
import asyncio
from cloudcoil.caching import Cache
from cloudcoil.client import Config
from cloudcoil.models.kubernetes.core.v1 import Pod

async def monitor(stop: asyncio.Event) -> None:
    config = Config(cache=Cache(resources=[Pod], wait_for_sync=True))
    await config.async_initialize()
    informer = config.cache.get_informer(Pod, sync=False)

    @informer.on_add
    def added(pod):
        print("Added", pod.namespace, pod.name)

    @informer.on_update
    def updated(old, new):
        print("Updated", new.namespace, new.name)

    @informer.on_delete
    def deleted(pod):
        print("Deleted", pod.namespace, pod.name)

    async with config:
        # Async informer storage is local: get/list are synchronous.
        print(len(informer.list()))
        await stop.wait()
```

Async informers accept sync or async callbacks. For synchronous applications, use
`get_informer(Pod, sync=True)` and register synchronous handlers before `with config:`.
Direct informer objects are lower-level cache views; copy returned resources before
editing. Controller `ctx.cached(...)` and admission `request.cached(...)` return deep copies.
Use controllers when you need retry queues and reconciliation rather than raw events.
