"""Read and follow pod logs using the active Config's authenticated HTTP clients."""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Self, TypedDict, Unpack

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cloudcoil._context import context
from cloudcoil._log_owners import OwnerTraversal
from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status
from cloudcoil.errors import ResourceNotFound
from cloudcoil.resources import Resource

logger = logging.getLogger(__name__)

# The API server negotiates a Kubernetes serializer before returning the raw log
# stream. A text/plain-only Accept is rejected with 406, even though logs are text.
_LOG_HEADERS = {"Accept": "*/*"}
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_DNS_SUBDOMAIN = rf"{_DNS_LABEL}(?:\.{_DNS_LABEL})*"


class LogParameters(TypedDict, total=False):
    """IDE-visible keyword options accepted by all log operations."""

    container: str | None
    previous: bool
    timestamps: bool
    tail_lines: int | None
    since_seconds: int | None
    since_time: datetime | None
    limit_bytes: int | None


class LogOptions(BaseModel):
    """Reusable validated log filters; direct keyword arguments override these values."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    container: str | None = Field(default=None, min_length=1)
    previous: bool = False
    timestamps: bool = False
    tail_lines: int | None = Field(default=None, ge=0, serialization_alias="tailLines")
    since_seconds: int | None = Field(default=None, gt=0, serialization_alias="sinceSeconds")
    since_time: AwareDatetime | None = Field(default=None, serialization_alias="sinceTime")
    limit_bytes: int | None = Field(default=None, gt=0, serialization_alias="limitBytes")

    @model_validator(mode="after")
    def check_time_filters(self) -> Self:
        if self.since_seconds is not None and self.since_time is not None:
            raise ValueError("Specify only one of since_seconds and since_time")
        return self


@dataclass(frozen=True, slots=True)
class LogSource:
    """A discovered container, with an immutable snapshot of its Pod metadata.

    Discovery identifies potential log sources, not a guarantee that logs are retained
    or that the caller has pods/log permission. Sources retain their discovery Config.
    """

    pod: str
    namespace: str
    container: str
    container_type: Literal["regular", "init", "ephemeral"]
    labels: Mapping[str, str]
    pod_uid: str | None
    owners: tuple[tuple[str, str], ...]
    node: str | None
    phase: str | None
    restart_count: int
    state: Literal["waiting", "running", "terminated"] | None
    _config: Config = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class LogFilter:
    """Client-side line filtering. All supplied conditions must match.

    Metadata filtering can use a predicate, e.g. match=lambda r: r.container == "app".
    Kubernetes label_selector and field_selector filter Pods before fetching logs.
    """

    contains: str | None = None
    regex: str | None = None
    ignore_case: bool = False
    _pattern: re.Pattern[str] | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_pattern",
            re.compile(self.regex, re.IGNORECASE if self.ignore_case else 0)
            if self.regex is not None
            else None,
        )

    def __call__(self, record: LogRecord) -> bool:
        message = record.message.casefold() if self.ignore_case else record.message
        needle = (
            self.contains.casefold()
            if self.contains is not None and self.ignore_case
            else self.contains
        )
        return (needle is None or needle in message) and (
            self._pattern is None or self._pattern.search(record.message) is not None
        )


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One log line with source metadata. Timestamp preserves RFC3339 nanosecond precision.

    labels is None when no Pod metadata was supplied; container may be None when the
    API server selected it. raw preserves the text excluding the line terminator.
    """

    message: str
    raw: str
    pod: str
    namespace: str
    container: str | None
    timestamp: str | None
    labels: Mapping[str, str] | None
    source: LogSource | None = None
    previous: bool = False

    def __str__(self) -> str:
        return self.raw


@dataclass(frozen=True)
class _Request:
    config: Config
    pod: str
    namespace: str
    options: LogOptions
    labels: Mapping[str, str] | None
    source: LogSource | None = None

    @property
    def url(self) -> str:
        return f"/api/v1/namespaces/{self.namespace}/pods/{self.pod}/log"

    def params(self, follow: bool) -> dict:
        return {
            **self.options.model_dump(mode="json", by_alias=True, exclude_none=True),
            "follow": follow,
        }

    def record(self, raw: str) -> LogRecord:
        timestamp, message = None, raw
        if self.options.timestamps:
            candidate, separator, remainder = raw.partition(" ")
            if separator:
                try:
                    parsed = datetime.fromisoformat(candidate)
                except ValueError:
                    pass
                else:
                    if parsed.tzinfo is not None:
                        timestamp, message = candidate, remainder
        return LogRecord(
            message,
            raw,
            self.pod,
            self.namespace,
            self.options.container,
            timestamp,
            self.labels,
            self.source,
            self.options.previous,
        )


