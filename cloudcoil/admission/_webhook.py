"""Dependency-free ASGI admission application and matching Kubernetes manifests."""

import asyncio
import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError

from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

if TYPE_CHECKING:
    from cloudcoil.client import Config

from ._decorators import _methods
from ._mutation import mutation_patch
from ._types import AdmissionDenied, AdmissionRequest, Operation, UserInfo

logger = logging.getLogger(__name__)

type Mutator[T: Resource] = Callable[[AdmissionRequest[T]], Awaitable[T | None]]
type Validator[T: Resource] = Callable[[AdmissionRequest[T]], Awaitable[None]]
type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]


class _Kind(BaseModel):
    group: str
    version: str
    kind: str


class _Target(BaseModel):
    group: str
    version: str
    resource: str


class _Request(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True)

    uid: str = Field(min_length=1)
    kind: _Kind
    resource: _Target
    operation: Operation
    object: dict[str, Any] | None = None
    old_object: dict[str, Any] | None = Field(default=None, alias="oldObject")
    name: str = ""
    namespace: str = ""
    subresource: str = Field(default="", alias="subResource")
    dry_run: bool = Field(default=False, alias="dryRun")
    user_info: UserInfo = Field(default_factory=UserInfo, alias="userInfo")
    options: dict[str, Any] | None = None


class _Review(BaseModel):
    api_version: Literal["admission.k8s.io/v1"] = Field(alias="apiVersion")
    kind: Literal["AdmissionReview"]
    request: _Request


@dataclass(frozen=True)
class _Route:
    model: type[Resource]
    handler: Callable[[AdmissionRequest[Any]], Awaitable[Any]]
    mutation: bool
    path: str
    resource: str
    operations: tuple[Operation, ...]
    subresource: str
    scope: Literal["Namespaced", "Cluster", "*"]
    timeout_seconds: int
    failure_policy: Literal["Fail", "Ignore"]


def _dns(value: str, *, label: bool = False) -> None:
    parts = value.split(".")
    if (
        not value
        or len(value) > (63 if label else 253)
        or (label and len(parts) != 1)
        or any(
            len(part) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part)
            for part in parts
        )
    ):
        raise ValueError(f"Invalid DNS {'label' if label else 'subdomain'}: {value!r}")


