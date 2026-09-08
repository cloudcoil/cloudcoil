"""Per-reconciliation operations exposed to decorated handlers."""

from typing import Literal

from cloudcoil.caching._reader import CachedResources
from cloudcoil.client import AsyncAPIClient
from cloudcoil.resources import Resource

from ._types import Request


class Context[T: Resource]:
    """Explicit clients and reporting for one primary resource.

    Status and Events are queued; ensure and live clients perform I/O immediately.
    Context instances belong to one pass and must not be stored on the controller.
    """

    def __init__(self, request: Request[T]) -> None:
        self._request = request

    @property
    def resource(self) -> T:
        return self._request.object

    @property
    def namespace(self) -> str | None:
        return self._request.namespace

    async def client[U: Resource](self, resource: type[U]) -> AsyncAPIClient[U]:
        return await self._request.client(resource)

    async def get[U: Resource](
        self, resource: type[U], name: str, *, namespace: str | None = None
    ) -> U:
        """Read live, defaulting to the primary namespace."""
        client = await self.client(resource)
        return await client.get(name, namespace=namespace)

    def cached[U: Resource](self, resource: type[U]) -> CachedResources[U]:
        return self._request.cached(resource)

    async def ensure[U: Resource](self, desired: U) -> U:
        return await self._request.ensure(desired)

    def set_status(self, **changes: object) -> None:
        self._request.set_status(**changes)

    def condition(
        self, name: str, status: bool | Literal["Unknown"], *, reason: str, message: str = ""
    ) -> None:
        if name in self._request._report.reserved:
            raise ValueError(f"Condition {name!r} is managed by the controller")
        self._request.condition(name, status, reason=reason, message=message)

    def event(
        self, reason: str, message: str, *, type: Literal["Normal", "Warning"] = "Normal"
    ) -> None:
        """Queue a bounded, best-effort Event, flushed after status persistence."""
        if not reason or type not in ("Normal", "Warning"):
            raise ValueError("Events need a reason and a Normal or Warning type")
        report = self._request._report
        if len(report.events) < 100:
            report.events.append((reason, message, type, report.action or "Reconcile"))
