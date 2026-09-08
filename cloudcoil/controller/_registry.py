"""Decorator registration and ordered execution over the controller runtime."""

import inspect
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from cloudcoil.errors import ResourceConflict, ResourceNotFound
from cloudcoil.resources import Resource

from ._context import Context
from ._mutations import ensure_finalizer, remove_finalizer
from ._status import ReconcileStatus, _status_model
from ._types import Request, Result, Wait


def _arity(handler: Callable[..., Any], *, predicate: bool = False) -> int:
    label = getattr(handler, "__name__", repr(handler))
    if inspect.iscoroutinefunction(handler) == predicate:
        raise TypeError(
            f"{label}: {'predicates must be synchronous' if predicate else 'handlers must be async'}"
        )
    parameters = list(inspect.signature(handler).parameters.values())
    if len(parameters) not in (1, 2) or any(
        p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in parameters
    ):
        raise TypeError(f"{label}: use (resource) or (resource, ctx)")
    return len(parameters)


def _refs(value: object | tuple[object, ...] | None) -> tuple[object, ...]:
    return () if value is None else value if isinstance(value, tuple) else (value,)


def _ordered(nodes: list[Any], *, label: str) -> list[Any]:
    """Require a unique topological order; import order never resolves ambiguity."""
    identities = {id(node.identity): node for node in nodes}
    if len(identities) != len(nodes):
        raise ValueError(f"Duplicate {label} handler")
    remaining = list(nodes)
    completed: set[int] = set()
    ordered = []
    for node in nodes:
        for dependency in node.dependencies:
            if id(dependency) not in identities:
                raise ValueError(f"Unknown {label} dependency for {node.name}")
    while remaining:
        ready = [n for n in remaining if all(id(d) in completed for d in n.dependencies)]
        if not ready:
            raise ValueError(f"Cycle in {label} dependencies")
        if len(ready) != 1:
            names = ", ".join(n.name for n in ready)
            raise ValueError(f"Ambiguous {label} order: {names}; declare dependencies")
        node = ready[0]
        ordered.append(node)
        completed.add(id(node.identity))
        remaining.remove(node)
    return ordered


@dataclass
class _Handler:
    function: Callable[..., Any]
    arity: int

    @classmethod
    def build(cls, function: Callable[..., Any], *, predicate: bool = False) -> "_Handler":
        return cls(function, _arity(function, predicate=predicate))

    def call(self, request: Request[Any]) -> Any:
        if self.arity == 1:
            return self.function(request.object)
        return self.function(request.object, Context(request))


@dataclass
class _Branch:
    handler: _Handler
    predicate: _Handler
    dependencies: tuple[object, ...]

    @property
    def identity(self) -> object:
        return self.handler.function

    @property
    def name(self) -> str:
        return self.handler.function.__name__


class _Branches:
    def __init__(self, check: Callable[[], None]) -> None:
        self._check = check
        self.branches: list[_Branch] = []
        self.fallback: _Handler | None = None

    def case[F: Callable[..., Any]](
        self, *, when: Callable[..., bool], after: object | tuple[object, ...] | None = None
    ) -> Callable[[F], F]:
        predicate = _Handler.build(when, predicate=True)

        def register(function: F) -> F:
            self._check()
            self.branches.append(_Branch(_Handler.build(function), predicate, _refs(after)))
            return function

        return register

    def otherwise[F: Callable[..., Any]](self) -> Callable[[F], F]:
        def register(function: F) -> F:
            self._check()
            if self.fallback is not None:
                raise ValueError("Only one otherwise handler may be registered")
            self.fallback = _Handler.build(function)
            return function

        return register

    @property
    def populated(self) -> bool:
        return bool(self.branches or self.fallback)

    def validate(self) -> list[_Branch]:
        if self.fallback is None:
            raise ValueError("Cases require an otherwise handler")
        return _ordered(self.branches, label="case")

    def select(self, request: Request[Any]) -> _Handler:
        for branch in self.validate():
            request._report.action = branch.name
            matches = branch.predicate.call(request)
            if type(matches) is not bool:
                if inspect.iscoroutine(matches):
                    matches.close()
                raise TypeError("Case predicates must return bool")
            if matches:
                return branch.handler
        assert self.fallback is not None
        return self.fallback