def _options(options: LogOptions | None, overrides: LogParameters, follow: bool) -> LogOptions:
    values: dict[str, Any] = {"timestamps": follow}
    if options is not None:
        values.update(options.model_dump(exclude_unset=True))
    values.update(overrides)
    return LogOptions.model_validate(values)


def _container_names(data: dict[str, Any]) -> list[str]:
    spec = data.get("spec") or {}
    return [
        item["name"]
        for key in ("containers", "initContainers", "ephemeralContainers")
        for item in spec.get(key, [])
    ]


def _container(data: dict[str, Any], explicit: str | None) -> str | None:
    containers = _container_names(data)
    if explicit is not None:
        if containers and explicit not in containers:
            raise ValueError(f"Unknown container {explicit!r}; choose from {containers}")
        return explicit
    default = (data.get("metadata", {}).get("annotations") or {}).get(
        "kubectl.kubernetes.io/default-container"
    )
    if default and default in containers:
        return default
    regular = [item["name"] for item in (data.get("spec") or {}).get("containers", [])]
    if len(regular) == 1:
        return regular[0]
    if len(regular) > 1:
        raise ValueError(f"Specify container for multi-container pod; choose from {containers}")
    return None


def _name(name: str | None, kind: str) -> str:
    if not name or len(name) > 253 or not re.fullmatch(_DNS_SUBDOMAIN, name):
        raise ValueError(f"A valid {kind} name is required")
    return name


def _request(
    pod: str | Resource | LogSource,
    namespace: str | None,
    config: Config | None,
    options: LogOptions | None,
    overrides: LogParameters,
    *,
    follow: bool,
) -> _Request:
    settings = _options(options, overrides, follow)
    name: str | None
    labels: Mapping[str, str] | None = None
    source = pod if isinstance(pod, LogSource) else None
    if isinstance(pod, LogSource):
        if namespace is not None and namespace != pod.namespace:
            raise ValueError("A discovered source cannot be moved to another namespace")
        if settings.container is not None and settings.container != pod.container:
            raise ValueError("A discovered source cannot select a different container")
        name, namespace, labels = pod.pod, pod.namespace, pod.labels
        config = config if config is not None else pod._config
        settings = settings.model_copy(update={"container": pod.container})
    elif isinstance(pod, Resource):
        if pod.api_version != "v1" or pod.kind != "Pod":
            raise ValueError("Logs require a v1 Pod resource")
        name = pod.name
        namespace = namespace if namespace is not None else pod.namespace
        labels = MappingProxyType(dict(pod.metadata.labels or {})) if pod.metadata else None
        settings = settings.model_copy(
            update={
                "container": _container(
                    pod.model_dump(by_alias=True, exclude_none=True), settings.container
                )
            }
        )
    else:
        name = pod
        if name.startswith(("pod/", "pods/")):
            name = name.split("/", 1)[1]
    name = _name(name, "pod")
    config = config if config is not None else context.active_config
    namespace = _namespace(config, namespace)
    logger.debug("%s logs for %s/%s", "Following" if follow else "Reading", namespace, name)
    return _Request(config, name, namespace, settings, labels, source)


def _namespace(config: Config, namespace: str | None) -> str:
    namespace = config.namespace if namespace is None else namespace
    if (
        not namespace
        or len(namespace) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", namespace)
    ):
        raise ValueError("A valid namespace is required")
    return namespace


def _timeout(client: httpx.Client | httpx.AsyncClient) -> httpx.Timeout:
    timeout = httpx.Timeout(client.timeout)
    timeout.read = None  # Quiet containers may produce no log output for hours.
    return timeout


# Canonical API identity, REST plural, and familiar kubectl short name. No generated
# model dependency is needed for either built-ins or custom Resource instances.
_WORKLOADS = {
    ("apps/v1", "Deployment"): ("deployments", "deploy"),
    ("apps/v1", "ReplicaSet"): ("replicasets", "rs"),
    ("apps/v1", "StatefulSet"): ("statefulsets", "sts"),
    ("apps/v1", "DaemonSet"): ("daemonsets", "ds"),
    ("batch/v1", "Job"): ("jobs", "job"),
    ("batch/v1", "CronJob"): ("cronjobs", "cj"),
    ("v1", "ReplicationController"): ("replicationcontrollers", "rc"),
}
_WORKLOAD_NAMES = {
    alias: (api_version, kind, plural)
    for (api_version, kind), (plural, short) in _WORKLOADS.items()
    for alias in (kind.lower(), plural, short)
}


