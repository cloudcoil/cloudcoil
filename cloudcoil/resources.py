import importlib
import inspect
import pkgutil
import sys
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    Callable,
    Generic,
    Iterator,
    Literal,
    Type,
    TypeVar,
    overload,
)

import yaml
from pydantic import ConfigDict, Field, create_model, model_validator

from cloudcoil._context import context
from cloudcoil.apimachinery import ListMeta, ObjectMeta, Status
from cloudcoil.errors import ResourceNotFound
from cloudcoil.pydantic import BaseModel

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


DEFAULT_PAGE_LIMIT = 50
WatchEvent = Literal["ADDED", "MODIFIED", "DELETED", "ERROR", "BOOKMARK"]
WaitPredicate = Callable[[WatchEvent, "Resource"], bool]


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
    api_version: Annotated[Any | None, Field(alias="apiVersion")]
    kind: Any | None

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

    @property
    def resource_version(self) -> str | None:
        if self.metadata is None:
            return None
        return self.metadata.resource_version

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

    def save(self, dry_run: bool = False) -> Self:
        try:
            self.fetch()
        except ResourceNotFound:
            return self.create(dry_run=dry_run)
        else:
            return self.update(dry_run=dry_run)

    async def async_save(self, dry_run: bool = False) -> Self:
        try:
            await self.async_fetch()
        except ResourceNotFound:
            return await self.async_create(dry_run=dry_run)
        else:
            return await self.async_update(dry_run=dry_run)

    @classmethod
    def delete(
        cls,
        name: str,
        namespace: str | None = None,
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self | Status:
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
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self | Status:
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
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self | Status:
        config = context.active_config
        return config.client_for(self.__class__, sync=True).remove(
            self,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
        )

    async def async_remove(
        self,
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
    ) -> Self | Status:
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

    @classmethod
    def delete_all(
        cls,
        namespace: str | None = None,
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> "ResourceList[Self]":
        config = context.active_config
        return config.client_for(cls, sync=True).delete_all(
            namespace=namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
            label_selector=label_selector,
            field_selector=field_selector,
        )

    @classmethod
    async def async_delete_all(
        cls,
        namespace: str | None = None,
        dry_run: bool = False,
        propagation_policy: Literal["orphan", "background", "foreground"] | None = None,
        grace_period_seconds: int | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> "ResourceList[Self]":
        config = context.active_config
        return await config.client_for(cls, sync=False).delete_all(
            namespace=namespace,
            dry_run=dry_run,
            propagation_policy=propagation_policy,
            grace_period_seconds=grace_period_seconds,
            label_selector=label_selector,
            field_selector=field_selector,
        )

    @classmethod
    def watch(
        cls,
        namespace: str | None = None,
        all_namespaces: bool = False,
        field_selector: str | None = None,
        label_selector: str | None = None,
        resource_version: str | None = None,
    ) -> Iterator[tuple[WatchEvent, "Self"]]:
        config = context.active_config
        return config.client_for(cls, sync=True).watch(
            namespace=namespace,
            all_namespaces=all_namespaces,
            field_selector=field_selector,
            label_selector=label_selector,
            resource_version=resource_version,
        )

    @classmethod
    async def async_watch(
        cls,
        namespace: str | None = None,
        all_namespaces: bool = False,
        field_selector: str | None = None,
        label_selector: str | None = None,
        resource_version: str | None = None,
    ) -> AsyncGenerator[tuple[WatchEvent, "Self"], None]:
        config = context.active_config
        return config.client_for(cls, sync=False).watch(
            namespace=namespace,
            all_namespaces=all_namespaces,
            field_selector=field_selector,
            label_selector=label_selector,
            resource_version=resource_version,
        )

    @overload
    def wait_for(
        self,
        predicate: WaitPredicate,
        /,
        timeout: float | None = None,
    ) -> None: ...

    @overload
    def wait_for(
        self,
        predicate: dict[
            str,
            WaitPredicate,
        ],
        /,
        timeout: float | None = None,
    ) -> str: ...

    def wait_for(self, predicate, timeout=None):
        config = context.active_config
        client = config.client_for(self.__class__, sync=True)
        if not self.name:
            raise ValueError("Resource name must be set to wait for it")
        if isinstance(predicate, dict):
            return client.wait_for(self, predicate, timeout=timeout)
        assert isinstance(predicate, Callable)
        client.wait_for(self, {"predicate": predicate}, timeout=timeout)
        return None

    @overload
    async def async_wait_for(
        self,
        predicate: WaitPredicate,
        /,
        timeout: float | None = None,
    ) -> None: ...

    @overload
    async def async_wait_for(
        self,
        predicate: dict[
            str,
            WaitPredicate,
        ],
        /,
        timeout: float | None = None,
    ) -> str: ...

    async def async_wait_for(
        self,
        predicate,
        timeout=None,
    ):
        config = context.active_config
        client = config.client_for(self.__class__, sync=False)
        if not self.name:
            raise ValueError("Resource name must be set to wait for it")
        if isinstance(predicate, dict):
            return await client.wait_for(self, predicate, timeout=timeout)
        assert isinstance(predicate, Callable)
        await client.wait_for(self, {"predicate": predicate}, timeout=timeout)
        return None


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
        return len(self.items) + (self.metadata.remaining_item_count or 0)


class _Scheme:
    _registry: dict[GVK, Type[Resource]] = {}
    _registered_modules: set[str] = set()
    _initialized = False

    @classmethod
    def _register(cls, kind: Type[Resource]) -> None:
        cls._registry[kind.gvk()] = kind
        cls._registry[kind.gvk().model_copy(update={"api_version": ""})] = kind

    @classmethod
    def _register_all(cls, kinds: list[Type[Resource]]) -> None:
        for kind in kinds:
            cls._register(kind)

    @classmethod
    def _discover(cls, module: str | ModuleType) -> None:
        def import_and_check_module(module_name: str):
            try:
                module = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Resource) and obj != Resource:
                        cls._registered_modules.add(module_name)
                        cls._register(obj)
            except Exception as e:
                print(f"Error importing module {module_name}: {e}")

        if isinstance(module, str):
            package = importlib.import_module(module)
        else:
            package = module

        for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            import_and_check_module(module_name)

    @classmethod
    def _get(cls, gvk: GVK) -> Type[Resource]:
        if gvk not in cls._registry:
            raise ValueError(f"Resource kind '{gvk}' not registered")
        return cls._registry[gvk]

    @classmethod
    def get(cls, kind: str, api_version: str = "") -> Type[Resource]:
        cls._initialize()
        return cls._registry[GVK(api_version=api_version, kind=kind)]

    @classmethod
    def _namespace_packages(cls, base_package: str = "cloudcoil.models") -> set[str]:
        packages = set()
        package_paths: set[Path] = set()
        for path in map(Path, sys.path):
            if not path.exists():
                continue
            package_path = path.joinpath(*base_package.split("."))
            if package_path.exists():
                package_paths.add(package_path)
        for package_path in package_paths:
            try:
                subdirs = [d for d in package_path.iterdir() if d.is_dir()]
            except OSError:
                continue
            for subdir in subdirs:
                packages.add(f"{base_package}.{subdir.name}")
        return packages

    @classmethod
    def _initialize(cls) -> None:
        if cls._initialized:
            return
        packages = cls._namespace_packages()
        for package in sorted(packages, key=lambda p: (p != "cloudcoil.models.kubernetes", p)):
            cls._discover(package)
        entrypoints = entry_points(group="cloudcoil_models")
        for entrypoint in entrypoints:
            cls._discover(entrypoint.value)
        cls._initialized = True


@overload
def parse(obj: list[dict]) -> list[Resource]: ...


@overload
def parse(obj: dict) -> Resource: ...


def parse(obj: dict | list[dict]) -> Resource | list[Resource]:
    if isinstance(obj, list):
        return [parse(o) for o in obj]
    resource = Resource.model_validate(obj)
    if not resource.api_version or not resource.kind:
        raise ValueError("Missing apiVersion or kind")
    kind = _Scheme.get(api_version=resource.api_version, kind=resource.kind)
    return kind.model_validate(obj)


@overload
def parse_file(path: str | Path, load_all: Literal[True]) -> list[Resource]: ...


@overload
def parse_file(path: str | Path, load_all: Literal[False]) -> Resource: ...


def parse_file(path: str | Path, load_all: bool = False) -> list[Resource] | Resource:
    if not load_all:
        return parse(yaml.safe_load(Path(path).read_text()))
    return parse(list(yaml.safe_load_all(Path(path).read_text())))


def get_model(kind: str, *, api_version: str = "") -> Type[Resource]:
    return _Scheme.get(kind=kind, api_version=api_version)


class Unstructured(Resource):
    model_config = ConfigDict(extra="allow")

    def __init__(self, **data):
        super().__init__(**data)
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        # Also update the model data
        object.__setattr__(self, key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    @property
    def raw(self) -> dict:
        return self._data


def get_dynamic_resource(kind: str, api_version: str) -> Type[Unstructured]:
    return create_model(
        f"Dynamic{kind}",
        api_version=(Literal[api_version], Field(alias="apiVersion", default=api_version)),
        kind=(Literal[kind], Field(default=kind)),
        __base__=Unstructured,
    )
