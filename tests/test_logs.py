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
from cloudcoil.resources import Resource


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
    assert request.headers["accept"] == "*/*"
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
    assert requests[0].headers["accept"] == "*/*"
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


def deployment_data():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "workers", "namespace": "jobs", "labels": {"wrong": "selector"}},
        "spec": {
            "selector": {
                "matchLabels": {"app": "worker"},
                "matchExpressions": [
                    {"key": "tier", "operator": "In", "values": ["web", "api"]},
                    {"key": "track", "operator": "NotIn", "values": ["canary"]},
                    {"key": "example.com/managed", "operator": "Exists"},
                    {"key": "disabled", "operator": "DoesNotExist"},
                ],
            },
            "template": {"metadata": {"labels": {"also": "wrong"}}, "spec": pod_data()["spec"]},
        },
    }


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("reference", ["object", "name", "metadata"])
async def test_deployment_discovery_selector_and_pagination(config, asynchronous, reference):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    data = deployment_data()
    target = {
        "object": Deployment.model_validate(data),
        "name": "deployment/workers",
        "metadata": Resource(
            apiVersion="apps/v1",
            kind="Deployment",
            metadata={"name": "workers", "namespace": "jobs"},
        ),
    }[reference]
    requests = []

    def handler(request):
        requests.append(request)
        if "/deployments/" in request.url.path:
            assert request.url.path == "/apis/apps/v1/namespaces/jobs/deployments/workers"
            return httpx.Response(200, json=data)
        second = "continue" in request.url.params
        assert request.url.path == "/api/v1/namespaces/jobs/pods"
        assert request.url.params["labelSelector"] == (
            "app=worker,tier in (api,web),track notin (canary),example.com/managed,!disabled,env=prod"
        )
        assert request.url.params["fieldSelector"] == "status.phase=Running"
        assert request.url.params["limit"] == "1"
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": "" if second else "next"},
                "items": [pod_data("second" if second else "first")],
            },
        )

    transport(config, handler)
    if asynchronous:
        config.client._transport = httpx.MockTransport(lambda _: pytest.fail("blocking I/O"))
    kwargs = dict(
        config=config,
        namespace="jobs",
        label_selector="env=prod",
        field_selector="status.phase=Running",
        container="setup",
        page_size=1,
    )
    sources = (
        [s async for s in logs.async_discover(target, **kwargs)]
        if asynchronous
        else list(logs.discover(target, **kwargs))
    )
    assert [(s.pod, s.container) for s in sources] == [("first", "setup"), ("second", "setup")]
    assert len(requests) == (2 if reference == "object" else 3)
    assert all(s._config is config for s in sources)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_deployment_selects_ready_pod_across_pages(config, asynchronous):
    pods = [pod_data(name) for name in ("a-pending", "b-unready", "c-terminating", "z-ready")]
    pods[0]["status"]["phase"] = "Pending"
    pods[2]["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    for pod in pods[2:]:
        pod["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    requests = []

    def handler(request):
        requests.append(request)
        if "/deployments/" in request.url.path:
            return httpx.Response(200, json=deployment_data())
        if request.url.path.endswith("/log"):
            assert request.url.path == "/api/v1/namespaces/jobs/pods/z-ready/log"
            assert request.url.params["container"] == "app"
            return httpx.Response(200, text="2026-01-01T00:00:00.123456789Z hello\n")
        second = "continue" in request.url.params
        return httpx.Response(
            200,
            json={
                "metadata": {"continue": "" if second else "next"},
                "items": pods[2:] if second else pods[:2],
            },
        )

    transport(config, handler)
    if asynchronous:
        config.client._transport = httpx.MockTransport(lambda _: pytest.fail("blocking I/O"))
    kwargs = dict(config=config, namespace="jobs", options=logs.LogOptions(tail_lines=5))
    if asynchronous:
        text = await logs.async_read("deploy/workers", **kwargs)
        async with logs.async_stream("deployment/workers", **kwargs) as records:
            record = await anext(records)
    else:
        text = logs.read("deployments/workers", **kwargs)
        with logs.stream("deployment/workers", **kwargs) as records:
            record = next(records)
    assert "hello" in text
    assert record.pod == "z-ready" and record.container == "app"
    assert record.source.pod_uid == "uid-z-ready"
    assert record.labels == {"app": "worker"}
    assert record.timestamp == "2026-01-01T00:00:00.123456789Z"
    assert requests[-1].url.params["tailLines"] == "5"
    assert requests[-1].url.params["follow"] == "true"


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"matchLabels": {}},
        {"matchExpressions": []},
        {"matchExpressions": [{"key": "app", "operator": "In", "values": []}]},
        {"matchExpressions": [{"key": "app", "operator": "Exists", "values": ["x"]}]},
        {"matchExpressions": [{"key": "app", "operator": "Typo"}]},
        {"matchLabels": {"app": "worker,other=x"}},
        {"matchLabels": {"/app": "worker"}},
    ],
)
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_deployment_invalid_selector_never_lists_namespace(config, selector, asynchronous):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    data = deployment_data()
    data["spec"]["selector"] = selector
    deployment = Deployment.model_validate(data)
    transport(config, lambda _: pytest.fail("must validate before HTTP"))
    with pytest.raises(ValueError, match="selector"):
        if asynchronous:
            await logs.async_read(deployment, config=config)
        else:
            logs.read(deployment, config=config)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_deployment_empty_results_and_rbac(config, asynchronous):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    deployment = Deployment.model_validate(deployment_data())
    transport(config, lambda _: httpx.Response(200, json={"items": []}))
    if asynchronous:
        assert [s async for s in logs.async_discover(deployment, config=config)] == []
    else:
        assert list(logs.discover(deployment, config=config)) == []
    with pytest.raises(ResourceNotFound, match="No matching Pods.*jobs/workers"):
        if asynchronous:
            await logs.async_read(deployment, config=config)
        else:
            logs.read(deployment, config=config)
    transport(config, lambda _: httpx.Response(403, json={"message": "deployment forbidden"}))
    with pytest.raises(APIError, match="deployment forbidden"):
        if asynchronous:
            await logs.async_read("deployment/workers", config=config)
        else:
            logs.read("deployment/workers", config=config)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_deployment_container_defaults_and_filter(config, asynchronous):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    deployment = Deployment.model_validate(deployment_data())
    pod = pod_data()
    pod["spec"]["containers"].append({"name": "sidecar", "image": "example"})
    requests = []

    def handler(request):
        requests.append(request)
        return (
            httpx.Response(200, text=request.url.params["container"])
            if request.url.path.endswith("/log")
            else httpx.Response(200, json={"items": [pod]})
        )

    transport(config, handler)

    async def read(**kwargs):
        return (
            await logs.async_read(deployment, config=config, **kwargs)
            if asynchronous
            else logs.read(deployment, config=config, **kwargs)
        )

    with pytest.raises(ValueError, match="multi-container"):
        await read()
    assert await read(container="setup") == "setup"
    pod["metadata"]["annotations"] = {"kubectl.kubernetes.io/default-container": "sidecar"}
    assert await read() == "sidecar"
    with pytest.raises(ResourceNotFound, match="container 'missing'"):
        await read(container="missing")