@dataclass(frozen=True)
class _Workload:
    name: str
    namespace: str
    config: Config
    kind: str
    api_version: str
    plural: str | None
    data: dict[str, Any] | None

    @property
    def has_selector(self) -> bool:
        return self.plural is not None and not (
            self.api_version == "batch/v1" and self.kind == "CronJob"
        )

    @property
    def url(self) -> str:
        prefix = (
            f"/apis/{self.api_version}" if "/" in self.api_version else f"/api/{self.api_version}"
        )
        return f"{prefix}/namespaces/{self.namespace}/{self.plural}/{self.name}"


def _workload(
    target: str | Resource | LogSource,
    namespace: str | None,
    config: Config | None,
) -> _Workload | None:
    data = None
    if isinstance(target, Resource):
        if target.kind == "Pod" and target.api_version == "v1":
            return None
        kind, api_version = target.kind, target.api_version
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(api_version, str)
            or not api_version
        ):
            raise ValueError("A workload resource needs kind and apiVersion")
        name = target.name
        if not name:
            raise ValueError("A workload name is required")
        namespace = namespace if namespace is not None else target.namespace
        data = target.model_dump(by_alias=True, exclude_none=True)
        entry = _WORKLOADS.get((api_version, kind))
        plural = entry[0] if entry else None
        if plural is not None:
            name = _name(name, "workload")
        if plural is not None and (
            "spec" not in data
            or (kind == "Job" and not (data.get("spec") or {}).get("selector"))
            or (kind == "CronJob" and not data.get("metadata", {}).get("uid"))
        ):
            data = None  # A metadata-only built-in workload is a reference to fetch.
    elif isinstance(target, str) and target.partition("/")[0] in _WORKLOAD_NAMES:
        alias, separator, name = target.partition("/")
        if not separator:
            return None  # A bare name still refers to a Pod.
        api_version, kind, plural = _WORKLOAD_NAMES[alias]
        name = _name(name, "workload")
    else:
        return None
    config = config if config is not None else context.active_config
    return _Workload(name, _namespace(config, namespace), config, kind, api_version, plural, data)


def _selector(selector: dict[str, Any]) -> str:
    """Serialize the full LabelSelector, never broadening a malformed selector."""
    parts = []

    def label(value: object, *, key: bool = False) -> str:
        if not isinstance(value, str):
            raise ValueError("Pod selector keys and values must be strings")
        name = value
        if key and "/" in value:
            prefix, name = value.split("/", 1)
            if len(prefix) > 253 or not re.fullmatch(_DNS_SUBDOMAIN, prefix):
                raise ValueError(f"Invalid Pod selector key: {value!r}")
        if (
            len(name) > 63
            or (key and not name)
            or (name and not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9_.-]*[a-zA-Z0-9])?", name))
        ):
            raise ValueError(f"Invalid Pod selector label: {value!r}")
        return value

    labels = selector.get("matchLabels", {})
    expressions = selector.get("matchExpressions", [])
    labels = {} if labels is None else labels
    expressions = [] if expressions is None else expressions
    if not isinstance(labels, dict) or not isinstance(expressions, list):
        raise ValueError("Invalid Pod selector: expected matchLabels map and matchExpressions list")
    for key, value in labels.items():
        parts.append(f"{label(key, key=True)}={label(value)}")
    parts.sort()
    for expression in expressions:
        if not isinstance(expression, dict):
            raise ValueError("Invalid Pod selector expression: expected a mapping")
        key = label(expression.get("key"), key=True)
        operator, values = expression.get("operator"), expression.get("values", [])
        values = [] if values is None else values
        if not isinstance(values, list):
            raise ValueError("Pod selector expression values must be a list")
        if operator in ("In", "NotIn") and values:
            op = "in" if operator == "In" else "notin"
            parts.append(f"{key} {op} ({','.join(sorted(label(value) for value in values))})")
        elif operator in ("Exists", "DoesNotExist") and not values:
            parts.append(key if operator == "Exists" else f"!{key}")
        else:
            raise ValueError(f"Invalid Pod selector expression: {expression}")
    if not parts:
        raise ValueError("Pod selector must not be empty")
    return ",".join(parts)


