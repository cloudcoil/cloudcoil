"""Typed process and leadership lifecycle notifications."""

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, cast

from cloudcoil.controller._leader import LeaderElection, LeadershipLost


class LifecycleType(StrEnum):
    STARTUP = "startup"
    LEADERSHIP_ACQUIRED = "leadership_acquired"
    SHUTDOWN = "shutdown"
    LEADERSHIP_LOST = "leadership_lost"
    FAILURE = "failure"


@dataclass
class LifecycleEvent:
    """A per-scope event whose type/error are updated before lifespan cleanup.

    Read type inside the handler's finally block to distinguish normal shutdown,
    leadership loss, and failure. identity is populated for elected leaders.
    """

    type: LifecycleType
    scope: Literal["process", "leader"]
    identity: str | None = None
    error: BaseException | None = None


class Lifespans:
    def __init__(self, check: Callable[[], None]) -> None:
        self.check = check
        self.handlers: dict[str, tuple[Callable[..., AsyncIterator[None]], bool]] = {}

    def register[F: Callable[..., AsyncIterator[None]]](
        self, *, scope: Literal["process", "leader"] = "process"
    ) -> Callable[[F], F]:
        if scope not in ("process", "leader"):
            raise ValueError("Lifespan scope must be process or leader")

        def register(handler: F) -> F:
            self.check()
            if scope in self.handlers:
                raise ValueError(f"Only one {scope} lifespan; compose resources with async with")
            parameters = list(inspect.signature(handler).parameters.values())
            if (
                not inspect.isasyncgenfunction(handler)
                or len(parameters) > 1
                or any(
                    p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in parameters
                )
            ):
                raise TypeError(
                    "Lifespan must be an async generator taking optional LifecycleEvent"
                )
            self.handlers[scope] = (handler, bool(parameters))
            return cast(F, handler)

        return register

    @asynccontextmanager
    async def enter(
        self, scope: Literal["process", "leader"], leader: LeaderElection | None = None
    ) -> AsyncIterator[None]:
        registered = self.handlers.get(scope)
        if registered is None:
            yield
            return
        handler, accepts_event = registered
        event = LifecycleEvent(
            LifecycleType.STARTUP if scope == "process" else LifecycleType.LEADERSHIP_ACQUIRED,
            scope,
            leader.identity if leader is not None else None,
        )
        factory: Any = asynccontextmanager(handler)
        async with factory(*([event] if accepts_event else [])):
            try:
                yield
            except BaseException as error:
                failure = getattr(leader, "_failure", None)
                cause = (
                    failure
                    if isinstance(failure, LeadershipLost)
                    and isinstance(error, asyncio.CancelledError)
                    else error
                )
                event.error = cause
                if isinstance(cause, LeadershipLost):
                    event.type = LifecycleType.LEADERSHIP_LOST
                elif isinstance(cause, asyncio.CancelledError):
                    event.type = LifecycleType.SHUTDOWN
                    event.error = None
                else:
                    event.type = LifecycleType.FAILURE
                raise
            finally:
                if event.type in (LifecycleType.STARTUP, LifecycleType.LEADERSHIP_ACQUIRED):
                    event.type = LifecycleType.SHUTDOWN
