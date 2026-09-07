# Logs


Read or follow a Pod or workload with the same interface:

```python
from cloudcoil import logs

print(logs.read("deployment/worker", namespace="jobs", tail_lines=50))
with logs.stream("deployment/worker", namespace="jobs") as records:
    for record in records:
        print(record.pod, record.container, record.message)
```

These built-in workload objects work too, including metadata-only references:

| Resource | String target (singular/plural also accepted) |
| --- | --- |
| Deployment | `deploy/worker` |
| ReplicaSet | `rs/worker` |
| StatefulSet | `sts/database` |
| DaemonSet | `ds/agent` |
| Job | `job/migration` |
| CronJob | `cj/nightly` |
| ReplicationController | `rc/worker` |

A workload selects
one Pod, preferring non-terminating, running, ready Pods, then breaking ties by name.
Container selection uses that Pod's default-container annotation or sole regular
container; otherwise specify `container=`. Selection considers every list page.

To combine discovery and streaming across **all matching Pods** of any supported workload,
use the async helper:

```python
from cloudcoil import logs

async def follow_workers():
    async with logs.async_stream(
        "deployment/worker", namespace="jobs", all_pods=True,
        tail_lines=100, match=logs.LogFilter(contains="error", ignore_case=True),
    ) as records:
        async for record in records:
            print(record.pod, record.container, record.message)
```

`all_pods=True` selects one container per Pod, or the named `container=` on Pods that
contain it. Records arrive as each stream produces them, preserving order within each
source, with no global timestamp sort. `max_streams=10` bounds concurrent requests and
tasks; buffering is bounded too. Following more sources than this limit raises before
opening any log streams: increase the limit explicitly. With `follow=False`, larger
selections are processed in batches. A source error propagates and closes the other
streams; exiting the block, a failing filter, and cancellation also close all responses.

For more control, `logs.discover("deployment/worker", namespace="jobs")` (or a Deployment
object) returns containers across its matching Pods for use with `read()` / `stream()`.
Discovery uses the full `spec.selector`, including `matchExpressions`, and ANDs any
additional `label_selector=` for built-in workloads; it does not guess from workload metadata
or template labels. ReplicationControllers use their flat label maps. Job references fetch
the server-generated selector when it is missing. Empty selectors are rejected. Workload
discovery requires Pod-list permission, and a name or metadata-only reference also requires
permission to get that workload. Log reads additionally require `pods/log`.
An empty workload returns no discovered sources;
read/stream raise `ResourceNotFound` if no Pods match. Built-in workload selectors retain
Kubernetes label-selector semantics.

**Custom resources:** pass a generated `Resource` instance or `Unstructured` object.
If its `spec.selector` describes its Pods, both the standard `matchLabels`/`matchExpressions`
shape and a flat label map work automatically. This is a convention, not a universal CRD
guarantee: some operators use selectors for other resources. If the selector is absent or
has another shape, discovery automatically traverses `ownerReferences` back from Pods.
This supports chains such as custom resource → StatefulSet → Pod, as well as CronJob →
Job → Pod. Pass a fetched resource with `metadata.uid` so ownership can be matched to
the exact object; names alone are insufficient when an object has been recreated.

Supply `label_selector=` to explicitly define the Pod association when the convention
does not apply or the operator does not set ownership links. For custom
resources this replaces the convention; for built-in workloads it narrows their selector.
It works on `discover`, `read`, `stream`, and their async equivalents:

```python
from cloudcoil import logs
from cloudcoil.resources import Resource

async def follow_custom_resource(resource: Resource, pod_labels: str):
    async with logs.async_stream(
        resource, label_selector=pod_labels, all_pods=True, tail_lines=100
    ) as records:
        async for record in records:
            print(record.pod, record.container, record.message)
```

Use the operator's actual Pod labels. Custom kinds do not have string shortcuts or an
automatic resource GET; the supplied object provides its selector and namespace. Use
`namespace=` to select the Pod namespace for cluster-scoped or cross-namespace operators.
The ownership fallback lists Pods in the selected namespace, then reads only referenced
ancestors, caching lookups for that discovery call. It requests metadata where supported
and uses API discovery for unfamiliar owner kinds. It respects namespaced/cluster-scoped
ownership rules, skips deleted/recreated ancestors, and stops cycles. It requires permission
to read intermediate owners and their API discovery endpoints; permission errors propagate
instead of producing a silently incomplete result. Use `label_selector=` if those reads
are unavailable. Resources without selectors or ownership links still need explicit Pod labels.

Discover containers by Kubernetes selectors, then filter their log records:

```python
from cloudcoil import logs

errors = logs.LogFilter(regex=r"error|exception", ignore_case=True)
for source in logs.discover(all_namespaces=True, label_selector="app=worker"):
    # Sources include regular, init, and ephemeral containers. Select before reading.
    if source.container_type != "regular":
        continue
    with logs.stream(source, follow=False, tail_lines=100, timestamps=True, match=errors) as records:
        for record in records:
            print(record.namespace, record.pod, record.container, record.message)
```

`discover()` uses the active namespace by default and follows every list page. It returns
metadata without downloading logs: labels, pod UID, owner references, node, phase,
container type/state, and restart count. Selectors run on the server; `container="app"`
selects an exact container name. A discovered source retains its configuration so it can
be passed directly to `read()` or `stream()` outside the original context. Discovery is
a snapshot of potential sources; a waiting container may not have logs, and discovery
permissions do not imply permission to read them. API errors propagate to the caller.

```python
# Read text with original line endings, or follow structured records.
print(logs.read("worker", namespace="jobs", tail_lines=50))
with logs.stream("worker", namespace="jobs", match=logs.LogFilter(contains="failed")) as records:
    for record in records:
        print(record.timestamp, record.message)

# The same operations are available asynchronously.
async for source in logs.async_discover(label_selector="app=worker", container="app"):
    async with logs.async_stream(source, follow=False, match=errors) as records:
        async for record in records:
            print(record.pod, record.message)
```

A supplied Pod provides its namespace, labels, and sole regular container (or the valid
`kubectl.kubernetes.io/default-container` annotation). Ambiguous Pods require `container=`.
A pod name alone needs only log-read permissions and leaves container selection to the
server; labels and the selected container may then be unknown. Records expose `raw`,
`message`, `timestamp`, `pod`, `namespace`, `container`, `previous`, `labels`, and, when discovered,
`source`. Metadata is a snapshot; timestamps preserve nanosecond precision as strings.
Use `match=lambda record: ...` for custom text or metadata filtering.

`stream()` follows by default and requests timestamps; `follow=False` reads a finite
snapshot and defaults timestamps off. Both accept `timestamps=` explicitly. Always use
`with` / `async with` so breaking, errors, and cancellation close the HTTP response.
Following disables only the response read timeout. Deployment membership and source
metadata are snapshots: streams do not reconnect, switch Pods, or discover new replicas
during a rollout. For manually discovered live sources, run async consumers concurrently
under your own concurrency limit; a sequential follow loop stays on its first live source.

All operations reuse the active configuration's authenticated HTTP client, or accept
`config=` explicitly. Reusable `LogOptions` and typed keywords support `previous`,
`tail_lines`, `since_seconds` **or** timezone-aware `since_time`, and `limit_bytes`.
Direct keywords override options. Time/tail/byte limits apply on the server before
client-side matching; byte limits may truncate a line. Kubernetes log access cannot
recover deleted Pods or logs that the node has already rotated away.