def _workload_params(
    workload: _Workload,
    data: dict[str, Any],
    label_selector: str | None,
    field_selector: str | None,
    page_size: int,
) -> tuple[Config, str, dict[str, str | int]]:
    spec = data.get("spec") or {}
    raw = spec.get("selector") if isinstance(spec, dict) else None
    builtin = workload.has_selector
    if not builtin and label_selector is not None:
        if not label_selector.strip(" \t\r\n,"):
            raise ValueError("label_selector must not be empty for a custom resource")
        selector = ""
    elif not builtin and not raw:
        raise ValueError(
            f"{workload.kind} has no non-empty spec.selector; provide label_selector= "
            "with the labels of its Pods"
        )
    else:
        if not isinstance(raw, dict):
            raise ValueError("spec.selector must be a Pod label selector mapping")
        # ReplicationController and some operators use a flat label map. Other
        # built-ins use metav1.LabelSelector, including matchExpressions.
        flat = workload.kind == "ReplicationController" and workload.api_version == "v1"
        if not builtin and raw and all(isinstance(value, str) for value in raw.values()):
            flat = True
        if flat:
            raw = {"matchLabels": raw}
        elif raw.keys() - {"matchLabels", "matchExpressions"}:
            raise ValueError(
                "Unsupported spec.selector shape; use Pod discovery with label_selector="
            )
        selector = _selector(raw)
    if label_selector:
        selector = f"{selector},{label_selector}" if selector else label_selector
    return _discovery_request(
        workload.config, workload.namespace, False, selector, field_selector, page_size
    )


def _workload_query(
    workload: _Workload,
    label_selector: str | None = None,
    field_selector: str | None = None,
    page_size: int = 500,
) -> tuple[Config, str, dict[str, str | int], OwnerTraversal | None]:
    data = workload.data
    if data is None:
        response = workload.config.client.get(workload.url)
        raise_for_status(response)
        data = response.json()
    return _workload_pod_query(workload, data, label_selector, field_selector, page_size)


async def _async_workload_query(
    workload: _Workload,
    label_selector: str | None = None,
    field_selector: str | None = None,
    page_size: int = 500,
) -> tuple[Config, str, dict[str, str | int], OwnerTraversal | None]:
    data = workload.data
    if data is None:
        response = await workload.config.async_client.get(workload.url)
        raise_for_status(response)
        data = response.json()
    return _workload_pod_query(workload, data, label_selector, field_selector, page_size)


def _workload_pod_query(
    workload: _Workload,
    data: dict[str, Any],
    label_selector: str | None,
    field_selector: str | None,
    page_size: int,
) -> tuple[Config, str, dict[str, str | int], OwnerTraversal | None]:
    try:
        query = _workload_params(workload, data, label_selector, field_selector, page_size)
    except ValueError:
        if workload.has_selector or label_selector is not None:
            raise
        ownership = OwnerTraversal(workload.config, data)
        query = _discovery_request(
            workload.config, workload.namespace, False, None, field_selector, page_size
        )
        return *query, ownership
    return *query, None


def _pod_priority(pod: dict[str, Any]) -> tuple[bool, bool, bool, str]:
    meta, status = pod["metadata"], pod.get("status") or {}
    ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions") or []
    )
    return (
        bool(meta.get("deletionTimestamp")),
        status.get("phase") != "Running",
        not ready,
        meta["name"],
    )


def _workload_requests(
    workload: _Workload,
    pods: list[dict[str, Any]],
    settings: LogOptions,
    *,
    all_pods: bool = False,
) -> list[_Request]:
    if settings.container is not None:
        pods = [pod for pod in pods if settings.container in _container_names(pod)]
    if not pods:
        detail = f"No matching Pods for {workload.kind} {workload.namespace}/{workload.name}"
        if settings.container is not None:
            detail += f" with container {settings.container!r}"
        raise ResourceNotFound(detail)
    pods.sort(key=_pod_priority)
    if not all_pods:
        pods = pods[:1]
    requests = []
    for pod in pods:
        container = _container(pod, settings.container)
        if container is None:
            raise ValueError(f"Pod {pod['metadata']['name']} has no regular containers")
        source = next(_sources({"items": [pod]}, workload.config, container))
        requests.append(_request(source, None, workload.config, settings, {}, follow=False))
    return requests


