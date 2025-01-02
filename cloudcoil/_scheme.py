import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Type, overload

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import sys

import yaml

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points


from cloudcoil.resources import GVK, Resource


class _Scheme:
    def __init__(self):
        self._registry = {}
        self._registered_modules = set()

    def _register(self, kind: Type[Resource]) -> None:
        self._registry[kind.gvk()] = kind
        self._registry[kind.gvk().model_copy(update={"api_version": ""})] = kind

    def _register_all(self, kinds: list[Type[Resource]]) -> None:
        for kind in kinds:
            self._register(kind)

    def _discover(self, module: str | ModuleType) -> None:
        # Uses pkgutil to discover all modules in module_path recursively
        # and imports them
        # Then it looks for all classes that are subclasses of Resource
        # and registers them
        def import_and_check_module(module_name: str):
            try:
                module = importlib.import_module(module_name)
                # Get all members of the module
                for _, obj in inspect.getmembers(module):
                    # Check if object is a class and subclasses base_class
                    if inspect.isclass(obj) and issubclass(obj, Resource) and obj != Resource:
                        self._registered_modules.add(module_name)
                        self._register(obj)
            except Exception as e:
                print(f"Error importing module {module_name}: {e}")

        if isinstance(module, str):
            package = importlib.import_module(module)
        else:
            package = module

        # Walk through all modules in the package
        for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            import_and_check_module(module_name)

    def _get(self, gvk: GVK) -> Type[Resource]:
        if gvk not in self._registry:
            raise ValueError(f"Resource kind '{gvk}' not registered")
        return self._registry[gvk]

    @overload
    def parse(self, obj: list[dict]) -> list[Resource]: ...

    @overload
    def parse(self, obj: dict) -> Resource: ...

    def parse(self, obj: dict | list[dict]) -> Resource | list[Resource]:
        if isinstance(obj, list):
            return [self.parse(o) for o in obj]
        resource = Resource.model_validate(obj)
        if not resource.api_version or not resource.kind:
            raise ValueError("Missing apiVersion or kind")
        kind = self.get(resource.api_version, resource.kind)
        return kind.model_validate(obj)

    def get(self, kind: str, api_version: str = "") -> Type[Resource]:
        return self._registry[GVK(api_version=api_version, kind=kind)]

    def parse_file(self, path: str | Path) -> list[Resource] | Resource:
        return self.parse(yaml.safe_load(Path(path).read_text()))

    @classmethod
    def _get_default(cls: Type[Self]) -> Self:
        discovered_kinds = entry_points(group="cloudcoil_kinds")
        output = cls()
        for discovered_kind in discovered_kinds:
            output._discover(discovered_kind.load())
        return output


scheme = _Scheme._get_default()