async def test_deployment_argument_validation_before_io(config):
    transport(config, lambda _: pytest.fail("unexpected HTTP"))
    for target in ("deployment/", "deployment/../x", "deployment/a..b", "pod/../x", "a..b"):
        with pytest.raises(ValueError):
            logs.read(target, config=config)
    with pytest.raises(ValidationError):
        await logs.async_read("deployment/workers", config=config, tail_lines=-1)
    for kwargs in ({"all_namespaces": True}, {"page_size": 0}, {"container": ""}):
        with pytest.raises(ValueError):
            list(logs.discover("deployment/workers", config=config, **kwargs))
    with pytest.raises(ValueError, match="workload"):
        list(logs.discover("worker", config=config))
    with pytest.raises(ValueError, match="all_pods"):
        async with logs.async_stream("worker", config=config, all_pods=True):
            pass
    with pytest.raises(ValueError, match="max_streams"):
        async with logs.async_stream("deployment/workers", config=config, max_streams=0):
            pass


async def test_all_pods_merges_live_sources_and_preserves_options(config):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    opened = set()
    closed = set()
    ready = asyncio.Event()
    requests = []

    class Body(httpx.AsyncByteStream):
        def __init__(self, name):
            self.name = name

        async def __aiter__(self):
            opened.add(self.name)
            if len(opened) == 2:
                ready.set()
            await ready.wait()  # A sequential implementation would deadlock here.
            yield b"2026-01-01T00:00:00.123456789Z ignore\n"
            yield b"2026-01-01T00:00:00.123456789Z ERROR example\n"

        async def aclose(self):
            closed.add(self.name)

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/log"):
            assert request.url.params["container"] == "setup"
            assert request.url.params["previous"] == "true"
            assert request.url.params["tailLines"] == "2"
            assert request.url.params["timestamps"] == "true"
            return httpx.Response(200, stream=Body(request.url.path.split("/")[-2]))
        return httpx.Response(200, json={"items": [pod_data("first"), pod_data("second")]})

    transport(config, handler)
    deployment = Deployment.model_validate(deployment_data())
    async with asyncio.timeout(2):
        async with logs.async_stream(
            deployment,
            config=config,
            all_pods=True,
            container="setup",
            previous=True,
            options=logs.LogOptions(tail_lines=2),
            match=logs.LogFilter(contains="ERROR"),
        ) as records:
            result = [record async for record in records]
    assert {r.pod for r in result} == {"first", "second"}
    assert all(r.source.container_type == "init" and r.previous for r in result)
    assert all(r.timestamp == "2026-01-01T00:00:00.123456789Z" for r in result)
    assert opened == closed == {"first", "second"}