def _resolve_request(
    pod: str | Resource | LogSource,
    namespace: str | None,
    config: Config | None,
    options: LogOptions | None,
    filters: LogParameters,
    *,
    follow: bool,
    label_selector: str | None = None,
) -> _Request:
    settings = _options(options, filters, follow)
    workload = _workload(pod, namespace, config)
    if workload is None:
        if label_selector is not None:
            raise ValueError("label_selector requires a workload target")
        return _request(pod, namespace, config, settings, {}, follow=follow)
    pods = list(_list_pods(*_workload_query(workload, label_selector)))
    return _workload_requests(workload, pods, settings)[0]


async def _async_resolve_requests(
    pod: str | Resource | LogSource,
    namespace: str | None,
    config: Config | None,
    options: LogOptions | None,
    filters: LogParameters,
    *,
    follow: bool,
    label_selector: str | None = None,
    all_pods: bool = False,
) -> list[_Request]:
    settings = _options(options, filters, follow)
    workload = _workload(pod, namespace, config)
    if workload is None:
        if label_selector is not None:
            raise ValueError("label_selector requires a workload target")
        if all_pods:
            raise ValueError(
                "all_pods requires a workload resource or a supported kind/name target"
            )
        return [_request(pod, namespace, config, settings, {}, follow=follow)]
    query = await _async_workload_query(workload, label_selector)
    pods = [pod async for pod in _async_list_pods(*query)]
    return _workload_requests(workload, pods, settings, all_pods=all_pods)


def read(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    label_selector: str | None = None,
    options: LogOptions | None = None,
    **filters: Unpack[LogParameters],
) -> str:
    """Read text from a Pod or one selected workload Pod, preserving line endings.

    Built-in workload targets accept kind/name or a Resource instance. Custom
    resources use spec.selector by convention, then UID-checked owner references.
    label_selector explicitly supplies their Pod association. For built-ins with
    Pod selectors, label_selector narrows their selector.
    """
    request = _resolve_request(
        pod, namespace, config, options, filters, follow=False, label_selector=label_selector
    )
    response = request.config.client.get(
        request.url, params=request.params(False), headers=_LOG_HEADERS
    )
    raise_for_status(response)
    return response.text


async def async_read(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    label_selector: str | None = None,
    options: LogOptions | None = None,
    **filters: Unpack[LogParameters],
) -> str:
    """Read a finite log snapshot without synchronous discovery or I/O."""
    request = (
        await _async_resolve_requests(
            pod, namespace, config, options, filters, follow=False, label_selector=label_selector
        )
    )[0]
    response = await request.config.async_client.get(
        request.url, params=request.params(False), headers=_LOG_HEADERS
    )
    raise_for_status(response)
    return response.text


@contextmanager
def stream(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    label_selector: str | None = None,
    options: LogOptions | None = None,
    follow: bool = True,
    match: Callable[[LogRecord], bool] | None = None,
    **filters: Unpack[LogParameters],
) -> Iterator[Iterator[LogRecord]]:
    """Follow records inside a with block; exiting closes the response immediately."""
    request = _resolve_request(
        pod, namespace, config, options, filters, follow=follow, label_selector=label_selector
    )
    client = request.config.client
    with client.stream(
        "GET",
        request.url,
        params=request.params(follow),
        headers=_LOG_HEADERS,
        timeout=_timeout(client) if follow else client.timeout,
    ) as response:
        if not response.is_success:
            response.read()
            raise_for_status(response)
        records = (request.record(line) for line in response.iter_lines())
        yield (record for record in records if match is None or match(record))


