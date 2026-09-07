"""Read-only, copied snapshots from an explicitly registered async informer."""

from collections.abc import Mapping

from cloudcoil.resources import Resource

from ._informer import AsyncInformer


class CachedResources[T: Resource]:
    """Local get/list with no API fallback; values are independent deep copies.

    Missing objects return None. An unsynced or stopped informer raises instead
    of presenting an empty cache as authoritative. Lists cover only the watched
    scope, are eventually consistent, and have no server pagination tokens.
    """

    def __init__(self, informer: AsyncInformer[T], namespace: str | None = None) -> None:
        self._informer = informer
        self._namespace = namespace

    def _check(self) -> None:
        if not self._informer._has_synced():
            raise RuntimeError("Informer is not running and synced")
        if self._informer._watch._error is not None:
            raise RuntimeError("Informer watch failed") from self._informer._watch._error

    def get(self, name: str, namespace: str | None = None) -> T | None:
        self._check()
        namespace = (namespace or self._namespace) if self._informer._client.namespaced else None
        if self._informer._client.namespaced and namespace is None:
            raise ValueError("Specify a namespace for a namespaced cache lookup")
        obj = self._informer.get(name, namespace)
        return obj.model_copy(deep=True) if obj is not None else None

    def list(
        self,
        namespace: str | None = None,
        *,
        all_namespaces: bool = False,
        labels: Mapping[str, str] | None = None,
    ) -> list[T]:
        """List cached objects; labels is an AND of exact label matches.

        all_namespaces means all namespaces in this informer's configured scope,
        not an expansion of its watch. Filtering scans the in-memory snapshot.
        """
        self._check()
        if all_namespaces and namespace is not None:
            raise ValueError("namespace and all_namespaces are mutually exclusive")
        target = (
            None
            if all_namespaces or not self._informer._client.namespaced
            else namespace or self._namespace
        )
        if self._informer._client.namespaced and target is None and not all_namespaces:
            raise ValueError("Specify namespace or all_namespaces=True")
        return [
            obj.model_copy(deep=True)
            for obj in self._informer.list(namespace=target)
            if not labels
            or all(
                obj.metadata and (obj.metadata.labels or {}).get(key) == value
                for key, value in labels.items()
            )
        ]
