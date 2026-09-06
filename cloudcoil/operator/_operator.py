"""One definition for operator installation and process lifecycle."""

import argparse
import asyncio
import math
import os
import signal
from collections.abc import Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from cloudcoil.admission import AdmissionWebhook
from cloudcoil.admission._decorators import _methods
from cloudcoil.client import Config
from cloudcoil.controller import Controller, HealthServer, LeaderElection, Manager
from cloudcoil.crd import CRD, _resource_options
from cloudcoil.resources import Resource

from ._install import install
from ._manifests import RBACRule, build_manifests
from ._server import _HTTPS, WebhookServer


class Operator:
    """Describe, install, and run controllers and resource-local admission policies.

    Construction and manifest generation are offline. Config is created lazily;
    an explicitly passed Config remains owned by its caller. Installation uses
    the caller's privileges; generated runtime RBAC never grants CRD/RBAC setup
    privileges implicitly. Declare extra RBAC rules for application API calls.
    """

    def __init__(
        self,
        name: str,
        *controllers: Controller[Any],
        resources: Sequence[type[Resource] | CRD] = (),
        namespace: str | None = None,
        config: Config | None = None,
        rules: Sequence[RBACRule] = (),
        webhook: WebhookServer | None = None,
        leader_election: LeaderElection | bool | None = None,
        health: HealthServer | None = None,
    ) -> None:
        namespace = namespace or (
            config.namespace if config else os.environ.get("CLOUDCOIL_NAMESPACE", "default")
        )
        self.name = name
        self.namespace = namespace
        self.controllers = tuple(controllers)
        self.rules = tuple(rules)
        self.webhook = webhook
        leader_election = (
            LeaderElection(name) if leader_election is True else leader_election or None
        )
        self.leader_election = leader_election
        self.health = health
        self.config = config
        if config is not None and config.namespace != namespace:
            raise ValueError("Config.namespace must match Operator.namespace")
        self.crds: tuple[CRD, ...]
        definitions: dict[type[Resource], CRD] = {}
        for item in resources:
            definition = item if isinstance(item, CRD) else CRD(item)
            if definition.resource in definitions:
                raise ValueError("A resource cannot be registered twice")
            definitions[definition.resource] = definition
        for controller in controllers:
            if controller.resource not in definitions and _resource_options(controller.resource):
                definitions[controller.resource] = CRD(controller.resource)
            if controller.config is not None and controller.config is not config:
                raise ValueError("Operator controllers must share the operator Config")
        if leader_election and leader_election.config not in (None, config):
            raise ValueError("Operator leader election must share the operator Config")
        self.crds = tuple(definitions.values())
        self._models = tuple(crd.resource for crd in self.crds if _methods(crd.resource))
        if self._models and webhook is None:
            raise ValueError("Resources with admission methods require webhook=WebhookServer(...)")
        if webhook is not None and not self._models:
            raise ValueError("A webhook server needs resource-local admission methods")
        if not controllers and webhook is None:
            raise ValueError("An operator needs controllers or webhooks")
        self.manager: Manager | None = None
        self._used = False
        self._running = False
        self._serving = False
        self._failure: BaseException | None = None
        self._ready = asyncio.Event()
        self._finished = asyncio.Event()
        # Fail early on ambiguous resource scope/plural and invalid RBAC settings.
        self.manifests(include_webhooks=False)

    def _admission(self, config: Config | None = None) -> AdmissionWebhook:
        admission = AdmissionWebhook(config=config)._register_models(
            self._models, require_config=config is not None
        )
        if set(admission._routes) & {"/readyz", "/controllers/readyz", "/metrics"}:
            raise ValueError("Admission paths conflict with operator health/metrics endpoints")
        return admission

    def manifests(
        self,
        *,
        image: str | None = None,
        command: Sequence[str] | None = None,
        replicas: int = 1,
        include_webhooks: bool = True,
    ) -> list[dict[str, Any]]:
        """Return fresh CRD/RBAC/Service/Deployment/admission manifests, offline.

        image enables a Deployment; command replaces its container entry point.
        TLS Secrets and namespaces must already exist. include_webhooks=False
        exports the CRD/RBAC foundation without admission registration or hosting.
        """
        if image and self.webhook and not include_webhooks:
            raise ValueError(
                "A Deployment for this operator requires its webhook TLS configuration"
            )
        return build_manifests(
            name=self.name,
            namespace=self.namespace,
            controllers=self.controllers,
            crds=self.crds,
            rules=self.rules,
            leader_election=self.leader_election,
            admission=self._admission() if include_webhooks and self._models else None,
            webhook=self.webhook if include_webhooks else None,
            image=image,
            command=command,
            replicas=replicas,
        )

    def to_yaml(self, **options: Any) -> str:
        """Serialize manifests for review, kubectl, or GitOps."""
        return yaml.safe_dump_all(self.manifests(**options), sort_keys=False)

    @asynccontextmanager
    async def _configuration(self):
        owned = self.config is None
        config = self.config if self.config is not None else Config(namespace=self.namespace)
        try:
            yield config
        finally:
            if owned:
                try:
                    await config.async_client.aclose()
                finally:
                    await asyncio.to_thread(config.client.close)

    async def install(
        self,
        *,
        image: str | None = None,
        command: Sequence[str] | None = None,
        replicas: int = 1,
        include_webhooks: bool = True,
        timeout: float = 120,
        force: bool = False,
    ) -> None:
        """Apply desired objects, establish CRDs, and enable webhooks after rollout.

        Existing objects are updated with server-side apply; ownership conflicts
        fail unless force=True. A failure leaves already applied objects in place
        for inspection and retry. No resources are deleted or rolled back.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Installation timeout must be finite and positive")
        if include_webhooks and self.webhook and image is None:
            raise ValueError(
                "Installing webhooks requires image=... to wait for a serving Deployment; "
                "use include_webhooks=False to install only CRDs and RBAC"
            )
        manifests = self.manifests(
            image=image, command=command, replicas=replicas, include_webhooks=include_webhooks
        )
        async with self._configuration() as config:
            await install(
                config,
                manifests,
                field_manager=f"cloudcoil-{self.name}",
                timeout=timeout,
                force=force,
                wait_deployment=image is not None,
            )

    @property
    def ready(self) -> bool:
        """Admission readiness on every replica; controller readiness is separate."""
        return (
            self.healthy
            and self._ready.is_set()
            and (self.webhook is not None or (self.manager is not None and self.manager.ready))
        )

    @property
    def healthy(self) -> bool:
        return (
            self._running
            and self._failure is None
            and (self.webhook is None or self._serving)
            and (self.manager is None or self.manager.healthy)
        )

    async def wait_ready(self, timeout: float = 30) -> None:
        async with asyncio.timeout(timeout):
            while not self.ready:
                if self._failure is not None:
                    raise self._failure
                if self._finished.is_set():
                    raise RuntimeError("Operator stopped before becoming ready")
                await asyncio.sleep(0.01)

    def _application(self, admission: AdmissionWebhook):
        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            if scope["type"] == "http" and scope.get("path") in (
                "/readyz",
                "/healthz",
                "/controllers/readyz",
                "/metrics",
            ):
                path = scope["path"]
                if path == "/metrics":
                    code, body = 200, self.manager.metrics() if self.manager else ""
                else:
                    good = self.ready if path == "/readyz" else self.healthy
                    if path == "/controllers/readyz":
                        good = self.manager is not None and self.manager.ready
                    code, body = (200, "ok\n") if good else (503, "not ready\n")
                await send(
                    {
                        "type": "http.response.start",
                        "status": code,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": body.encode()})
                return
            await admission(scope, receive, send)

        return app

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        """Serve admission on every replica and run the manager until stopped.

        Installation is an explicit earlier step. Workers start after discovery;
        manager leader election does not gate webhook serving. Embedded use does
        not replace signal handlers; main() supplies SIGINT/SIGTERM shutdown.
        """
        if self._used:
            raise RuntimeError("Operator instances can only run once")
        self._used = True
        stop = stop if stop is not None else asyncio.Event()
        component_stop = asyncio.Event()
        server: _HTTPS | None = None
        tasks: list[asyncio.Task[Any]] = []

        async def shutdown(exc_type: Any, exception: BaseException | None, traceback: Any) -> bool:
            self._ready.clear()
            component_stop.set()
            errors: list[BaseException] = []
            try:
                if server:
                    await server.close()
            except Exception as error:
                errors.append(error)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                for outcome in outcomes:
                    if (
                        isinstance(outcome, BaseException)
                        and not isinstance(outcome, asyncio.CancelledError)
                        and outcome is not exception
                        and all(outcome is not error for error in errors)
                    ):
                        errors.append(outcome)
                self._serving = False
                self._running = False
            if errors:
                if exception is not None and not isinstance(exception, asyncio.CancelledError):
                    errors.insert(0, exception)
                if len(errors) == 1:
                    raise errors[0]
                raise BaseExceptionGroup("Operator failed while stopping components", errors)
            return False

        async def run_components(config: Config) -> None:
            nonlocal server
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(config)
                stack.push_async_exit(shutdown)
                self._running = True
                admission = self._admission(config)
                if self.controllers:
                    self.manager = Manager(
                        *self.controllers,
                        config=config,
                        leader_election=self.leader_election,
                        health=self.health,
                    )
                if self.webhook:
                    server = _HTTPS(self._application(admission), self.webhook)
                    await server.start()
                    self._serving = True
                    assert server.task is not None
                    tasks.append(server.task)
                if self.manager:
                    tasks.append(asyncio.create_task(self.manager.run(stop=component_stop)))
                    await asyncio.sleep(0)
                self._ready.set()
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
                if not stop.is_set():
                    raise RuntimeError("An operator component stopped unexpectedly")

        runtime: asyncio.Task[None] | None = None
        stopped: asyncio.Task[bool] | None = None
        try:
            if stop.is_set():
                return
            async with self._configuration() as config:
                if config.namespace != self.namespace:
                    raise ValueError("Config.namespace must match Operator.namespace")
                runtime = asyncio.create_task(run_components(config))
                stopped = asyncio.create_task(stop.wait())
                try:
                    done, _ = await asyncio.wait(
                        (runtime, stopped), return_when=asyncio.FIRST_COMPLETED
                    )
                    if runtime in done:
                        await runtime
                finally:
                    # Covers stop during discovery, TLS startup, and informer sync.
                    runtime.cancel()
                    stopped.cancel()
                    outcomes = await asyncio.gather(runtime, stopped, return_exceptions=True)
                    error = outcomes[0]
                    if isinstance(error, BaseException) and not isinstance(
                        error, asyncio.CancelledError
                    ):
                        raise error
        except BaseException as exc:
            self._failure = exc
            raise
        finally:
            self._finished.set()

    def main(self, argv: Sequence[str] | None = None) -> None:
        """Shared ``manifests``, ``install``, and ``run`` command-line entry point."""
        parser = argparse.ArgumentParser(description=f"Manage the {self.name} operator")
        commands = parser.add_subparsers(dest="command_name", required=True)
        for name in ("manifests", "install"):
            command = commands.add_parser(name)
            command.add_argument("--image")
            command.add_argument("--command", nargs="+", help="Container entry point before run")
            command.add_argument("--replicas", type=int, default=1)
            command.add_argument("--without-webhooks", action="store_true")
            command.add_argument(
                "--ca-file",
                default=os.environ.get("CLOUDCOIL_WEBHOOK_CA_FILE"),
                help="Public PEM CA for webhook registration (or CLOUDCOIL_WEBHOOK_CA_FILE)",
            )
            if name == "install":
                command.add_argument("--timeout", type=float, default=120)
                command.add_argument("--force", action="store_true")
        commands.add_parser("run")
        args = parser.parse_args(argv)
        if args.command_name == "run":
            asyncio.run(self._main_run())
        else:
            if args.ca_file:
                if self.webhook is None:
                    parser.error("--ca-file requires a webhook server")
                self.webhook = replace(self.webhook, ca_bundle=Path(args.ca_file).read_bytes())
            options = dict(
                image=args.image,
                command=args.command,
                replicas=args.replicas,
                include_webhooks=not args.without_webhooks,
            )
            if args.command_name == "manifests":
                print(self.to_yaml(**options), end="")
            else:
                asyncio.run(self.install(**options, timeout=args.timeout, force=args.force))

    async def _main_run(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        previous: dict[signal.Signals, Any] = {}
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.getsignal(sig)
                loop.add_signal_handler(sig, stop.set)
            await self.run(stop=stop)
        finally:
            for sig, handler in previous.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, handler)
