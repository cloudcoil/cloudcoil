"""Read and follow pod logs using the active Config's authenticated HTTP clients."""

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
from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status
from cloudcoil.resources import Resource

logger = logging.getLogger(__name__)


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

    Metadata filtering can use a predicate instead, e.g. match=lambda r: r.labels.get(...).
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


def _request(
    pod: str | Resource | LogSource,
    namespace: str | None,
    config: Config | None,
    options: LogOptions | None,
    overrides: LogParameters,
    *,
    follow: bool,
) -> _Request:
    values: dict[str, Any] = options.model_dump() if options is not None else {"timestamps": follow}
    values.update(overrides)
    settings = LogOptions.model_validate(values)
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
        if settings.container is None:
            data = pod.model_dump(by_alias=True, exclude_none=True)
            spec = data.get("spec") or {}
            regular = [item["name"] for item in spec.get("containers", [])]
            containers = regular + [
                item["name"]
                for key in ("initContainers", "ephemeralContainers")
                for item in spec.get(key, [])
            ]
            default = (data.get("metadata", {}).get("annotations") or {}).get(
                "kubectl.kubernetes.io/default-container"
            )
            if default and default in containers:
                settings = settings.model_copy(update={"container": default})
            elif len(regular) == 1:
                settings = settings.model_copy(update={"container": regular[0]})
            elif len(regular) > 1:
                raise ValueError(
                    f"Specify container for multi-container pod; choose from {containers}"
                )
    else:
        name = pod
    if not name or len(name) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name):
        raise ValueError("A valid pod name is required")
    config = config if config is not None else context.active_config
    namespace = config.namespace if namespace is None else namespace
    if (
        not namespace
        or len(namespace) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", namespace)
    ):
        raise ValueError("A valid namespace is required")
    logger.debug("%s logs for %s/%s", "Following" if follow else "Reading", namespace, name)
    return _Request(config, name, namespace, settings, labels, source)


def _timeout(client: httpx.Client | httpx.AsyncClient) -> httpx.Timeout:
    timeout = httpx.Timeout(client.timeout)
    timeout.read = None  # Quiet containers may produce no log output for hours.
    return timeout


def read(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    options: LogOptions | None = None,
    **filters: Unpack[LogParameters],
) -> str:
    """Read a finite log snapshot as text, preserving line endings."""
    request = _request(pod, namespace, config, options, filters, follow=False)
    response = request.config.client.get(
        request.url, params=request.params(False), headers={"Accept": "text/plain"}
    )
    raise_for_status(response)
    return response.text


async def async_read(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    options: LogOptions | None = None,
    **filters: Unpack[LogParameters],
) -> str:
    """Read a finite log snapshot without synchronous discovery or I/O."""
    request = _request(pod, namespace, config, options, filters, follow=False)
    response = await request.config.async_client.get(
        request.url, params=request.params(False), headers={"Accept": "text/plain"}
    )
    raise_for_status(response)
    return response.text


@contextmanager
def stream(
    pod: str | Resource | LogSource,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    options: LogOptions | None = None,
    follow: bool = True,
    match: Callable[[LogRecord], bool] | None = None,
    **filters: Unpack[LogParameters],
) -> Iterator[Iterator[LogRecord]]:
    """Follow records inside a with block; exiting closes the response immediately."""
    request = _request(pod, namespace, config, options, filters, follow=follow)
    client = request.config.client
    with client.stream(
        "GET",
        request.url,
        params=request.params(follow),
        headers={"Accept": "text/plain"},
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
    options: LogOptions | None = None,
    follow: bool = True,
    match: Callable[[LogRecord], bool] | None = None,
    **filters: Unpack[LogParameters],
) -> AsyncIterator[AsyncIterator[LogRecord]]:
    """Follow records inside an async with block; cancellation closes the response."""
    request = _request(pod, namespace, config, options, filters, follow=follow)
    client = request.config.async_client
    async with client.stream(
        "GET",
        request.url,
        params=request.params(follow),
        headers={"Accept": "text/plain"},
        timeout=_timeout(client) if follow else client.timeout,
    ) as response:
        if not response.is_success:
            await response.aread()
            raise_for_status(response)
        records = (request.record(line) async for line in response.aiter_lines())
        yield (record async for record in records if match is None or match(record))


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
        # Reuse path validation without fetching a Pod or performing API discovery.
        request = _request("placeholder", namespace, config, None, {}, follow=False)
        url = f"/api/v1/namespaces/{request.namespace}/pods"
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

    Defaults to the active namespace. Set all_namespaces=True for cluster-wide discovery.
    Kubernetes applies selectors before pagination. Errors (including RBAC) propagate.
    """
    config, url, params = _discovery_request(
        config, namespace, all_namespaces, label_selector, field_selector, page_size
    )
    seen: set[str] = set()
    while True:
        response = config.client.get(url, params=params)
        raise_for_status(response)
        data = response.json()
        yield from _sources(data, config, container)
        token = data.get("metadata", {}).get("continue")
        if not token:
            return
        if token in seen:
            raise ValueError("Pod list returned a repeated continuation token")
        seen.add(token)
        params["continue"] = token


async def async_discover(
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
    config, url, params = _discovery_request(
        config, namespace, all_namespaces, label_selector, field_selector, page_size
    )
    seen: set[str] = set()
    while True:
        response = await config.async_client.get(url, params=params)
        raise_for_status(response)
        data = response.json()
        for source in _sources(data, config, container):
            yield source
        token = data.get("metadata", {}).get("continue")
        if not token:
            return
        if token in seen:
            raise ValueError("Pod list returned a repeated continuation token")
        seen.add(token)
        params["continue"] = token