@pytest.mark.parametrize("exit_mode", ["break", "cancel", "predicate", "http_error", "read_error"])
async def test_all_pods_closes_quiet_and_busy_producers(config, exit_mode):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    opened = set()
    closed = set()
    ready = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        def __init__(self, name):
            self.name = name

        async def __aiter__(self):
            opened.add(self.name)
            if len(opened) == 2:
                ready.set()
            await ready.wait()
            if self.name == "busy" and exit_mode != "cancel":
                if exit_mode == "read_error":
                    raise httpx.ReadError("connection lost")
                for _ in range(1000):  # Fill the bounded queue before the consumer exits.
                    yield b"hello\n"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.add(self.name)

    async def handler(request):
        if not request.url.path.endswith("/log"):
            return httpx.Response(200, json={"items": [pod_data("busy"), pod_data("quiet")]})
        name = request.url.path.split("/")[-2]
        if exit_mode == "http_error" and name == "busy":
            opened.add(name)
            await ready.wait()
            return httpx.Response(403, json={"message": "logs forbidden"})
        return httpx.Response(200, stream=Body(name))

    config.async_client._transport = httpx.MockTransport(handler)
    config.async_client._mounts.clear()
    deployment = Deployment.model_validate(deployment_data())

    def match(record):
        if exit_mode == "predicate":
            raise RuntimeError("bad predicate")
        return True

    async def consume():
        async with logs.async_stream(
            deployment, config=config, all_pods=True, match=match
        ) as records:
            await anext(records)

    task = asyncio.create_task(consume())
    async with asyncio.timeout(2):
        await ready.wait()
        if exit_mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif exit_mode in ("predicate", "http_error", "read_error"):
            error = {
                "predicate": RuntimeError,
                "http_error": APIError,
                "read_error": httpx.ReadError,
            }[exit_mode]
            with pytest.raises(error):
                await task
        else:
            await task
    assert closed == ({"quiet"} if exit_mode == "http_error" else opened)