@asynccontextmanager
async def async_stream(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    label_selector: str | None = None,
    options: LogOptions | None = None,
    follow: bool = True,
    match: Callable[[LogRecord], bool] | None = None,
    all_pods: bool = False,
    max_streams: int = 10,
    **filters: Unpack[LogParameters],
) -> AsyncIterator[AsyncIterator[LogRecord]]:
    """Stream a Pod, or discover and stream a workload inside an async with block.

    By default, select one workload Pod, preferring running, ready Pods that are
    not terminating. all_pods=True merges one container per matching Pod in arrival
    order. Follow fails before opening logs if the selection exceeds max_streams;
    finite snapshots use at most max_streams concurrent requests. Exiting cancels
    all producers and closes their responses. Pod membership is a snapshot.
    """
    if max_streams < 1:
        raise ValueError("max_streams must be positive")
    requests = await _async_resolve_requests(
        pod,
        namespace,
        config,
        options,
        filters,
        follow=follow,
        all_pods=all_pods,
        label_selector=label_selector,
    )
    if follow and len(requests) > max_streams:
        raise ValueError(
            f"Following {len(requests)} containers exceeds max_streams={max_streams}; "
            "increase max_streams or select fewer sources with discover()"
        )
    if len(requests) == 1:
        async with _async_stream_request(requests[0], follow) as records:
            yield (record async for record in records if match is None or match(record))
    else:
        async with _merge_streams(requests, follow, max_streams) as records:
            yield (record async for record in records if match is None or match(record))


@asynccontextmanager
async def _async_stream_request(
    request: _Request,
    follow: bool,
) -> AsyncIterator[AsyncIterator[LogRecord]]:
    client = request.config.async_client
    async with client.stream(
        "GET",
        request.url,
        params=request.params(follow),
        headers=_LOG_HEADERS,
        timeout=_timeout(client) if follow else client.timeout,
    ) as response:
        if not response.is_success:
            await response.aread()
            raise_for_status(response)
        yield (request.record(line) async for line in response.aiter_lines())


@asynccontextmanager
async def _merge_streams(
    requests: list[_Request],
    follow: bool,
    max_streams: int,
) -> AsyncIterator[AsyncIterator[LogRecord]]:
    # Backpressure bounds buffered records even when callers consume slowly.
    queue: asyncio.Queue[LogRecord | Exception | None] = asyncio.Queue(maxsize=128)
    pending = iter(requests)
    worker_count = min(max_streams, len(requests))

    async def produce() -> None:
        for request in pending:
            try:
                async with _async_stream_request(request, follow) as records:
                    async for record in records:
                        await queue.put(record)
            except Exception as exc:
                exc.add_note(
                    f"Log source: {request.namespace}/{request.pod}/{request.options.container}"
                )
                await queue.put(exc)
                break
        await queue.put(None)

    async def consume() -> AsyncIterator[LogRecord]:
        remaining = worker_count
        while remaining:
            item = await queue.get()
            if item is None:
                remaining -= 1
            elif isinstance(item, Exception):
                raise item
            else:
                yield item

    tasks = [asyncio.create_task(produce()) for _ in range(worker_count)]
    try:
        yield consume()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _discovery_request(
    config: Config | None,
    namespace: str | None,
    all_namespaces: bool,
    label_selector: str | None,
    field_selector: str | None,
    page_size: int,
) -> tuple[Config, str, dict[str, str | int]]:
    if all_namespaces and namespace is not None:
        raise ValueError("namespace and all_namespaces are mutually exclusive")
    if page_size < 1:
        raise ValueError("page_size must be positive")
    config = config if config is not None else context.active_config
    if all_namespaces:
        url = "/api/v1/pods"
    else:
        url = f"/api/v1/namespaces/{_namespace(config, namespace)}/pods"
    params: dict[str, str | int] = {"limit": page_size}
    if label_selector is not None:
        params["labelSelector"] = label_selector
    if field_selector is not None:
        params["fieldSelector"] = field_selector
    return config, url, params


def _sources(data: dict[str, Any], config: Config, container: str | None) -> Iterator[LogSource]:
    for pod in data["items"]:
        meta, spec, status = pod["metadata"], pod.get("spec", {}), pod.get("status", {})
        labels = MappingProxyType(dict(meta.get("labels") or {}))
        owners = tuple((owner["kind"], owner["name"]) for owner in meta.get("ownerReferences", []))
        groups: tuple[tuple[str, str, Literal["regular", "init", "ephemeral"]], ...] = (
            ("containers", "containerStatuses", "regular"),
            ("initContainers", "initContainerStatuses", "init"),
            ("ephemeralContainers", "ephemeralContainerStatuses", "ephemeral"),
        )
        for spec_key, status_key, kind in groups:
            statuses = {item["name"]: item for item in status.get(status_key, [])}
            for item in spec.get(spec_key, []):
                name = item["name"]
                if container is not None and name != container:
                    continue
                details = statuses.get(name, {})
                state: Literal["waiting", "running", "terminated"] | None = None
                for candidate in ("waiting", "running", "terminated"):
                    if candidate in (details.get("state") or {}):
                        state = candidate
                        break
                yield LogSource(
                    pod=meta["name"],
                    namespace=meta["namespace"],
                    container=name,
                    container_type=kind,
                    labels=labels,
                    pod_uid=meta.get("uid"),
                    owners=owners,
                    node=spec.get("nodeName"),
                    phase=status.get("phase"),
                    restart_count=details.get("restartCount", 0),
                    state=state,
                    _config=config,
                )


