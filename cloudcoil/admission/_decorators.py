"""Admission policy metadata attached to Resource class methods."""

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ._types import Operation


@dataclass(frozen=True)
class _AdmissionMethod:
    mutation: bool
    path: str | None
    operations: tuple[Operation, ...]
    subresource: str
    timeout_seconds: int
    failure_policy: Literal["Fail", "Ignore"]


def _decorate[**P, R](
    options: _AdmissionMethod,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def decorate(handler: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not inspect.iscoroutinefunction(handler):
            raise TypeError(
                "Admission handlers must be async; put @classmethod/@staticmethod outermost"
            )
        if hasattr(handler, "__cloudcoil_admission__"):
            raise ValueError("An admission method can declare only one policy")
        handler.__cloudcoil_admission__ = options  # type: ignore[attr-defined]
        return handler

    return decorate


def mutating[**P, R](
    *,
    path: str | None = None,
    operations: Sequence[Operation] = ("CREATE", "UPDATE"),
    subresource: str = "",
    timeout_seconds: int = 5,
    failure_policy: Literal["Fail", "Ignore"] = "Fail",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Mark an async Resource class/static method that returns an edited resource.

    The bound method takes AdmissionRequest and optionally an injected AsyncAPIClient.
    Register the model explicitly with AdmissionWebhook.register before serving.
    """
    return _decorate(
        _AdmissionMethod(
            True, path, tuple(operations), subresource, timeout_seconds, failure_policy
        )
    )


def validating[**P, R](
    *,
    path: str | None = None,
    operations: Sequence[Operation] = ("CREATE", "UPDATE"),
    subresource: str = "",
    timeout_seconds: int = 5,
    failure_policy: Literal["Fail", "Ignore"] = "Fail",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Mark an async Resource class/static method; raise AdmissionDenied to reject."""
    return _decorate(
        _AdmissionMethod(
            False, path, tuple(operations), subresource, timeout_seconds, failure_policy
        )
    )


def _methods(
    model: type[Any],
) -> list[tuple[str, Callable[..., Awaitable[Any]], _AdmissionMethod, bool]]:
    # Ordinary Python shadowing applies even when an override is not decorated.
    members: dict[str, Any] = {}
    for base in reversed(model.__mro__):
        members.update(vars(base))
    result = []
    for name, member in members.items():
        function = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
        options = getattr(function, "__cloudcoil_admission__", None)
        if options is None:
            continue
        if not isinstance(member, (classmethod, staticmethod)):
            raise TypeError(f"{model.__name__}.{name} needs @classmethod or @staticmethod")
        handler = getattr(model, name)
        parameters = list(inspect.signature(handler).parameters.values())
        if len(parameters) not in (1, 2) or any(
            param.kind not in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
            for param in parameters
        ):
            raise TypeError(f"{model.__name__}.{name} must take request and optionally client")
        result.append((name, handler, options, len(parameters) == 2))
    return result
