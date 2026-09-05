"""Log protocol, source discovery, filtering, and response lifetime regressions."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import Pod
from pydantic import ValidationError

from cloudcoil import logs
from cloudcoil._context import context
from cloudcoil.client import Config
from cloudcoil.errors import APIError, ResourceNotFound


@pytest.fixture
async def config():
    config = Config(server="https://test", namespace="chosen", token="secret")
    yield config
    config.client.close()
    await config.async_client.aclose()


def transport(config, handler):
    # Retain the real Config's authentication, TLS, and timeout setup.
    config.client._transport = httpx.MockTransport(handler)
    config.client._mounts.clear()
    config.async_client._transport = httpx.MockTransport(handler)
    config.async_client._mounts.clear()


def pod_data(name="worker"):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": "jobs",
            "uid": f"uid-{name}",
            "labels": {"app": "worker"},
            "ownerReferences": [
                {"apiVersion": "apps/v1", "kind": "ReplicaSet", "name": "workers", "uid": "rs"}
            ],
        },
        "spec": {
            "nodeName": "node-a",
            "containers": [{"name": "app", "image": "example"}],
            "initContainers": [{"name": "setup", "image": "example"}],
            "ephemeralContainers": [
                {"name": "debug", "image": "example", "targetContainerName": "app"}
            ],
        },
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "app",
                    "restartCount": 2,
                    "image": "example",
                    "imageID": "example-id",
                    "ready": True,
                    "state": {"running": {}},
                }
            ],
        },
    }


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_read_protocol_and_options(config, asynchronous):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="hello\r\nworld\n")

    transport(config, handler)
    opts = logs.LogOptions(
        container="app", tail_lines=50, since_time=datetime(2026, 1, 1, tzinfo=UTC)
    )
    fn = logs.async_read if asynchronous else logs.read
    result = fn("worker", config=config, options=opts, tail_lines=0, previous=True)
    if asynchronous:
        result = await result
    assert result == "hello\r\nworld\n"
    assert len(requests) == 1  # No discovery or Pod GET needed for pods/log-only RBAC.
    request = requests[0]
    assert request.url.path == "/api/v1/namespaces/chosen/pods/worker/log"
    assert request.headers["authorization"] == "Bearer secret"
    assert request.headers["accept"] == "text/plain"
    assert dict(request.url.params) == {
        "container": "app",
        "tailLines": "0",
        "sinceTime": "2026-01-01T00:00:00Z",
        "previous": "true",
        "timestamps": "false",
        "follow": "false",
    }
    assert opts.tail_lines == 50


@pytest.mark.parametrize(
    "overrides",
    [
        {"tail_lines": -1},
        {"since_seconds": 0},
        {"limit_bytes": 0},
        {"container": ""},
        {"since_time": datetime(2026, 1, 1)},
        {"since_seconds": 1, "since_time": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
)
async def test_invalid_options_before_io(config, overrides):
    transport(config, lambda _: pytest.fail("unexpected HTTP request"))
    with pytest.raises(ValidationError):
        logs.read("worker", config=config, **overrides)


async def test_pod_defaults_and_ambiguity(config):
    requests = []
    transport(config, lambda r: (requests.append(r), httpx.Response(200, text=""))[1])
    pod = Pod.model_validate(pod_data())
    logs.read(pod, config=config)
    assert requests[-1].url.path == "/api/v1/namespaces/jobs/pods/worker/log"
    assert requests[-1].url.params["container"] == "app"
    data = pod_data()
    data["spec"]["containers"].append({"name": "sidecar", "image": "example"})
    pod = Pod.model_validate(data)
    with pytest.raises(ValueError, match="multi-container"):
        logs.read(pod, config=config)
    pod.metadata.annotations = {"kubectl.kubernetes.io/default-container": "sidecar"}
    logs.read(pod, config=config, namespace="override")
    assert requests[-1].url.params["container"] == "sidecar"
    assert "/namespaces/override/" in requests[-1].url.path
    logs.read(pod, config=config, container="setup")
    assert requests[-1].url.params["container"] == "setup"


class Bytes(httpx.SyncByteStream):
    closed = False

    def __iter__(self):
        yield b"2026-01-01T00:00:00.123456789Z ERROR caf\xc3"
        yield b"\xa9\r\n\nplain partial"

    def close(self):
        self.closed = True


class AsyncBytes(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        for chunk in Bytes():
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_records_filter_and_cleanup(config, asynchronous):
    body = AsyncBytes() if asynchronous else Bytes()
    requests = []
    transport(config, lambda r: (requests.append(r), httpx.Response(200, stream=body))[1])
    pod = Pod.model_validate(pod_data())
    match = logs.LogFilter(contains="error", regex="café$", ignore_case=True)
    if asynchronous:
        async with logs.async_stream(pod, config=config, match=match, previous=True) as records:
            record = await anext(records)
            assert not body.closed
    else:
        with logs.stream(pod, config=config, match=match, previous=True) as records:
            record = next(records)
            assert not body.closed
    assert body.closed
    assert record.previous is True
    assert record.message == "ERROR café"
    assert record.timestamp == "2026-01-01T00:00:00.123456789Z"
    assert str(record) == record.raw == f"{record.timestamp} ERROR café"
    assert (record.pod, record.namespace, record.container) == ("worker", "jobs", "app")
    pod.metadata.labels["app"] = "changed"
    assert record.labels == {"app": "worker"}
    with pytest.raises(TypeError):
        record.labels["x"] = "no"
    timeout = requests[0].extensions["timeout"]
    assert timeout["read"] is None
    assert timeout["connect"] == config.client.timeout.connect
    assert config.client.timeout.read is not None


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_snapshot_lines_preserved(config, asynchronous):
    body = AsyncBytes() if asynchronous else Bytes()
    transport(config, lambda _: httpx.Response(200, stream=body))
    if asynchronous:
        async with logs.async_stream("worker", config=config, follow=False) as records:
            result = [record async for record in records]
    else:
        with logs.stream("worker", config=config, follow=False) as records:
            result = list(records)
    assert len(result) == 3
    assert result[1].message == ""
    assert result[2].message == "plain partial"
    assert all(record.timestamp is None and record.labels is None for record in result)
    assert result[0].message.startswith("2026-")  # No parsing unless timestamps were requested.
    assert body.closed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "status,detail,error",
    [
        (404, {"message": "gone"}, ResourceNotFound),
        (403, "forbidden", APIError),
    ],
)
async def test_errors_close_stream(config, asynchronous, status, detail, error):
    responses = []

    def handler(_):
        response = httpx.Response(
            status, **({"json": detail} if isinstance(detail, dict) else {"text": detail})
        )
        responses.append(response)
        return response

    transport(config, handler)
    with pytest.raises(error) as exc:
        if asynchronous:
            async with logs.async_stream("worker", config=config):
                pytest.fail("yielded on HTTP failure")
        else:
            with logs.stream("worker", config=config):
                pytest.fail("yielded on HTTP failure")
    assert exc.value.status_code == status
    assert responses[0].is_closed


async def test_async_cancellation_closes_response(config):
    started = asyncio.Event()

    class Blocked(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            self.closed = True

    body = Blocked()
    transport(config, lambda _: httpx.Response(200, stream=body))

    async def consume():
        async with logs.async_stream("worker", config=config) as records:
            await anext(records)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert body.closed


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_discovery_pagination_metadata_and_source_read(config, asynchronous):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/log"):
            return httpx.Response(200, text="hello\n")
        second = request.url.params.get("continue") == "next"
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": "" if second else "next"},
                "items": [pod_data("second" if second else "first")],
            },
        )

    transport(config, handler)
    kwargs = dict(
        config=config,
        all_namespaces=True,
        label_selector="app=worker",
        field_selector="status.phase=Running",
        page_size=1,
    )
    sources = (
        [s async for s in logs.async_discover(**kwargs)]
        if asynchronous
        else list(logs.discover(**kwargs))
    )
    assert len(sources) == 6
    assert [s.container_type for s in sources[:3]] == ["regular", "init", "ephemeral"]
    source = sources[0]
    assert source.restart_count == 2 and source.state == "running"
    assert source.owners == (("ReplicaSet", "workers"),)
    assert source.pod_uid == "uid-first" and source.node == "node-a" and source.phase == "Running"
    assert source.labels == {"app": "worker"}
    assert requests[0].url.path == "/api/v1/pods"
    assert dict(requests[1].url.params) == {
        "limit": "1",
        "labelSelector": "app=worker",
        "fieldSelector": "status.phase=Running",
        "continue": "next",
    }
    # Retains its Config, namespace and container without requiring any active context.
    assert (await logs.async_read(source) if asynchronous else logs.read(source)) == "hello\n"
    assert requests[-1].url.path == "/api/v1/namespaces/jobs/pods/first/log"
    assert requests[-1].url.params["container"] == "app"
    with logs.stream(source, follow=False, match=lambda r: r.labels["app"] == "worker") as records:
        assert next(records).source is source
    with pytest.raises(ValueError, match="namespace"):
        logs.read(source, namespace="different")
    with pytest.raises(ValueError, match="container"):
        logs.read(source, container="different")


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_discovery_container_filter_and_repeated_token(config, asynchronous):
    transport(
        config,
        lambda _: httpx.Response(
            200, json={"metadata": {"continue": "same"}, "items": [pod_data()]}
        ),
    )
    it = (
        logs.async_discover(config=config, container="setup")
        if asynchronous
        else logs.discover(config=config, container="setup")
    )
    first = await anext(it) if asynchronous else next(it)
    assert first.container == "setup"
    with pytest.raises(ValueError, match="repeated continuation"):
        if asynchronous:
            _ = [s async for s in it]
        else:
            list(it)


async def test_discovery_validation_and_active_config(config):
    requests = []
    transport(config, lambda r: (requests.append(r), httpx.Response(200, json={"items": []}))[1])
    # Push directly: this verifies the active-config path without unrelated API discovery.
    context._enter(config)
    try:
        assert list(logs.discover()) == []
    finally:
        context._exit(config)
    assert requests[0].url.path == "/api/v1/namespaces/chosen/pods"
    for kwargs in (
        {"namespace": "x", "all_namespaces": True},
        {"page_size": 0},
        {"namespace": "../bad"},
    ):
        with pytest.raises(ValueError):
            list(logs.discover(config=config, **kwargs))


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_predicate_failure_closes_stream(config, asynchronous):
    body = AsyncBytes() if asynchronous else Bytes()
    transport(config, lambda _: httpx.Response(200, stream=body))

    def broken(record):
        raise RuntimeError("filter failed")

    with pytest.raises(RuntimeError, match="filter failed"):
        if asynchronous:
            async with logs.async_stream("worker", config=config, match=broken) as records:
                await anext(records)
        else:
            with logs.stream("worker", config=config, match=broken) as records:
                next(records)
    assert body.closed


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_discovery_rbac_error_is_not_an_empty_result(config, asynchronous):
    transport(config, lambda _: httpx.Response(403, json={"message": "pods forbidden"}))
    with pytest.raises(APIError) as exc:
        if asynchronous:
            _ = [source async for source in logs.async_discover(config=config)]
        else:
            list(logs.discover(config=config))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_read_http_errors(config, asynchronous):
    transport(config, lambda _: httpx.Response(404, json={"message": "pod gone"}))
    with pytest.raises(ResourceNotFound):
        if asynchronous:
            await logs.async_read("worker", config=config)
        else:
            logs.read("worker", config=config)


async def test_empty_logs_and_invalid_pod_inputs(config):
    from cloudcoil.models.kubernetes.core.v1 import ConfigMap

    transport(config, lambda _: httpx.Response(200, text=""))
    assert logs.read("worker", config=config) == ""
    with logs.stream("worker", config=config) as records:
        assert list(records) == []
    for pod in ("../worker", "", ConfigMap(metadata={"name": "config"}), Pod()):
        with pytest.raises(ValueError):
            logs.read(pod, config=config)


def test_log_filter_validation_and_combination():
    import re

    with pytest.raises(re.error):
        logs.LogFilter(regex="[")
    record = logs.LogRecord("ERROR café", "ERROR café", "worker", "jobs", "app", None, {})
    assert logs.LogFilter()(record)
    assert logs.LogFilter(contains="error", ignore_case=True)(record)
    assert not logs.LogFilter(contains="error")(record)
    assert not logs.LogFilter(contains="ERROR", regex="missing")(record)


@pytest.mark.parametrize(
    "options,overrides,expected",
    [
        (logs.LogOptions(tail_lines=10), {}, "true"),
        (logs.LogOptions(timestamps=False), {}, "false"),
        (logs.LogOptions(timestamps=False), {"timestamps": True}, "true"),
    ],
)
async def test_reusable_options_preserve_operation_defaults(config, options, overrides, expected):
    requests = []
    transport(config, lambda r: (requests.append(r), httpx.Response(200, text=""))[1])
    with logs.stream("worker", config=config, options=options, **overrides) as records:
        assert list(records) == []
    assert requests[0].url.params["timestamps"] == expected
