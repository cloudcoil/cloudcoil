"""Generated CRDs and admission webhooks against the Kubernetes/provider CI matrix."""

import asyncio
import json
import os
import ssl
import subprocess
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import Namespace
from pydantic import BaseModel, Field, create_model

from cloudcoil.admission import AdmissionDenied, AdmissionWebhook, mutating, validating
from cloudcoil.controller import Controller
from cloudcoil.crd import CEL, CRD, ListType, PrinterColumn, custom_resource
from cloudcoil.resources import Resource

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
cluster_name = f"test-cloudcoil-sync-v{k8s_version}"
provider = os.environ.get("CLUSTER_PROVIDER", "kind")
pytestmark = pytest.mark.configure_test_cluster(
    cluster_name=cluster_name,
    k8s_version=f"v{k8s_version}",
    provider=provider,
    remove=False,
)


class ExtensionSpec(BaseModel):
    replicas: Annotated[int, CEL("self <= 4", "At most four replicas")] = Field(
        default=1, ge=1, le=5
    )
    tags: Annotated[list[str], ListType("set")] = Field(default_factory=list)
    message: str = "hello"
    mode: Literal["Active", "Paused"] = "Active"
    target: int | str = 80
    note: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ExtensionStatus(BaseModel):
    ready: Annotated[bool, PrinterColumn(name="Ready")]
    observed_generation: int = Field(alias="observedGeneration")


@asynccontextmanager
async def installed_widget(config):
    """Isolate cluster-scoped definitions even under pytest-xdist and retained clusters."""
    group = f"test-{uuid4().hex[:12]}.cloudcoil.dev"
    api_version = f"{group}/v1"
    widget_type = create_model(
        "ExtensionWidget",
        __base__=Resource,
        api_version=(Literal[api_version], Field(default=api_version, alias="apiVersion")),
        kind=(Literal["ExtensionWidget"], "ExtensionWidget"),
        spec=(ExtensionSpec, ...),
        status=(ExtensionStatus | None, None),
    )
    widget_type = custom_resource(plural="widgets")(widget_type)
    manifest = CRD(widget_type).manifest()
    assert manifest["spec"]["versions"][0]["additionalPrinterColumns"][0] == {
        "name": "Ready",
        "jsonPath": ".status.ready",
        "type": "boolean",
        "priority": 0,
    }
    definitions = "/apis/apiextensions.k8s.io/v1/customresourcedefinitions"
    definition_url = f"{definitions}/{manifest['metadata']['name']}"
    namespace = await Namespace(metadata={"generateName": "test-extensions-"}).async_create()
    created = False
    try:
        response = await config.async_client.post(definitions, json=manifest)
        assert response.status_code == 201, response.text
        created = True
        async with asyncio.timeout(30):
            while True:
                response = await config.async_client.get(definition_url)
                response.raise_for_status()
                conditions = (response.json().get("status") or {}).get("conditions") or []
                if any(c["type"] == "Established" and c["status"] == "True" for c in conditions):
                    break
                await asyncio.sleep(0.1)
        await asyncio.to_thread(config.refresh_api_resources)
        yield widget_type, namespace.name, group
    finally:
        if created:
            response = await config.async_client.delete(definition_url)
            response.raise_for_status()
        await namespace.async_remove()


