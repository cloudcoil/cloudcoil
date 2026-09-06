"""Optional, minimal HTTP diagnostics owned by the manager lifecycle."""

import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._manager import Manager


class HealthServer:
    """Serve GET /healthz, /readyz, and /metrics; opt in through Manager(health=...).

    Defaults to loopback. Bind host="0.0.0.0" for container probes. This is a plain
    HTTP diagnostics listener; protect access with your network configuration.
    Connections have bounded headers, a read deadline, and no keep-alive.
    """

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8080) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between 0 and 65535")
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._used = False
        self._closing = False

    @property
    def address(self) -> tuple[str, int] | None:
        """Bound host and port (including an assigned port=0), or None when stopped."""
        if self._server is None or not self._server.sockets:
            return None
        host, port, *_ = self._server.sockets[0].getsockname()
        return host, port

    async def _start(self, manager: "Manager") -> None:
        if self._used:
            raise RuntimeError("HealthServer instances can only run once")
        self._used = True

        def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            if self._closing or len(self._tasks) >= 128:
                writer.close()
                return
            task = asyncio.create_task(self._handle(manager, reader, writer))
            self._tasks.add(task)

            def completed(task: asyncio.Task[None]) -> None:
                # A connection can be cancelled before _handle enters its finally.
                writer.close()
                self._tasks.discard(task)

            task.add_done_callback(completed)

        self._server = await asyncio.start_server(connected, self.host, self.port, limit=8192)

    async def _handle(
        self, manager: "Manager", reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            code, body = HTTPStatus.BAD_REQUEST, "bad request\n"
            content_type = "text/plain; charset=utf-8"
            try:
                async with asyncio.timeout(5):
                    headers = await reader.readuntil(b"\r\n\r\n")
                first = headers.split(b"\r\n", 1)[0].split(b" ")
                if len(first) == 3 and first[2] in (b"HTTP/1.0", b"HTTP/1.1"):
                    method, path, _ = first
                    if method != b"GET":
                        code, body = HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed\n"
                    elif path == b"/healthz":
                        code = HTTPStatus.OK if manager.healthy else HTTPStatus.SERVICE_UNAVAILABLE
                        body = "ok\n" if manager.healthy else "unhealthy\n"
                    elif path == b"/readyz":
                        code = HTTPStatus.OK if manager.ready else HTTPStatus.SERVICE_UNAVAILABLE
                        body = "ok\n" if manager.ready else "not ready\n"
                    elif path == b"/metrics":
                        code, body = HTTPStatus.OK, manager.metrics()
                        content_type = "text/plain; version=0.0.4; charset=utf-8"
                    else:
                        code, body = HTTPStatus.NOT_FOUND, "not found\n"
            except asyncio.LimitOverrunError:
                code, body = HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, "headers too large\n"
            except TimeoutError:
                code, body = HTTPStatus.REQUEST_TIMEOUT, "request timeout\n"
            except asyncio.IncompleteReadError:
                pass
            payload = body.encode("utf-8")
            response = (
                f"HTTP/1.1 {code.value} {code.phrase}\r\n"
                f"Content-Type: {content_type}\r\nContent-Length: {len(payload)}\r\n"
                "Connection: close\r\nCache-Control: no-store\r\n"
                + ("Allow: GET\r\n" if code == HTTPStatus.METHOD_NOT_ALLOWED else "")
                + "\r\n"
            ).encode("ascii") + payload
            writer.write(response)
            async with asyncio.timeout(5):
                await writer.drain()
        except ConnectionError, TimeoutError:
            pass
        finally:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except ConnectionError, TimeoutError:
                pass

    async def _close(self) -> None:
        self._closing = True
        if self._server is not None:
            self._server.close()
            # Cancel clients before wait_closed, which may wait for active streams.
            tasks = list(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._server.wait_closed()
            self._server = None
