import sys
from typing import Any, Literal

from cloudcoil.apimachinery import ListMeta, ObjectMeta

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from pydantic import ConfigDict

from cloudcoil._pydantic import BaseModel
from cloudcoil.client._context import context


class GVK(BaseModel):
    api_version: str
    kind: str
    model_config = ConfigDict(frozen=True)

    @property
    def group(self) -> str:
        return self.api_version.split("/")[0]

    @property
    def version(self) -> str:
        return self.api_version.split("/")[1]


class BaseResource(BaseModel):
    api_version: Any
    kind: Any

    @classmethod
    def gvk(cls) -> GVK:
        fields = cls.model_fields
        if "api_version" not in fields:
            raise ValueError(f"Resource {cls} does not have an api_version field")
        if "kind" not in fields:
            raise ValueError(f"Resource {cls} does not have a kind field")
        api_version = fields["api_version"].default
        kind = fields["kind"].default
        return GVK(api_version=api_version, kind=kind)


class ResourceList(BaseResource):
    metadata: ListMeta | None = None


class Resource(BaseResource):
    metadata: ObjectMeta | None = None

    @property
    def name(self) -> str | None:
        if self.metadata is None:
            return None
        return self.metadata.name

    @property
    def namespace(self) -> str | None:
        if self.metadata is None:
            return None
        return self.metadata.namespace

    @classmethod
    def get(cls, name: str, namespace: str | None = None) -> Self:
        config = context.active_config
        return config.client_for(cls, sync=True).get(name, namespace)

    @classmethod
    async def async_get(cls, name: str, namespace: str | None = None) -> Self:
        config = context.active_config
        return await config.client_for(cls, sync=False).get(name, namespace)

    def create(self, namespace: str | None = None) -> Self:
        config = context.active_config
        return config.client_for(self.__class__, sync=True).create(self, namespace=namespace)

    async def async_create(self, namespace: str | None = None) -> Self:
        config = context.active_config
        return await config.client_for(self.__class__, sync=False).create(self, namespace=namespace)

    @classmethod
    def delete(
        cls,
        name: str,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self:
        config = context.active_config
        return config.client_for(cls, sync=True).delete(
            name,
            namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    @classmethod
    async def async_delete(
        cls,
        name: str,
        namespace: str | None = None,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self:
        config = context.active_config
        return await config.client_for(cls, sync=False).delete(
            name,
            namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    def remove(
        self,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self:
        config = context.active_config
        return config.client_for(self.__class__, sync=True).remove(
            self,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    async def async_remove(
        self,
        dry_run: bool = True,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self:
        config = context.active_config
        return await config.client_for(self.__class__, sync=False).remove(
            self,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )
