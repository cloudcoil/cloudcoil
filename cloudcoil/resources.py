import sys
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, TypeVar

from cloudcoil.apimachinery import ListMeta, ObjectMeta

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import yaml
from pydantic import ConfigDict, Field, model_validator

from cloudcoil._context import context
from cloudcoil._pydantic import BaseModel

DEFAULT_PAGE_LIMIT = 50


class GVK(BaseModel):
    api_version: Annotated[str, Field(alias="apiVersion")]
    kind: str
    model_config = ConfigDict(frozen=True)

    @property
    def group(self) -> str:
        if self.api_version is None:
            raise ValueError("api_version is not set")
        return self.api_version.split("/")[0]

    @property
    def version(self) -> str:
        if self.api_version is None:
            raise ValueError("api_version is not set")
        return self.api_version.split("/")[1]


class BaseResource(BaseModel):
    api_version: Annotated[str | None, Field(alias="apiVersion")]
    kind: str | None

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


class Resource(BaseResource):
    metadata: ObjectMeta | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        path = Path(path)
        return cls.model_validate(yaml.safe_load(path.read_text()))

    @property
    def name(self) -> str | None:
        if self.metadata is None:
            return None
        return self.metadata.name

    @name.setter
    def name(self, value: str):
        if self.metadata is None:
            self.metadata = ObjectMeta(name=value)
        else:
            self.metadata.name = value

    @property
    def namespace(self) -> str | None:
        if self.metadata is None:
            return None
        return self.metadata.namespace

    @namespace.setter
    def namespace(self, value: str):
        if self.metadata is None:
            self.metadata = ObjectMeta(namespace=value)
        else:
            self.metadata.namespace = value

    @classmethod
    def get(cls, name: str, namespace: str | None = None) -> Self:
        config = context.active_config
        return config.client_for(cls, sync=True).get(name, namespace)

    @classmethod
    async def async_get(cls, name: str, namespace: str | None = None) -> Self:
        config = context.active_config
        return await config.client_for(cls, sync=False).get(name, namespace)

    def fetch(self) -> Self:
        config = context.active_config
        if self.name is None:
            raise ValueError("Resource name is not set")
        return config.client_for(self.__class__, sync=True).get(self.name, self.namespace)

    async def async_fetch(self) -> Self:
        config = context.active_config
        if self.name is None:
            raise ValueError("Resource name is not set")
        return await config.client_for(self.__class__, sync=False).get(self.name, self.namespace)

    def create(self, dry_run: bool = False) -> Self:
        config = context.active_config
        return config.client_for(self.__class__, sync=True).create(self, dry_run=dry_run)

    async def async_create(self, dry_run: bool = False) -> Self:
        config = context.active_config
        return await config.client_for(self.__class__, sync=False).create(self, dry_run=dry_run)

    def update(self, dry_run: bool = False) -> Self:
        config = context.active_config
        return config.client_for(self.__class__, sync=True).update(self, dry_run=dry_run)

    async def async_update(self, dry_run: bool = False) -> Self:
        config = context.active_config
        return await config.client_for(self.__class__, sync=False).update(self, dry_run=dry_run)

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

    @classmethod
    def list(
        cls,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: None | str = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> "ResourceList[Self]":
        config = context.active_config
        return config.client_for(cls, sync=True).list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            continue_=continue_,
            field_selector=field_selector,
            label_selector=label_selector,
            limit=limit,
        )

    @classmethod
    async def async_list(
        cls,
        namespace: str | None = None,
        all_namespaces: bool = False,
        continue_: None | str = None,
        field_selector: str | None = None,
        label_selector: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> "ResourceList[Self]":
        config = context.active_config
        return await config.client_for(cls, sync=False).list(
            namespace=namespace,
            all_namespaces=all_namespaces,
            continue_=continue_,
            field_selector=field_selector,
            label_selector=label_selector,
            limit=limit,
        )


T = TypeVar("T", bound=Resource)


class ResourceList(BaseResource, Generic[T]):
    metadata: ListMeta | None = None
    items: list[T] = []
    _next_page_params: dict[str, Any] = {}

    @property
    def resource_class(self) -> type[T]:
        return self.__pydantic_generic_metadata__["args"][0]

    @model_validator(mode="after")
    def _validate_gvk(self):
        assert issubclass(self.resource_class, Resource)
        if self.api_version != self.resource_class.gvk().api_version:
            raise ValueError(f"api_version must be {self.resource_class.gvk().api_version}")
        if self.kind != self.resource_class.gvk().kind + "List":
            raise ValueError(f"kind must be {self.resource_class.gvk().kind + 'List'}")
        return self

    def has_next_page(self) -> bool:
        return bool(self.metadata and self.metadata.remaining_item_count)

    def get_next_page(self) -> "ResourceList[T]":
        config = context.active_config
        return config.client_for(self.resource_class, sync=True).list(**self._next_page_params)

    async def async_get_next_page(self) -> "ResourceList[T]":
        config = context.active_config
        return await config.client_for(self.resource_class, sync=False).list(
            **self._next_page_params
        )

    def __iter__(self):
        resource_list = self
        while True:
            for item in resource_list.items:
                yield item
            if not resource_list.has_next_page():
                break
            resource_list = resource_list.get_next_page()

    async def __aiter__(self):
        resource_list = self
        while True:
            for item in resource_list.items:
                yield item
            if not resource_list.has_next_page():
                break
            resource_list = await resource_list.async_get_next_page()

    def __len__(self):
        return len(self.items) + self.metadata.remaining_item_count