async def test_all_pods_concurrency_limit_and_finite_batches(config):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    opened = active = peak = 0
    ready = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal opened, active, peak
            opened += 1
            active += 1
            peak = max(peak, active)
            if active == 2:
                ready.set()
            await ready.wait()
            yield b"line\n"

        async def aclose(self):
            nonlocal active
            active -= 1

    def handler(request):
        if request.url.path.endswith("/log"):
            return httpx.Response(200, stream=Body())
        return httpx.Response(200, json={"items": [pod_data(f"pod-{i}") for i in range(3)]})

    transport(config, handler)
    deployment = Deployment.model_validate(deployment_data())
    with pytest.raises(ValueError, match="3 containers exceeds max_streams=2"):
        async with logs.async_stream(deployment, config=config, all_pods=True, max_streams=2):
            pytest.fail("must reject before yielding")
    assert opened == 0
    async with asyncio.timeout(2):
        async with logs.async_stream(
            deployment,
            config=config,
            all_pods=True,
            max_streams=2,
            follow=False,
        ) as records:
            assert len([record async for record in records]) == 3
    assert opened == 3 and peak == 2 and active == 0


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "api_version,kind,plural,alias",
    [
        ("apps/v1", "ReplicaSet", "replicasets", "rs"),
        ("apps/v1", "StatefulSet", "statefulsets", "sts"),
        ("apps/v1", "DaemonSet", "daemonsets", "ds"),
        ("batch/v1", "Job", "jobs", "job"),
        ("v1", "ReplicationController", "replicationcontrollers", "rc"),
    ],
)
async def test_workload_kinds_and_short_names(
    config, asynchronous, api_version, kind, plural, alias
):
    from cloudcoil.resources import get_model

    data = deployment_data()
    data.update(apiVersion=api_version, kind=kind)
    if kind == "ReplicationController":
        data["spec"]["selector"] = {"app": "worker"}
    else:
        data["spec"]["selector"] = {"matchLabels": {"app": "worker"}}
    if kind == "StatefulSet":
        data["spec"]["serviceName"] = "workers"
    if kind == "Job":
        data["spec"].pop("replicas", None)
        data["spec"]["template"]["spec"]["restartPolicy"] = "Never"
    model = get_model(kind, api_version=api_version)
    workload = model.model_validate(data)
    fetched = []
    prefix = f"/apis/{api_version}" if "/" in api_version else f"/api/{api_version}"

    def handler(request):
        if request.url.path.endswith(f"/{plural}/workers"):
            assert request.url.path == f"{prefix}/namespaces/jobs/{plural}/workers"
            fetched.append(request.url.path)
            return httpx.Response(200, json=data)
        if request.url.path.endswith("/log"):
            assert "labelSelector" not in request.url.params
            assert "label_selector" not in request.url.params
            return httpx.Response(200, text="hello\n")
        assert request.url.path == "/api/v1/namespaces/jobs/pods"
        assert request.url.params["labelSelector"] == "app=worker,env=prod"
        return httpx.Response(200, json={"items": [pod_data("first"), pod_data("second")]})

    transport(config, handler)
    if asynchronous:
        config.client._transport = httpx.MockTransport(lambda _: pytest.fail("blocking I/O"))
    kwargs = dict(config=config, namespace="jobs", label_selector="env=prod")
    for target in (
        workload,
        Resource(apiVersion=api_version, kind=kind, metadata=workload.metadata),
        f"{alias}/workers",
        f"{plural}/workers",
        f"{kind.lower()}/workers",
    ):
        if asynchronous:
            sources = [s async for s in logs.async_discover(target, **kwargs)]
            assert await logs.async_read(target, **kwargs) == "hello\n"
            async with logs.async_stream(target, all_pods=True, follow=False, **kwargs) as records:
                assert {record.pod async for record in records} == {"first", "second"}
        else:
            sources = list(logs.discover(target, **kwargs))
            assert logs.read(target, **kwargs) == "hello\n"
            with logs.stream(target, follow=False, **kwargs) as records:
                assert next(records).pod == "first"
        assert len(sources) == 6
    assert len(fetched) == 12  # Each operation fetches references, never full objects.


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "selector",
    [
        {
            "matchLabels": {"operator.io/cluster": "database"},
            "matchExpressions": [
                {"key": "role", "operator": "In", "values": ["primary", "replica"]}
            ],
        },
        {"operator.io/cluster": "database", "role": "primary"},
    ],
)
async def test_custom_resource_selector_conventions(config, asynchronous, selector):
    from cloudcoil.resources import Unstructured

    custom = Unstructured.model_validate(
        {
            "apiVersion": "operator.io/v1",
            "kind": "Database",
            "metadata": {"name": "database", "namespace": "jobs"},
            "spec": {"selector": selector},
        }
    )
    expected = (
        "operator.io/cluster=database,role in (primary,replica)"
        if "matchLabels" in selector
        else "operator.io/cluster=database,role=primary"
    )

    def handler(request):
        if request.url.path.endswith("/log"):
            return httpx.Response(200, text="custom log\n")
        assert request.url.path == "/api/v1/namespaces/jobs/pods"  # No guessed CRD REST path.
        assert request.url.params["labelSelector"] == expected
        return httpx.Response(200, json={"items": [pod_data()]})

    transport(config, handler)
    if asynchronous:
        assert len([s async for s in logs.async_discover(custom, config=config)]) == 3
        assert await logs.async_read(custom, config=config) == "custom log\n"
        async with logs.async_stream(custom, all_pods=True, follow=False, config=config) as records:
            assert [record.message async for record in records] == ["custom log"]
    else:
        assert len(list(logs.discover(custom, config=config))) == 3
        assert logs.read(custom, config=config) == "custom log\n"
        with logs.stream(custom, follow=False, config=config) as records:
            assert next(records).message == "custom log"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("spec", [{}, {"selector": {"unrelated": {"database": "external"}}}])
