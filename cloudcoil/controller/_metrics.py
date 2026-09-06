"""Manager-local, bounded-cardinality Prometheus metrics without dependencies."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._manager import Manager

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_OUTCOMES = ("success", "error", "terminal", "cancelled")


@dataclass(frozen=True)
class ControllerStatus:
    """Immutable local snapshot; counts reset when a controller is recreated."""

    ready: bool
    queued: int
    processing: int
    delayed: int
    successes: int
    errors: int
    terminal_errors: int
    cancellations: int
    duration_seconds: float


@dataclass
class _ReconcileMetrics:
    outcomes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_OUTCOMES, 0))
    buckets: list[int] = field(default_factory=lambda: [0] * len(_BUCKETS))
    duration: float = 0.0

    def observe(self, outcome: str, duration: float) -> None:
        self.outcomes[outcome] += 1
        self.duration += duration
        for index, bound in enumerate(_BUCKETS):
            if duration <= bound:
                self.buckets[index] += 1


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _render(manager: "Manager") -> str:
    lines: list[str] = []

    def metric(name: str, kind: str, help_text: str, values: list[tuple[str, int | float]]) -> None:
        name = f"cloudcoil_{name}"
        lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"))
        lines.extend(f"{name}{labels} {value}" for labels, value in values)

    metric(
        "manager_healthy",
        "gauge",
        "Manager lifecycle is running without fatal failure.",
        [("", int(manager.healthy))],
    )
    metric(
        "manager_ready",
        "gauge",
        "Manager holds leadership if enabled and all controllers are synced.",
        [("", int(manager.ready))],
    )
    metric(
        "manager_informers",
        "gauge",
        "Distinct manager-owned informer subscriptions.",
        [("", manager.informer_count)],
    )
    election = manager.leader_election
    metric(
        "leader_election_held",
        "gauge",
        "Lease held within the local renewal deadline; zero when disabled.",
        [("", int(election is not None and election.is_leader))],
    )
    metric(
        "leader_election_acquisitions_total",
        "counter",
        "Successful leadership acquisitions.",
        [("", election._acquisitions if election else 0)],
    )
    metric(
        "leader_election_renewal_failures_total",
        "counter",
        "Transient failed renewal attempts.",
        [("", election._renewal_failures if election else 0)],
    )
    statuses = [
        (f'{{controller="{_label(name)}"}}', controller.status)
        for name, controller in zip(manager._names, manager._controllers, strict=True)
    ]
    for suffix, attribute, description in (
        ("ready", "ready", "Controller watches synced and workers running."),
        (
            "queue_depth",
            "queued",
            "Keys waiting for an available worker; excludes processing and delays.",
        ),
        ("active_workers", "processing", "Keys currently being reconciled."),
        ("delayed_keys", "delayed", "Keys with a pending retry or scheduled requeue."),
    ):
        metric(
            f"controller_{suffix}",
            "gauge",
            description,
            [(labels, int(getattr(status, attribute))) for labels, status in statuses],
        )
    outcomes: list[tuple[str, int | float]] = []
    for name, controller in zip(manager._names, manager._controllers, strict=True):
        outcomes.extend(
            (f'{{controller="{_label(name)}",result="{outcome}"}}', count)
            for outcome, count in controller._metrics.outcomes.items()
        )
    metric(
        "controller_reconciles_total",
        "counter",
        "Completed reconcile attempts by result, including cancellation.",
        outcomes,
    )
    name = "cloudcoil_controller_reconcile_duration_seconds"
    lines.extend(
        (
            f"# HELP {name} Reconcile attempt duration including errors and cancellation.",
            f"# TYPE {name} histogram",
        )
    )
    for label, controller in zip(manager._names, manager._controllers, strict=True):
        labels = f'controller="{_label(label)}"'
        stats = controller._metrics
        for bound, count in zip(_BUCKETS, stats.buckets, strict=True):
            lines.append(f'{name}_bucket{{{labels},le="{bound}"}} {count}')
        count = sum(stats.outcomes.values())
        lines.extend(
            (
                f'{name}_bucket{{{labels},le="+Inf"}} {count}',
                f"{name}_count{{{labels}}} {count}",
                f"{name}_sum{{{labels}}} {stats.duration}",
            )
        )
    return "\n".join(lines) + "\n"