class StageScope[T: Resource]:
    """One automatically executed stage, containing a handler or first-match cases.

    Usually created through Controller.stage(). A decorator returns the original
    function, preserving its signature; a named scope can register case handlers.
    """

    def __init__(
        self,
        registry: "Registry[T]",
        name: str | None,
        condition: str,
        depends: object | tuple[object, ...] | None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", condition) or condition == "Ready":
            raise ValueError("Stage condition must be an identifier other than Ready")
        self.registry = registry
        self.name = name or condition
        self.condition = condition
        self.dependencies = _refs(depends)
        self.handler: _Handler | None = None
        self.identity: object = self
        self._branches = _Branches(self._check_cases)

    def __call__[F: Callable[..., Any]](self, function: F) -> F:
        self.registry.check()
        if self.handler is not None or self._branches.populated:
            raise ValueError("A stage has one handler or cases, not both")
        self.handler = _Handler.build(function)
        self.identity = function
        return function

    def _check_cases(self) -> None:
        self.registry.check()
        if self.handler is not None:
            raise ValueError("A stage has one handler or cases, not both")

    def case[F: Callable[..., Any]](
        self, *, when: Callable[..., bool], after: object | tuple[object, ...] | None = None
    ) -> Callable[[F], F]:
        return self._branches.case(when=when, after=after)

    def otherwise[F: Callable[..., Any]](self) -> Callable[[F], F]:
        return self._branches.otherwise()

    def validate(self) -> None:
        if self.handler is None:
            self._branches.validate()


class Registry[T: Resource]:
    def __init__(self, resource: type[T], report_status: bool | None = None) -> None:
        self.resource = resource
        self.handler: _Handler | None = None
        self.stages: list[StageScope[T]] = []
        self.branches = _Branches(self.check)
        self.finalizer: tuple[str, _Handler] | None = None
        self.every: float | None = None
        self.frozen = False
        if report_status is None:
            try:
                report_status = issubclass(
                    _status_model(resource.model_construct()), ReconcileStatus
                )
            except TypeError:
                report_status = False
        self.report_status = report_status

    def check(self) -> None:
        if self.frozen:
            raise RuntimeError("Register handlers before running the controller")

    def reconcile[F: Callable[..., Any]](self, *, every: float | None = None) -> Callable[[F], F]:
        if every is not None and (
            isinstance(every, bool) or not math.isfinite(every) or every <= 0
        ):
            raise ValueError("every must be finite and positive")

        def register(function: F) -> F:
            self.check()
            if self.handler is not None:
                raise ValueError("Only one reconcile handler may be registered")
            self.handler = _Handler.build(function)
            self.every = every
            return function

        return register

    def stage(
        self,
        name: str | None = None,
        *,
        condition: str,
        depends: object | tuple[object, ...] | None = None,
    ) -> StageScope[T]:
        self.check()
        stage = StageScope(self, name, condition, depends)
        self.stages.append(stage)
        return stage

    def finalize[F: Callable[..., Any]](self, key: str) -> Callable[[F], F]:
        if not key or "/" not in key:
            raise ValueError("Use a qualified finalizer name such as example.com/cleanup")

        def register(function: F) -> F:
            self.check()
            if self.finalizer is not None:
                raise ValueError("Use one finalizer handler and compose cleanup explicitly")
            self.finalizer = (key, _Handler.build(function))
            return function

        return register

    def validate(self, *, freeze: bool = False) -> list[StageScope[T]]:
        modes = bool(self.handler) + bool(self.stages) + self.branches.populated
        if modes != 1:
            raise ValueError("Register exactly one entrypoint: reconcile, stages, or cases")
        if self.report_status:
            model = _status_model(self.resource.model_construct())
            if not issubclass(model, ReconcileStatus):
                raise TypeError("Automatic reporting requires a ReconcileStatus subclass")
            model()
        names = [s.condition for s in self.stages]
        if len(set(names)) != len(names):
            raise ValueError("Stage conditions must be unique")
        if len({s.name for s in self.stages}) != len(self.stages):
            raise ValueError("Stage names must be unique")
        ordered = _ordered(self.stages, label="stage")
        for stage in ordered:
            stage.validate()
        if self.branches.populated:
            self.branches.validate()
        if freeze:
            self.frozen = True
        return ordered

    async def _finalize(self, request: Request[T]) -> bool:
        """Return true when deletion consumes the pass; publish a fresh write baseline."""
        obj = request.object
        if self.finalizer is None:
            return bool(obj.metadata and obj.metadata.deletion_timestamp)
        key, handler = self.finalizer
        if not obj.metadata or not obj.metadata.uid or not obj.name:
            raise ValueError("Finalizers require a fetched resource with UID")
        client = await request.client(self.resource)
        try:
            current = await client.get(obj.name, obj.namespace)
        except ResourceNotFound:
            return True
        if not current.metadata or current.metadata.uid != obj.metadata.uid:
            raise ResourceConflict("Resource was replaced before finalization", status_code=409)
        if not current.metadata or not current.metadata.deletion_timestamp:
            current = await ensure_finalizer(current, key, config=request.config)
        # Preserve the independent dispatch baseline after our own live write.
        request._report.baseline = current.model_copy(deep=True)
        request._report.current = current
        if current.metadata and current.metadata.deletion_timestamp:
            if key in (current.metadata.finalizers or []):
                request._report.pending = ["Finalize"]
                request._report.action = "Finalize"
                returned = await handler.call(request)
                if isinstance(returned, Wait):
                    raise returned
                if returned is not None:
                    raise TypeError("Finalizers return None after cleanup, or raise Wait")
                await remove_finalizer(current, key, config=request.config)
                # Removing a finalizer may delete the object immediately: no status write follows.
                request._report.dirty = False
            return True
        return False

    def _outcome(
        self,
        request: Request[T],
        condition: str,
        *,
        wait: Wait | None = None,
        reason: str = "Reconciled",
    ) -> None:
        report = request._report
        message = wait.message if wait else f"{report.action} is up to date"
        reason = wait.reason if wait else reason
        if report.managed:
            request.condition(
                condition,
                wait is None,
                reason=reason,
                message=message,
                event=True,
                action=report.action,
            )
            if wait is not None:
                for pending in report.pending[1:]:
                    request.condition(pending, "Unknown", reason="DependencyNotReady")
                if condition != "Ready":
                    request.condition("Ready", False, reason=reason, message=message)
        else:
            Context(request).event(reason, message)

    async def __call__(self, request: Request[T]) -> T | Result | None:
        ordered = self.validate(freeze=True)
        if request.resource is None:
            return None
        try:
            if await self._finalize(request):
                return None
        except Wait as wait:
            Context(request).event(wait.reason, wait.message)
            return Result(requeue_after=wait.requeue_after)
        report = request._report
        report.managed = self.report_status
        report.stage_conditions = bool(ordered)
        report.pending = [s.condition for s in ordered] if ordered else ["Reconcile"]
        report.reserved = {"Ready", *report.pending} if self.report_status else set()
        if self.report_status:
            request.set_status(
                observed_generation=request.object.metadata.generation
                if request.object.metadata
                else None
            )
        if ordered:
            for stage in ordered:
                report.action = stage.name
                try:
                    handler = stage.handler or stage._branches.select(request)
                    report.action = handler.function.__name__
                    returned = await handler.call(request)
                    if isinstance(returned, Wait):
                        raise returned
                    if returned is not None:
                        raise TypeError("Stage handlers return None, or raise Wait")
                except Wait as wait:
                    self._outcome(request, stage.condition, wait=wait)
                    return Result(requeue_after=wait.requeue_after)
                self._outcome(
                    request,
                    stage.condition,
                    reason=report.action if stage.handler is None else "Reconciled",
                )
                report.pending.pop(0)
            self._outcome(request, "Ready")
            return None
        report.action = "Reconcile"
        try:
            handler = self.handler or self.branches.select(request)
            report.action = handler.function.__name__
            returned = await handler.call(request)
            if isinstance(returned, Wait):
                raise returned
            if returned is not None and not isinstance(returned, (self.resource, Result)):
                raise TypeError("Reconcile handlers return their resource, Result, or None")
        except Wait as wait:
            self._outcome(request, "Ready", wait=wait)
            return Result(requeue_after=wait.requeue_after)
        self._outcome(
            request, "Ready", reason=report.action if self.handler is None else "Reconciled"
        )
        report.pending.clear()
        if self.every is not None and not (
            isinstance(returned, Result) and returned.requeue_after is not None
        ):
            return Result(
                resource=returned.resource if isinstance(returned, Result) else returned,
                requeue_after=self.every,
            )
        return cast(T | Result | None, returned)