class AdmissionWebhook:
    """Register typed async mutators/validators and serve them as an ASGI app.

    Use an ASGI server for HTTPS and deployment. Callbacks must be side-effect
    free. An explicit Config enables injected clients for lookups; returned
    mutations are applied by the API server. Register all routes before serving
    or generating configurations.
    """

    def __init__(
        self, *, config: "Config | None" = None, max_body_bytes: int = 4 * 1024 * 1024
    ) -> None:
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes < 1
        ):
            raise ValueError("max_body_bytes must be a positive integer")
        self._config = config
        self._max_body_bytes = max_body_bytes
        self._routes: dict[str, _Route] = {}

    def register(self, *models: type[Resource]) -> Self:
        """Register policies declared on @custom_resource models, atomically.

        Paths default to /{mutate|validate}/{group}/{version}/{plural}/{method}.
        The optional Config and its HTTP clients remain owned by the caller.
        Client-taking handlers require Config; no discovery occurs during registration.
        """
        return self._register_models(models, require_config=True)

    def _register_models(self, models: Sequence[type[Resource]], *, require_config: bool) -> Self:
        # Operator manifest generation can collect routes before loading credentials.
        from cloudcoil.crd import _resource_options

        staged = AdmissionWebhook(config=self._config, max_body_bytes=self._max_body_bytes)
        staged._routes = dict(self._routes)
        for model in models:
            options = _resource_options(model)
            if options is None:
                raise ValueError(
                    f"{model.__name__} needs @custom_resource(plural=...) for registration"
                )
            methods = _methods(model)
            if not methods:
                raise ValueError(f"{model.__name__} has no decorated admission methods")
            gvk = model.gvk()
            for name, handler, policy, needs_client in methods:
                if needs_client and self._config is None and require_config:
                    raise ValueError(f"{model.__name__}.{name} needs AdmissionWebhook(config=...)")

                # Capture each handler independently; route dispatch never closes over loop variables.
                def bind(
                    callback: Callable[..., Awaitable[Any]],
                    resource: type[Resource],
                    inject_client: bool,
                ) -> Callable[[AdmissionRequest[Any]], Awaitable[Any]]:
                    async def invoke(request: AdmissionRequest[Any]) -> Any:
                        if inject_client:
                            if self._config is None:
                                raise RuntimeError("Serving injected handlers requires Config")
                            client = await self._config.async_client_for(resource, cached=False)
                            if client.namespaced and request.namespace:
                                client.default_namespace = request.namespace
                            return await callback(request, client)
                        return await callback(request)

                    return invoke

                prefix = "mutate" if policy.mutation else "validate"
                # Dots in DNS groups are harmless path characters but our public route
                # validator deliberately uses a narrower alphabet, so encode as slashes.
                group_path = gvk.group.replace(".", "/")
                path = (
                    policy.path or f"/{prefix}/{group_path}/{gvk.version}/{options.plural}/{name}"
                )
                staged._register(
                    model,
                    bind(handler, model, needs_client),
                    policy.mutation,
                    path,
                    options.plural,
                    policy.operations,
                    policy.subresource,
                    options.scope,
                    policy.timeout_seconds,
                    policy.failure_policy,
                )
        self._routes = staged._routes
        return self

    def mutating[T: Resource](
        self,
        model: type[T],
        *,
        resource: str,
        path: str,
        operations: Sequence[Operation] = ("CREATE", "UPDATE"),
        subresource: str = "",
        scope: Literal["Namespaced", "Cluster", "*"] = "*",
        timeout_seconds: int = 5,
        failure_policy: Literal["Fail", "Ignore"] = "Fail",
    ) -> Callable[[Mutator[T]], Mutator[T]]:
        """Register a mutator that returns its edited resource, or None for no patch."""

        def register(handler: Mutator[T]) -> Mutator[T]:
            self._register(
                model,
                handler,
                True,
                path,
                resource,
                operations,
                subresource,
                scope,
                timeout_seconds,
                failure_policy,
            )
            return handler

        return register

    def validating[T: Resource](
        self,
        model: type[T],
        *,
        resource: str,
        path: str,
        operations: Sequence[Operation] = ("CREATE", "UPDATE"),
        subresource: str = "",
        scope: Literal["Namespaced", "Cluster", "*"] = "*",
        timeout_seconds: int = 5,
        failure_policy: Literal["Fail", "Ignore"] = "Fail",
    ) -> Callable[[Validator[T]], Validator[T]]:
        """Register a validator; return None to allow or raise AdmissionDenied."""

        def register(handler: Validator[T]) -> Validator[T]:
            self._register(
                model,
                handler,
                False,
                path,
                resource,
                operations,
                subresource,
                scope,
                timeout_seconds,
                failure_policy,
            )
            return handler

        return register

    def _register(
        self,
        model: type[Resource],
        handler: Callable[..., Awaitable[Any]],
        mutation: bool,
        path: str,
        resource: str,
        operations: Sequence[Operation],
        subresource: str,
        scope: Literal["Namespaced", "Cluster", "*"],
        timeout_seconds: int,
        failure_policy: Literal["Fail", "Ignore"],
    ) -> None:
        model.gvk()  # Fail early for models without a concrete GVK.
        field = model.model_fields["api_version"]
        if (field.serialization_alias or field.alias) != "apiVersion":
            raise ValueError("The resource api_version field needs Field(alias='apiVersion')")
        if (
            not re.fullmatch(r"/[a-zA-Z0-9/_-]+", path)
            or path in self._routes
            or path == "/healthz"
        ):
            raise ValueError(
                "Webhook paths must be unique absolute paths without query or escape characters"
            )
        if len(resource) > 63 or not re.fullmatch(r"[a-z](?:[-a-z0-9]*[a-z0-9])?", resource):
            raise ValueError("resource must be the exact lowercase Kubernetes resource plural")
        if subresource and not re.fullmatch(r"[a-z][a-z0-9]*", subresource):
            raise ValueError("subresource must be an exact lowercase subresource name")
        if (
            not operations
            or len(set(operations)) != len(operations)
            or any(op not in ("CREATE", "UPDATE", "DELETE") for op in operations)
        ):
            raise ValueError("operations must contain unique CREATE, UPDATE, or DELETE entries")
        if scope not in ("Namespaced", "Cluster", "*") or failure_policy not in ("Fail", "Ignore"):
            raise ValueError("Invalid webhook scope or failure policy")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 30
        ):
            raise ValueError("timeout_seconds must be an integer between 1 and 30")
        self._routes[path] = _Route(
            model,
            handler,
            mutation,
            path,
            resource,
            tuple(operations),
            subresource,
            scope,
            timeout_seconds,
            failure_policy,
        )

    def configurations(
        self,
        *,
        name: str,
        service_name: str,
        service_namespace: str,
        ca_bundle: bytes,
        service_port: int = 443,
    ) -> list[dict[str, Any]]:
        """Generate v1 webhook configurations from registered routes.

        ca_bundle is PEM bytes (not base64); Kubernetes needs a certificate valid
        for service_name.service_namespace.svc. This method only returns manifests.
        """
        _dns(name)
        _dns(service_name, label=True)
        _dns(service_namespace, label=True)
        if name.endswith(".static.k8s.io"):
            raise ValueError("The .static.k8s.io suffix is reserved by Kubernetes")
        if not isinstance(ca_bundle, bytes) or b"-----BEGIN CERTIFICATE-----" not in ca_bundle:
            raise ValueError("ca_bundle must contain PEM certificate bytes")
        if (
            isinstance(service_port, bool)
            or not isinstance(service_port, int)
            or not 1 <= service_port <= 65535
        ):
            raise ValueError("service_port must be an integer between 1 and 65535")
        configurations: list[dict[str, Any]] = []
        for mutation, kind in (
            (True, "MutatingWebhookConfiguration"),
            (False, "ValidatingWebhookConfiguration"),
        ):
            webhooks: list[dict[str, Any]] = []
            for index, route in enumerate(self._routes.values()):
                if route.mutation != mutation:
                    continue
                gvk = route.model.gvk()
                webhook_name = f"{'mutate' if mutation else 'validate'}-{index}.{name}"
                _dns(webhook_name)
                if webhook_name.count(".") < 2:
                    raise ValueError("name must include a domain, such as widgets.example.com")
                webhook: dict[str, Any] = {
                    "name": webhook_name,
                    "admissionReviewVersions": ["v1"],
                    "sideEffects": "None",
                    "failurePolicy": route.failure_policy,
                    "matchPolicy": "Exact",
                    "timeoutSeconds": route.timeout_seconds,
                    "clientConfig": {
                        "service": {
                            "name": service_name,
                            "namespace": service_namespace,
                            "path": route.path,
                            "port": service_port,
                        },
                        "caBundle": base64.b64encode(ca_bundle).decode("ascii"),
                    },
                    "rules": [
                        {
                            "apiGroups": [gvk.group],
                            "apiVersions": [gvk.version],
                            "resources": [
                                route.resource
                                + (f"/{route.subresource}" if route.subresource else "")
                            ],
                            "operations": list(route.operations),
                            "scope": route.scope,
                        }
                    ],
                }
                if mutation:
                    webhook["reinvocationPolicy"] = "Never"
                webhooks.append(webhook)
            if webhooks:
                configurations.append(
                    {
                        "apiVersion": "admissionregistration.k8s.io/v1",
                        "kind": kind,
                        "metadata": {"name": name},
                        "webhooks": webhooks,
                    }
                )
        return configurations

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            raise ValueError("AdmissionWebhook only supports HTTP and lifespan ASGI scopes")
        if scope.get("path") == "/healthz" and scope.get("method") == "GET":
            await self._respond(send, 200, {"status": "ok"})
            return
        route = self._routes.get(scope.get("path", ""))
        if route is None:
            await self._respond(send, 404, {"message": "Unknown webhook path"})
            return
        if scope.get("method") != "POST":
            await self._respond(send, 405, {"message": "Webhook requests require POST"})
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        if (
            headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            != b"application/json"
        ):
            await self._respond(send, 415, {"message": "Expected application/json"})
            return
        response_started = False

        async def respond(status: int, value: dict[str, Any]) -> None:
            nonlocal response_started
            response_started = True
            await self._respond(send, status, value)

        try:
            async with asyncio.timeout(route.timeout_seconds):
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    if message["type"] != "http.request":
                        raise ValueError("Unexpected ASGI request event")
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self._max_body_bytes:
                        await respond(413, {"message": "AdmissionReview exceeds max_body_bytes"})
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
                try:
                    # JSON parsers may accept NaN/Infinity; Kubernetes JSON does not.
                    payload = json.loads(body)
                    json.dumps(payload, allow_nan=False)
                    review = _Review.model_validate(payload)
                    self._check_request(route, review.request)
                except ValidationError, ValueError:
                    await respond(
                        400,
                        {"message": "Invalid or mismatched admission.k8s.io/v1 AdmissionReview"},
                    )
                    return
                try:
                    request = self._request(route, review.request)
                    request._config = self._config
                except ValidationError as error:
                    causes = [
                        {
                            "reason": "FieldValueInvalid",
                            "field": ".".join(str(part) for part in issue["loc"])[:256],
                            "message": issue["msg"][:256],
                        }
                        for issue in error.errors(
                            include_input=False, include_url=False, include_context=False
                        )[:20]
                    ]
                    await respond(
                        200,
                        {
                            "apiVersion": "admission.k8s.io/v1",
                            "kind": "AdmissionReview",
                            "response": {
                                "uid": review.request.uid,
                                "allowed": False,
                                "status": {
                                    "code": 422,
                                    "reason": "Invalid",
                                    "message": "Invalid resource: "
                                    + "; ".join(
                                        f"{cause['field']}: {cause['message']}"
                                        for cause in causes[:3]
                                    ),
                                    "details": {"causes": causes},
                                },
                            },
                        },
                    )
                    return
                # Keep the baseline and raw JSON separate from callback-owned data.
                before = request.resource.model_copy(deep=True) if request.resource else None
                response: dict[str, Any] = {"uid": request.uid, "allowed": True}
                try:
                    connected, result = await self._invoke(route, request, receive)
                    if not connected:
                        return
                    if result is not None:
                        if not route.mutation or not isinstance(result, route.model):
                            raise TypeError(
                                "Validators return None; mutators return their registered resource type or None"
                            )
                        if before is None or review.request.object is None:
                            raise ValueError(
                                "Cannot mutate an admission request without a current object"
                            )
                        patch = mutation_patch(review.request.object, before, result)
                        if patch:
                            response.update(
                                patchType="JSONPatch",
                                patch=base64.b64encode(
                                    json.dumps(
                                        patch, allow_nan=False, separators=(",", ":")
                                    ).encode()
                                ).decode("ascii"),
                            )
                except AdmissionDenied as denied:
                    response = {
                        "uid": request.uid,
                        "allowed": False,
                        "status": {
                            "code": denied.code,
                            "reason": denied.reason,
                            "message": str(denied),
                        },
                    }
                await respond(
                    200,
                    {
                        "apiVersion": "admission.k8s.io/v1",
                        "kind": "AdmissionReview",
                        "response": response,
                    },
                )
        except TimeoutError:
            if not response_started:
                await respond(504, {"message": "Admission webhook timed out"})
        except Exception:
            if response_started:
                raise
            logger.exception("Admission handler failed: path=%s", route.path)
            await respond(500, {"message": "Admission webhook failed"})

    @staticmethod
    async def _invoke(
        route: _Route, request: AdmissionRequest[Any], receive: Receive
    ) -> tuple[bool, Any]:
        async def invoke() -> Any:
            return await route.handler(request)

        async def disconnected() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    raise ValueError("Unexpected ASGI event after request body")

        handler = asyncio.create_task(invoke())
        disconnect = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((handler, disconnect), return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done:
                await disconnect
                return False, None
            return True, await handler
        finally:
            for task in (handler, disconnect):
                task.cancel()
            await asyncio.gather(handler, disconnect, return_exceptions=True)

    @staticmethod
    def _check_request(route: _Route, raw: _Request) -> None:
        gvk = route.model.gvk()
        if (raw.kind.group, raw.kind.version, raw.kind.kind) != (
            gvk.group,
            gvk.version,
            gvk.kind,
        ) or (raw.resource.group, raw.resource.version, raw.resource.resource) != (
            gvk.group,
            gvk.version,
            route.resource,
        ):
            raise ValueError("Admission kind or resource does not match this route")
        if raw.operation not in route.operations or raw.subresource != route.subresource:
            raise ValueError("Admission operation or subresource does not match this route")
        if (route.scope == "Namespaced" and not raw.namespace) or (
            route.scope == "Cluster" and raw.namespace
        ):
            raise ValueError("Admission namespace does not match this route's scope")
        if raw.operation == "DELETE":
            if raw.object is not None or raw.old_object is None:
                raise ValueError("DELETE needs oldObject and no object")
        elif (
            raw.object is None
            or (raw.operation == "CREATE" and raw.old_object is not None)
            or (raw.operation == "UPDATE" and raw.old_object is None)
        ):
            raise ValueError("Invalid object/oldObject for admission operation")
        for value in (raw.object, raw.old_object):
            if value is not None and (value.get("apiVersion"), value.get("kind")) != (
                gvk.api_version,
                gvk.kind,
            ):
                raise ValueError("Object GVK does not match this route")

    @staticmethod
    def _request(route: _Route, raw: _Request) -> AdmissionRequest[Any]:
        return AdmissionRequest[Any](
            uid=raw.uid,
            operation=raw.operation,
            resource=route.model.model_validate(deepcopy(raw.object))
            if raw.object is not None
            else None,
            old_resource=route.model.model_validate(deepcopy(raw.old_object))
            if raw.old_object is not None
            else None,
            name=raw.name,
            namespace=raw.namespace,
            subresource=raw.subresource,
            dry_run=raw.dry_run,
            user_info=raw.user_info.model_copy(deep=True),
            options=deepcopy(raw.options),
            raw_object=deepcopy(raw.object),
            raw_old_object=deepcopy(raw.old_object),
        )

    @staticmethod
    async def _respond(send: Send, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
