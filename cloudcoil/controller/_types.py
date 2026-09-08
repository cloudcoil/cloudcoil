"""Typed reconciliation inputs and outcomes."""

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from cloudcoil.caching._reader import CachedResources
from cloudcoil.resources import Resource

if TYPE_CHECKING:
    from cloudcoil.caching._informer import AsyncInformer
    from cloudcoil.client import AsyncAPIClient, Config

    from ._events import EventRecorder


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
    config: "Config | None" = None
    _informers: "dict[type[Resource], AsyncInformer[Any]]" = field(
        default_factory=dict, repr=False, compare=False
    )
    _events: "EventRecorder | None" = field(default=None, repr=False, compare=False)

    async def event(
        self, reason: str, message: str, *, type: Literal["Normal", "Warning"] = "Normal"
    ) -> bool:
        """Record a bounded, best-effort Kubernetes Event regarding this resource."""
        if self.resource is None or self._events is None:
            return False
        return await self._events.emit(
            self.resource, reason, message, type=type, config=self.config
        )

    def cached[U: Resource](self, resource: type[U]) -> CachedResources[U]:
        """Read the primary or a declared .owns/.watch informer, without I/O."""
        if resource not in self._informers:
            raise ValueError(f"{resource.__name__} is not watched by this controller")
        return CachedResources(cast("AsyncInformer[U]", self._informers[resource]), self.namespace)

    async def client[U: Resource](self, resource: type[U]) -> "AsyncAPIClient[U]":
        """A live client for any kind, sharing this operator's connection.

        Namespaced clients default to this request's namespace. Pass a namespace
        to client operations for cross-namespace reads. Clients share the Config
        lifetime and must not be closed by handlers.
        """
        return await resource.async_client(self.config, namespace=self.namespace, cached=False)

    async def ensure[U: Resource](self, desired: U) -> U:
        """Create or patch an owned child; omitted fields remain untouched.

        Defaults name and namespace from the parent. Refuses unrelated existing
        objects. Maps merge, lists replace, and explicit None removes a field.
        Child events are subscribed separately with Controller.owns(...).
        """
        from ._children import ensure

        if self.resource is None:
            raise ValueError("Cannot ensure a child for an absent parent")
        return await ensure(self.resource, desired, config=self.config)

    @property
    def name(self) -> str:
        return self.key.name

    @property
    def namespace(self) -> str | None:
        return self.key.namespace


@dataclass(frozen=True)
class Result:
    """Successful reconciliation; optionally persist a resource and schedule another pass.

    resource is a modified copy of this request's primary snapshot. The controller
    patches its differences before scheduling requeue_after. None performs no write.
    """

    requeue_after: float | None = None
    resource: Resource | None = None

    def __post_init__(self) -> None:
        if self.requeue_after is not None and (
            not math.isfinite(self.requeue_after) or self.requeue_after < 0
        ):
            raise ValueError("requeue_after must be finite and nonnegative")


class TerminalError(Exception):
    """Do not retry this failure; a later event or resync can still reconcile the key."""
