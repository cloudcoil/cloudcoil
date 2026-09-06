"""Manager-owned informer sharing with exact subscription compatibility."""

from typing import Any, cast

from cloudcoil.caching._informer import AsyncInformer
from cloudcoil.caching._types import InformerOptions
from cloudcoil.client import Config
from cloudcoil.client._api_client import AsyncAPIClient
from cloudcoil.resources import Resource


class _InformerPool:
    """Prepare all subscribers before any watch starts; one lifetime per manager."""

    def __init__(self) -> None:
        self._informers: dict[tuple[Config, type[Resource], str], AsyncInformer[Any]] = {}

    def get[T: Resource](
        self, config: Config, client: AsyncAPIClient[T], options: InformerOptions
    ) -> AsyncInformer[T]:
        namespace: str | None = options.namespace or client.default_namespace
        if not client.namespaced or options.all_namespaces:
            namespace = None
        options = options.model_copy(
            update={
                "namespace": namespace,
                "all_namespaces": options.all_namespaces if client.namespaced else False,
            }
        )
        key = (config, client.kind, options.model_dump_json())
        if key not in self._informers:
            self._informers[key] = AsyncInformer(client, options)
        return cast(AsyncInformer[T], self._informers[key])

    @property
    def count(self) -> int:
        return len(self._informers)

    async def stop(self) -> None:
        for informer in reversed(list(self._informers.values())):
            await informer._stop()
