"""Optional HTTPS hosting for an operator's admission application."""

import asyncio
import math
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WebhookServer:
    """TLS files are provided by the deployment, typically from a mounted Secret.

    The certificate must cover ``<operator-name>.<namespace>.svc``. ``ca_bundle``
    contains public PEM certificates only; private keys never enter manifests.
    """

    ca_bundle: bytes = b""
    tls_secret: str = "operator-tls"
    certfile: str = "/var/run/cloudcoil/tls/tls.crt"
    keyfile: str = "/var/run/cloudcoil/tls/tls.key"
    host: str = "0.0.0.0"
    port: int = 9443
    service_port: int = 443
    startup_timeout: float = 30
    shutdown_timeout: float = 10

    def __post_init__(self) -> None:
        for port in (self.port, self.service_port):
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Webhook ports must be integers between 1 and 65535")
        for timeout in (self.startup_timeout, self.shutdown_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("Webhook timeouts must be finite and positive")


class _HTTPS:
    def __init__(self, app: Any, options: WebhookServer) -> None:
        try:
            import uvicorn
        except ImportError as exc:
            raise ImportError("HTTPS serving requires cloudcoil[operator]") from exc
        for path in (options.certfile, options.keyfile):
            if not Path(path).is_file():
                raise ValueError(f"Webhook TLS file does not exist: {path}")

        class Server(uvicorn.Server):
            def capture_signals(self) -> Any:
                # Operator.main owns signals; embedded async use leaves them alone.
                return nullcontext()

        self.server = Server(
            uvicorn.Config(
                app,
                host=options.host,
                port=options.port,
                ssl_certfile=options.certfile,
                ssl_keyfile=options.keyfile,
                lifespan="on",
                timeout_graceful_shutdown=math.ceil(options.shutdown_timeout),
                access_log=False,
            )
        )
        self.options = options
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async def serve() -> None:
            try:
                await self.server.serve()
            except SystemExit as exc:
                raise RuntimeError("Webhook server could not start") from exc

        self.task = asyncio.create_task(serve(), name="cloudcoil-webhooks")
        async with asyncio.timeout(self.options.startup_timeout):
            while not self.server.started:
                if self.task.done():
                    await self.task
                    raise RuntimeError("Webhook server stopped during startup")
                await asyncio.sleep(0.01)

    async def close(self) -> None:
        if self.task is None:
            return
        self.server.should_exit = True
        try:
            async with asyncio.timeout(self.options.shutdown_timeout + 1):
                await asyncio.shield(asyncio.gather(self.task, return_exceptions=True))
        except TimeoutError:
            self.task.cancel()
        finally:
            if not self.task.done():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
