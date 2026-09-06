"""Optimistic controller mutations using live reads and narrow JSON patches."""

import inspect
from collections.abc import Callable

from cloudcoil._context import context
from cloudcoil.client import Config
from cloudcoil.errors import ResourceConflict
from cloudcoil.patches import diff
from cloudcoil.resources import Resource

from ._types import TerminalError


async def mutate[T: Resource](
    resource: T, change: Callable[[T], None], *, status: bool = False, config: Config | None = None
) -> T:
    """Fetch live state, edit a copy, and patch only changes with UID/version tests.

    A no-op issues no PATCH. The synchronous callback must only edit the copy and
    have no external side effects. Conflicts propagate to the reconcile retry loop,
    which will read fresh state on its next attempt. The supplied resource must have
    a UID; never apply work for a deleted object to a replacement with the same name.
    """
    if not resource.name or not resource.metadata or not resource.metadata.uid:
        raise ValueError("mutate requires a fetched resource with metadata.name and UID")
    config = config or context.active_config
    client = await config.async_client_for(type(resource), cached=False)
    current = await client.get(resource.name, resource.namespace)
    if not current.metadata or current.metadata.uid != resource.metadata.uid:
        raise ResourceConflict(
            "Resource was replaced; refusing to mutate the new UID", status_code=409
        )
    desired = current.model_copy(deep=True)
    callback: Callable[[T], object] = change
    result = callback(desired)
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError("Mutation callbacks edit in place and must return None")
    operations = diff(current, desired)
    if status and any(
        op["op"] != "test" and op["path"] != "/status" and not op["path"].startswith("/status/")
        for op in operations
    ):
        raise ValueError("A status mutation can only change status fields")
    if not operations:
        return current
    return await client.patch(current, operations, subresource="status" if status else None)


async def ensure_finalizer[T: Resource](
    resource: T, finalizer: str, *, config: Config | None = None
) -> T:
    """Persist this controller's finalizer before creating external resources.

    Refuses to add a missing finalizer once deletion has begun. Existing finalizers
    are preserved. Complete cleanup before calling remove_finalizer.
    """
    if not finalizer or "/" not in finalizer:
        raise ValueError("Use a qualified finalizer name such as example.com/cleanup")

    def change(obj: T) -> None:
        assert obj.metadata is not None
        existing = obj.metadata.finalizers or []
        if finalizer in existing:
            return
        if obj.metadata.deletion_timestamp is not None:
            raise TerminalError("Cannot add a finalizer after deletion has begun")
        obj.metadata.finalizers = [*existing, finalizer]

    return await mutate(resource, change, config=config)


async def remove_finalizer[T: Resource](
    resource: T, finalizer: str, *, config: Config | None = None
) -> T:
    """Remove only this finalizer after successful, idempotent external cleanup."""

    def change(obj: T) -> None:
        assert obj.metadata is not None
        existing = obj.metadata.finalizers or []
        if finalizer in existing:
            obj.metadata.finalizers = [value for value in existing if value != finalizer]

    return await mutate(resource, change, config=config)