async def test_live_generated_crd_validation_defaults_and_controller_status(test_config):
    async with test_config, installed_widget(test_config) as (widget_type, namespace, group):
        collection = f"/apis/{group}/v1/namespaces/{namespace}/widgets"

        def document(spec):
            return {
                "apiVersion": f"{group}/v1",
                "kind": "ExtensionWidget",
                "metadata": {"name": "example", "namespace": namespace},
                "spec": spec,
            }

        # Raw HTTP bypasses Pydantic: these failures prove API-server validation.
        for spec in (
            {"replicas": 0},
            {"replicas": 6},
            {"replicas": 5},
            {"mode": "Invalid"},
            {"target": True},
            {"tags": ["duplicate", "duplicate"]},
        ):
            response = await test_config.async_client.post(collection, json=document(spec))
            assert response.status_code == 422, response.text
        response = await test_config.async_client.post(
            collection,
            json=document({"target": "named-port", "note": None}),
            params={"dryRun": "All"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["spec"]["target"] == "named-port"
        assert response.json()["spec"].get("note") is None
        initial = document({"extra": {"nested": {"arbitrary": [1, "two", None]}}})
        initial["status"] = {"ready": True, "observedGeneration": 999}
        response = await test_config.async_client.post(collection, json=initial)
        assert response.status_code == 201, response.text
        assert response.json()["spec"]["replicas"] == 1
        assert response.json()["spec"]["message"] == "hello"
        assert response.json()["spec"]["mode"] == "Active"
        assert response.json()["spec"]["target"] == 80
        assert response.json()["spec"].get("note") is None
        assert response.json()["spec"]["extra"] == initial["spec"]["extra"]
        # With the generated status subresource enabled, create ignores supplied status.
        assert not response.json().get("status")

        observed = asyncio.Event()
        stop = asyncio.Event()
        writes = []

        async def record(response):
            request = response.request
            if request.method == "PATCH" and request.url.path.startswith(collection + "/"):
                writes.append((request.url.path, response.status_code))

        async def reconcile(request):
            obj = request.resource
            if obj is None:
                return None
            desired = ExtensionStatus(ready=True, observedGeneration=obj.metadata.generation)
            if obj.status == desired:
                observed.set()
            obj.status = desired
            return obj

        controller = Controller(widget_type, reconcile, config=test_config, namespace=namespace)
        test_config.async_client.event_hooks["response"].append(record)
        task = asyncio.create_task(controller.run(stop=stop))
        try:
            await controller.wait_ready(30)
            await asyncio.wait_for(observed.wait(), 30)
            stop.set()
            await asyncio.wait_for(task, 20)
            current = await widget_type.async_get("example", namespace)
            assert current.status.ready
            assert current.status.observed_generation == current.metadata.generation
            assert current.spec.replicas == 1
            assert writes == [(f"{collection}/example/status", 200)]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            test_config.async_client.event_hooks["response"].remove(record)


@asynccontextmanager
async def admission_listener(app, tmp_path):
    """Expose the real ASGI app to Dockerized API servers using a test-only TLS bridge."""
    node = f"k3d-{cluster_name}-server-0" if provider == "k3d" else f"{cluster_name}-control-plane"
    inspect = await asyncio.to_thread(
        subprocess.run, ["docker", "inspect", node], check=True, capture_output=True, text=True
    )
    networks = json.loads(inspect.stdout)[0]["NetworkSettings"]["Networks"]
    gateway = next(network["Gateway"] for network in networks.values() if network.get("Gateway"))
    certificate, key = tmp_path / "server.crt", tmp_path / "server.key"
    await asyncio.to_thread(
        subprocess.run,
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=cloudcoil-test",
            "-addext",
            f"subjectAltName=IP:{gateway}",
        ],
        check=True,
        capture_output=True,
    )
    loop = asyncio.get_running_loop()

    async def forward(path, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            return await client.post(
                f"https://test{path}", content=body, headers={"Content-Type": "application/json"}
            )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            future = asyncio.run_coroutine_threadsafe(forward(self.path, body), loop)
            try:
                response = future.result(timeout=15)
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            finally:
                future.cancel()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://{gateway}:{server.server_port}", certificate.read_bytes()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(thread.join, 5)


async def test_live_generated_admission_mutation_validation_and_dry_run(test_config, tmp_path):
    async with test_config, installed_widget(test_config) as (widget_type, namespace, group):
        calls = []
        old_messages = []

        @custom_resource(plural="widgets")
        class AdmissionWidget(widget_type):
            @classmethod
            @mutating()
            async def default_labels(cls, request):
                calls.append(("mutate", request.operation, request.dry_run))
                obj = request.resource
                assert isinstance(obj, cls)
                obj.metadata.labels = {
                    **(obj.metadata.labels or {}),
                    "cloudcoil.dev/admitted": "yes",
                }
                return obj

            @classmethod
            @validating()
            async def validate_message(cls, request, client):
                calls.append(("validate", request.operation, request.dry_run))
                assert request.config is test_config
                namespaces = await request.config.async_client_for(Namespace, cached=False)
                assert (await namespaces.get(request.namespace)).name == namespace
                if request.operation == "UPDATE":
                    stored = await client.get(request.name)
                    assert isinstance(stored, cls)
                    assert stored.metadata.uid == request.old_resource.metadata.uid
                    old_messages.append(request.old_resource.spec.message)
                if request.resource.spec.message == "forbidden":
                    raise AdmissionDenied("message is forbidden")

        app = AdmissionWebhook(config=test_config).register(AdmissionWidget)

        async with admission_listener(app, tmp_path) as (url, certificate):
            configured = []
            registration = "/apis/admissionregistration.k8s.io/v1"
            collection = f"/apis/{group}/v1/namespaces/{namespace}/widgets"
            try:
                for config in app.configurations(
                    name=group,
                    service_name="test-webhook",
                    service_namespace=namespace,
                    ca_bundle=certificate,
                ):
                    for webhook in config["webhooks"]:
                        service = webhook["clientConfig"].pop("service")
                        webhook["clientConfig"]["url"] = url + service["path"]
                    resource = config["kind"].lower() + "s"
                    response = await test_config.async_client.post(
                        f"{registration}/{resource}", json=config
                    )
                    assert response.status_code == 201, response.text
                    configured.append(f"{registration}/{resource}/{config['metadata']['name']}")

                document = {
                    "apiVersion": f"{group}/v1",
                    "kind": "ExtensionWidget",
                    "metadata": {"name": "example", "namespace": namespace},
                    "spec": {"message": "allowed"},
                }
                # API servers discover webhook registrations asynchronously. Dry runs
                # wait for both routes without leaving objects or external side effects.
                async with asyncio.timeout(30):
                    while True:
                        response = await test_config.async_client.post(
                            collection, json=document, params={"dryRun": "All"}
                        )
                        assert response.status_code == 201, response.text
                        if {("mutate", "CREATE", True), ("validate", "CREATE", True)} <= set(calls):
                            break
                        await asyncio.sleep(0.1)
                assert response.json()["metadata"]["labels"]["cloudcoil.dev/admitted"] == "yes"
                response = await test_config.async_client.get(f"{collection}/example")
                assert response.status_code == 404  # Dry run was never persisted.

                document["spec"]["message"] = "forbidden"
                response = await test_config.async_client.post(collection, json=document)
                assert response.status_code == 403, response.text
                assert "message is forbidden" in response.json()["message"]

                document["spec"]["message"] = "allowed"
                response = await test_config.async_client.post(collection, json=document)
                assert response.status_code == 201, response.text
                assert response.json()["metadata"]["labels"]["cloudcoil.dev/admitted"] == "yes"
                assert ("validate", "CREATE", False) in calls
                update = response.json()
                update["spec"]["message"] = "forbidden"
                response = await test_config.async_client.put(f"{collection}/example", json=update)
                assert response.status_code == 403, response.text
                update["spec"]["message"] = "updated"
                update["metadata"]["labels"] = {}
                response = await test_config.async_client.put(f"{collection}/example", json=update)
                assert response.status_code == 200, response.text
                assert response.json()["spec"]["message"] == "updated"
                assert response.json()["metadata"]["labels"]["cloudcoil.dev/admitted"] == "yes"
                assert old_messages == ["allowed", "allowed"]
                assert ("mutate", "UPDATE", False) in calls
            finally:
                for config_url in reversed(configured):
                    response = await test_config.async_client.delete(config_url)
                    response.raise_for_status()