def discover(
    workload: str | Resource | None = None,
    *,
    namespace: str | None = None,
    all_namespaces: bool = False,
    label_selector: str | None = None,
    field_selector: str | None = None,
    container: str | None = None,
    config: Config | None = None,
    page_size: int = 500,
) -> Iterator[LogSource]:
    """Discover regular, init, and ephemeral containers without downloading logs.

    Pass a workload object or "deployment/name", "statefulset/name", etc. to use
    its full Pod selector. Custom Resource instances use spec.selector by convention,
    falling back to recursive ownerReferences matched by UID; CronJobs also traverse
    their ownership chains. The fallback needs metadata.uid and access to ancestors.
    Provide label_selector explicitly when the Pod association differs. It narrows
    built-in Pod selectors but replaces the convention for other resources.
    Defaults to the active namespace. Set all_namespaces=True for cluster-wide discovery.
    Kubernetes applies selectors before pagination. Errors (including RBAC) propagate.
    """
    target = _discovery_target(workload, namespace, config, all_namespaces, page_size, container)
    query = (
        _workload_query(target, label_selector, field_selector, page_size)
        if target is not None
        else _discovery_request(
            config, namespace, all_namespaces, label_selector, field_selector, page_size
        )
    )
    for pod in _list_pods(*query):
        yield from _sources({"items": [pod]}, query[0], container)


def _discovery_target(
    workload: str | Resource | None,
    namespace: str | None,
    config: Config | None,
    all_namespaces: bool,
    page_size: int,
    container: str | None,
) -> _Workload | None:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    LogOptions(container=container)
    if workload is None:
        return None
    if all_namespaces:
        raise ValueError("A workload cannot be combined with all_namespaces")
    target = _workload(workload, namespace, config)
    if target is None:
        raise ValueError(
            'Pass a workload resource or a supported kind/name (e.g. "deployment/name") to discover()'
        )
    return target


def _list_pods(
    config: Config,
    url: str,
    params: dict[str, str | int],
    ownership: OwnerTraversal | None = None,
) -> Iterator[dict[str, Any]]:
    params = dict(params)
    seen: set[str] = set()
    while True:
        response = config.client.get(url, params=params)
        raise_for_status(response)
        data = response.json()
        for pod in data["items"]:
            if ownership is None or ownership.matches(pod):
                yield pod
        token = data.get("metadata", {}).get("continue")
        if not token:
            return
        if token in seen:
            raise ValueError("Pod list returned a repeated continuation token")
        seen.add(token)
        params["continue"] = token


async def async_discover(
    workload: str | Resource | None = None,
    *,
    namespace: str | None = None,
    all_namespaces: bool = False,
    label_selector: str | None = None,
    field_selector: str | None = None,
    container: str | None = None,
    config: Config | None = None,
    page_size: int = 500,
) -> AsyncIterator[LogSource]:
    """Async equivalent of discover, with no blocking API discovery or requests."""
    target = _discovery_target(workload, namespace, config, all_namespaces, page_size, container)
    query = (
        await _async_workload_query(target, label_selector, field_selector, page_size)
        if target is not None
        else _discovery_request(
            config, namespace, all_namespaces, label_selector, field_selector, page_size
        )
    )
    async for pod in _async_list_pods(*query):
        for source in _sources({"items": [pod]}, query[0], container):
            yield source


async def _async_list_pods(
    config: Config,
    url: str,
    params: dict[str, str | int],
    ownership: OwnerTraversal | None = None,
) -> AsyncIterator[dict[str, Any]]:
    params = dict(params)
    seen: set[str] = set()
    while True:
        response = await config.async_client.get(url, params=params)
        raise_for_status(response)
        data = response.json()
        for pod in data["items"]:
            if ownership is None or await ownership.async_matches(pod):
                yield pod
        token = data.get("metadata", {}).get("continue")
        if not token:
            return
        if token in seen:
            raise ValueError("Pod list returned a repeated continuation token")
        seen.add(token)
        params["continue"] = token
