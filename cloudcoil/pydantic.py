import sys
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from pydantic import PrivateAttr

if sys.version_info >= (3, 11):
    from typing import Never as Never
    from typing import Self as Self
else:
    from typing_extensions import Never as Never
    from typing_extensions import Self as Self

import pydantic

T = TypeVar("T", bound=pydantic.BaseModel)
TBuilder = TypeVar("TBuilder", bound=pydantic.BaseModel)


class BaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
    )


class BaseBuilder(pydantic.BaseModel):
    _in_context: bool = False

    def build(self) -> Any:
        raise NotImplementedError


class BaseModelBuilder(BaseBuilder):
    _attrs: Dict[str, Any] = {}

    def _set(self, key: str, value: Any) -> Self:
        if self._in_context:
            self._attrs[key] = value
            return self
        builder = self.__class__()
        builder._attrs = self._attrs | {key: value}
        return builder


class GenericListBuilder(pydantic.BaseModel, Generic[T, TBuilder]):
    _list: List[T] = []

    @property
    def cls(self) -> type[T]:
        return self.__pydantic_generic_metadata__["args"][0]

    def add(self, value_or_callback: Callable[[TBuilder], TBuilder | T] | T) -> "Self":
        output = self.__class__()
        if callable(value_or_callback):
            result = value_or_callback(self.cls.builder())  # type: ignore
            if isinstance(result, self.cls):
                value = result
            else:
                value = result.build()  # type: ignore
        else:
            value = value_or_callback
        output._list = self._list + [value]
        return output

    def build(self) -> List[T]:
        return self._list


BuilderType = TypeVar("BuilderType", bound=BaseBuilder)


class BuilderContextBase(pydantic.BaseModel, Generic[BuilderType]):
    _builder: BuilderType = PrivateAttr()
    _parent_builder: Optional["BaseModelBuilder"] = PrivateAttr(default=None)
    _field_name: Optional[str] = PrivateAttr(default=None)

    def __enter__(self) -> BuilderType:
        return self._builder

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._parent_builder and self._field_name:
            self._parent_builder._set(self._field_name, self._builder.build())


class ListBuilderContext(pydantic.BaseModel, Generic[BuilderType]):
    _builders: List[BuilderType] = PrivateAttr(default_factory=list)
    _parent_builder: "BaseModelBuilder" = PrivateAttr()
    _field_name: str = PrivateAttr()

    def model_post_init(self, __context) -> None:
        self._builders = []

    def __enter__(self) -> "ListBuilderContext[BuilderType]":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        built_items = [builder.build() for builder in self._builders]
        self._parent_builder._set(self._field_name, built_items)

    def add(self) -> BuilderContextBase[BuilderType]:
        context = BuilderContextBase[BuilderType]()
        builder_class = self.__pydantic_generic_metadata__["args"][0]
        builder = builder_class()  # type: ignore
        context._builder = builder
        context._builder._in_context = True
        self._builders.append(builder)
        return context