async def test_custom_resource_explicit_pod_selector(config, asynchronous, spec):
    from cloudcoil.resources import Unstructured

    custom = Unstructured.model_validate(
        {
            "apiVersion": "operator.io/v1",
            "kind": "Database",
            "metadata": {"name": "database", "namespace": "jobs"},
            "spec": spec,
        }
    )
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/log"):
            assert "labelSelector" not in request.url.params
            return httpx.Response(200, text="custom log\n")
        assert request.url.path == "/api/v1/namespaces/jobs/pods"
        assert request.url.params["labelSelector"] == "operator.io/cluster=database"
        return httpx.Response(200, json={"items": [pod_data("first"), pod_data("second")]})

    transport(config, handler)
    kwargs = dict(config=config, label_selector="operator.io/cluster=database")
    if asynchronous:
        with pytest.raises(ValueError, match="selector"):
            await logs.async_read(custom, config=config)
        assert not requests
        assert len([s async for s in logs.async_discover(custom, **kwargs)]) == 6
        assert await logs.async_read(custom, **kwargs) == "custom log\n"
        async with logs.async_stream(custom, all_pods=True, follow=False, **kwargs) as records:
            assert {record.pod async for record in records} == {"first", "second"}
    else:
        with pytest.raises(ValueError, match="selector"):
            logs.read(custom, config=config)
        assert not requests
        assert len(list(logs.discover(custom, **kwargs))) == 6
        assert logs.read(custom, **kwargs) == "custom log\n"
        with logs.stream(custom, follow=False, **kwargs) as records:
            assert next(records).message == "custom log"


async def test_custom_and_builtin_selector_guards(config):
    from cloudcoil.models.kubernetes.apps.v1 import Deployment

    from cloudcoil.resources import Unstructured

    transport(config, lambda _: pytest.fail("must reject before I/O"))
    custom = Unstructured.model_validate(
        {
            "apiVersion": "operator.io/v1",
            "kind": "Database",
            "metadata": {"name": "db"},
        }
    )
    for selector in ("", " ", ", ,"):
        with pytest.raises(ValueError, match="empty"):
            await logs.async_read(custom, config=config, label_selector=selector)
    data = deployment_data()
    data["spec"]["selector"] = {}
    with pytest.raises(ValueError, match="empty"):
        logs.read(Deployment.model_validate(data), config=config, label_selector="app=worker")
    for pod in ("worker", "pod/worker"):
        with pytest.raises(ValueError, match="workload"):
            logs.read(pod, config=config, label_selector="app=worker")
        with pytest.raises(ValueError, match="workload"):
            await logs.async_read(pod, config=config, label_selector="app=worker")
    for raw in (
        {"matchLabels": ["bad"]},
        {"matchExpressions": ["bad"]},
        {"matchExpressions": [{"operator": "Exists"}]},
        {"matchExpressions": [{"key": "app", "operator": "In", "values": "bad"}]},
    ):
        custom["spec"] = {"selector": raw}
        with pytest.raises(ValueError, match="selector"):
            logs.read(custom, config=config)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_job_without_selector_fetches_server_generated_selector(config, asynchronous):
    from cloudcoil.models.kubernetes.batch.v1 import Job

    data = deployment_data()
    data.update(apiVersion="batch/v1", kind="Job")
    del data["spec"]["selector"]
    job = Job.model_validate(data)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/apis/batch/v1/namespaces/jobs/jobs/workers":
            data["spec"]["selector"] = {
                "matchLabels": {"batch.kubernetes.io/controller-uid": "job-uid"}
            }
            return httpx.Response(200, json=data)
        if request.url.path.endswith("/log"):
            return httpx.Response(200, text="done\n")
        assert request.url.params["labelSelector"] == "batch.kubernetes.io/controller-uid=job-uid"
        return httpx.Response(200, json={"items": [pod_data()]})

    transport(config, handler)
    result = (
        await logs.async_read(job, config=config) if asynchronous else logs.read(job, config=config)
    )
    assert result == "done\n"
    assert len(requests) == 3
