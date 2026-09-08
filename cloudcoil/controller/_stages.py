"""Small, level-based compositions over the ordinary controller runtime."""

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cloudcoil.resources import Resource

from ._status import ReconcileStatus, _status_model
from ._types import Request, Result, TerminalError, Wait

type Step[T: Resource] = Callable[[Request[T]], Awaitable[Wait | None]]
type Predicate[T: Resource] = Callable[[Request[T]], bool]


@dataclass(frozen=True)
class Stage[T: Resource]:
    """An idempotent action named by the condition it establishes."""

    name: str
    run: Step[T]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name) or len(self.name) > 128:
            raise ValueError("Stage name must be an identifier of at most 128 characters")
        if self.name == "Ready":
            raise ValueError("Ready is reserved for the aggregate condition")
        if not callable(self.run):
            raise TypeError("Stage run must be an async callable")


def _validate(resource: type[Resource], report_status: bool) -> None:
    if report_status:
        # Use a model-constructed shell only to inspect the declared status type.
        model = _status_model(resource.model_construct())
        if not issubclass(model, ReconcileStatus):
            raise TypeError(
                "Stages need a ReconcileStatus subclass; use report_status=False otherwise"
            )
        model()  # New objects need a status whose fields have defaults.


def _start[T: Resource](request: Request[T], names: list[str], report_status: bool) -> bool:
    obj = request.resource
    if obj is None or (obj.metadata and obj.metadata.deletion_timestamp):
        return False
    request._report.managed = report_status
    request._report.pending = names.copy()
    if report_status:
        request.set_status(observed_generation=obj.metadata.generation if obj.metadata else None)
    return True


async def _run[T: Resource](request: Request[T], stage: Stage[T]) -> Wait | None:
    result = await stage.run(request)
    if result is not None and not isinstance(result, Wait):
        raise TypeError("A stage must return None (continue) or Wait (stop this pass)")
    if request._report.managed:
        request.condition(
            stage.name,
            result is None,
            reason=result.reason if result else "Reconciled",
            message=result.message if result else f"{stage.name} is up to date",
            event=True,
        )
        if result is not None:
            for pending in request._report.pending[1:]:
                request.condition(pending, "Unknown", reason="DependencyNotReady")
            request.condition("Ready", False, reason=result.reason, message=result.message)
    if result is None:
        request._report.pending.pop(0)
    return result


def _done[T: Resource](request: Request[T], wait: Wait | None = None) -> Result:
    if wait is None and request._report.managed:
        request.condition(
            "Ready", True, reason="Reconciled", message="All required work is current", event=True
        )
    return Result(resource=request.object, requeue_after=wait.requeue_after if wait else None)


class Stages[T: Resource]:
    """Run stages in explicit order, stopping on waiting or failure.

    Every pass starts from the first stage, including when previously Ready.
    Conditions are observations, never checkpoints that skip drift repair.
    The controller persists status on waits/errors and applies its normal retries.
    """

    def __init__(self, *stages: Stage[T], report_status: bool = True) -> None:
        if not stages or any(not isinstance(stage, Stage) for stage in stages):
            raise ValueError("Stages requires one or more Stage values")
        if len({stage.name for stage in stages}) != len(stages):
            raise ValueError("Stage names must be unique")
        self.stages = stages
        self.report_status = report_status

    def _freeze(self, resource: type[T]) -> None:
        _validate(resource, self.report_status)

    async def __call__(self, request: Request[T]) -> Result | None:
        if not _start(request, [stage.name for stage in self.stages], self.report_status):
            return None
        for stage in self.stages:
            wait = await _run(request, stage)
            if wait is not None:
                return _done(request, wait)
        return _done(request)


@dataclass(frozen=True)
class _Case[T: Resource]:
    stage: Stage[T]
    when: Predicate[T]
    priority: int | None


class Cases[T: Resource]:
    """Register first-match cases on an instance before the controller starts.

    Without priorities, registration order is execution order. When priorities are
    supplied, every case must have a distinct integer priority (higher runs first).
    Predicates are synchronous, side-effect-free reads of current state. They are
    evaluated lazily; only the first matching action executes, even if it waits.
    """

    def __init__(self, *, report_status: bool = True) -> None:
        self.report_status = report_status
        self._cases: list[_Case[T]] = []
        self._otherwise: Stage[T] | None = None
        self._frozen = False

    def case(
        self, name: str, *, when: Predicate[T], priority: int | None = None
    ) -> Callable[[Step[T]], Step[T]]:
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
            raise ValueError("Case priority must be an integer")
        if not callable(when):
            raise TypeError("Case when must be a synchronous predicate")

        def register(run: Step[T]) -> Step[T]:
            self._check_name(name)
            if priority is not None and any(case.priority == priority for case in self._cases):
                raise ValueError("Case priorities must be unique; import order must not break ties")
            self._cases.append(_Case(Stage(name, run), when, priority))
            return run

        return register

    def otherwise(self, name: str) -> Callable[[Step[T]], Step[T]]:
        """Register the explicit fallback, which always follows all predicates."""

        def register(run: Step[T]) -> Step[T]:
            self._check_name(name)
            if self._otherwise is not None:
                raise ValueError("Only one otherwise case may be registered")
            self._otherwise = Stage(name, run)
            return run

        return register

    def _check_name(self, name: str) -> None:
        if self._frozen:
            raise RuntimeError("Register cases before running the controller")
        if any(case.stage.name == name for case in self._cases) or (
            self._otherwise is not None and self._otherwise.name == name
        ):
            raise ValueError("Case names must be unique")

    def _freeze(self, resource: type[T]) -> None:
        _validate(resource, self.report_status)
        if not self._cases and self._otherwise is None:
            raise ValueError("Register at least one case")
        if any(case.priority is not None for case in self._cases):
            if any(case.priority is None for case in self._cases):
                raise ValueError("Give every case a priority, or use registration order throughout")
            self._cases.sort(key=lambda case: case.priority or 0, reverse=True)
        self._frozen = True

    async def __call__(self, request: Request[T]) -> Result | None:
        if request.resource is None:
            return None
        if not self._frozen:
            self._freeze(type(request.object))
        names = [case.stage.name for case in self._cases]
        if self._otherwise is not None:
            names.append(self._otherwise.name)
        if not _start(request, names, self.report_status):
            return None
        selected = self._otherwise
        for case in self._cases:
            request._report.pending = [
                case.stage.name,
                *[name for name in names if name != case.stage.name],
            ]
            matches = case.when(request)
            if type(matches) is not bool:
                if inspect.iscoroutine(matches):
                    matches.close()
                raise TypeError("Case predicates must return bool and must not perform async I/O")
            if matches:
                selected = case.stage
                break
        if selected is None:
            raise TerminalError(
                "No case matched; register an otherwise handler if this is expected"
            )
        # Other cases do not claim a completed invariant on this pass.
        if self.report_status:
            for name in names:
                if name != selected.name:
                    request.condition(name, "Unknown", reason="NotSelected")
        request._report.pending = [selected.name]
        return _done(request, await _run(request, selected))
