import sys
from typing import Any, Callable, Dict, Generic, List, TypeVar

if sys.version_info >= (3, 11):
    from typing import Self as Self
else:
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
    _attrs: Dict[str, Any] = {}

    def _set(self, key: str, value: Any) -> Self:
        builder = self.__class__()
        builder._attrs = self._attrs | {key: value}
        return builder


class GenericListBuilder(pydantic.BaseModel, Generic[T, TBuilder]):
    _list: List[T] = []

    @property
    def base_class(self) -> type[T]:
        return self.__pydantic_generic_metadata__["args"][0]

    def add(self, value_or_callback: Callable[[TBuilder], TBuilder] | T) -> "Self":
        output = self.__class__()
        if callable(value_or_callback):
            value = value_or_callback(self.base_class.builder()).build()  # type: ignore
        else:
            value = value_or_callback
        output._list = self._list + [value]
        return output

    def build(self) -> List[T]:
        return self._list
