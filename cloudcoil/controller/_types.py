"""Typed reconciliation inputs and outcomes."""

import math
from dataclasses import dataclass

from cloudcoil.resources import Resource


@dataclass(frozen=True)
class ResourceKey:
    """Identity within a controller's primary resource kind; None is cluster scope."""

    name: str
    namespace: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A resource key needs a name")

    @classmethod
    def from_resource(cls, resource: Resource) -> "ResourceKey":
        if not resource.name:
            raise ValueError("A resource key needs metadata.name")
        return cls(resource.name, resource.namespace)


@dataclass(frozen=True)
class Request[T: Resource]:
    """Latest cached state at worker dispatch, copied so mutation cannot corrupt the cache.

    resource=None means the key is absent from the watched scope (deleted or no
    longer selected). It is not a deletion proof for destructive external cleanup;
    use a finalizer and a live API read for that. Reads are eventually consistent.
    """

    key: ResourceKey
    resource: T | None

    @property
    def name(self) -> str:
        return self.key.name

    @property
    def namespace(self) -> str | None:
        return self.key.namespace


@dataclass(frozen=True)
class Result:
    """Successful reconciliation; optionally schedule another pass in seconds."""

    requeue_after: float | None = None

    def __post_init__(self) -> None:
        if self.requeue_after is not None and (
            not math.isfinite(self.requeue_after) or self.requeue_after < 0
        ):
            raise ValueError("requeue_after must be finite and nonnegative")


class TerminalError(Exception):
    """Do not retry this failure; a later event or resync can still reconcile the key."""
