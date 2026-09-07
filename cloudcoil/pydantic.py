from contextlib import AbstractContextManager
from types import UnionType
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    TypeVar,
    Union,
    get_args,
    get_origin,
)
from typing import Never as Never
from typing import Self as Self

import pydantic
from pydantic import PrivateAttr

UNSET = object()

T = TypeVar("T", bound=pydantic.BaseModel)
TBuilder = TypeVar("TBuilder", bound=pydantic.BaseModel)
BuiltModel = TypeVar("BuiltModel", bound=pydantic.BaseModel, default=Any)


class BaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(
        populate_by_name=True,
        validate_default=True,
        validate_assignment=True,
    )

    @classmethod
    def builder(cls) -> "BaseModelBuilder[Self]":
        """Build handwritten models using their Pydantic field definitions."""
        cls.model_rebuild()
        return _ModelBuilder[Self](cls)

    @classmethod
    def new(cls) -> "AbstractContextManager[BaseModelBuilder[Self]]":
        """Open a builder context, including nested model and model-list fields."""
        result = BuilderContextBase[BaseModelBuilder[Self]]()
        result._builder = cls.builder()
        return result

    @classmethod
    def list_builder(cls) -> "GenericListBuilder[Self, Any]":
        return GenericListBuilder[cls, Any]()  # type: ignore[valid-type]


class BaseBuilder(pydantic.BaseModel, Generic[BuiltModel]):
    _in_context: bool = False

    def build(self) -> BuiltModel:
        raise NotImplementedError


class BaseModelBuilder(BaseBuilder[BuiltModel]):
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
        return list(self._list)


BuilderType = TypeVar("BuilderType", bound=BaseBuilder)


class BuilderContextBase(pydantic.BaseModel, Generic[BuilderType]):
    _builder: BuilderType = PrivateAttr()
    _parent_builder: Optional["BaseModelBuilder"] = PrivateAttr(default=None)
    _field_name: Optional[str] = PrivateAttr(default=None)
    _list_builders: list[BuilderType] | None = PrivateAttr(default=None)

    def __enter__(self) -> BuilderType:
        self._builder._in_context = True
        return self._builder

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is None:
                if self._parent_builder is not None and self._field_name:
                    self._parent_builder._set(self._field_name, self._builder.build())
                if self._list_builders is not None:
                    self._list_builders.append(self._builder)
        finally:
            self._builder._in_context = False


class ListBuilderContext(pydantic.BaseModel, Generic[BuilderType]):
    _builders: List[BuilderType] = PrivateAttr(default_factory=list)
    _parent_builder: "BaseModelBuilder" = PrivateAttr()
    _field_name: str = PrivateAttr()
    _factory: Callable[[], BuilderType] | None = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._builders = []

    def __enter__(self) -> "ListBuilderContext[BuilderType]":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            return
        built_items = [builder.build() for builder in self._builders]
        self._parent_builder._set(self._field_name, built_items)

    def add(self) -> BuilderContextBase[BuilderType]:
        context = BuilderContextBase[BuilderType]()
        builder_class = self.__pydantic_generic_metadata__["args"][0]
        builder = self._factory() if self._factory is not None else builder_class()  # type: ignore
        context._builder = builder
        context._builder._in_context = True
        context._list_builders = self._builders
        return context


def _model_field_type(annotation: Any) -> tuple[type[BaseModel] | None, bool]:
    """Resolve only unambiguous model fields; unions use explicit model values."""
    if get_origin(annotation) in (Union, UnionType):
        members = [member for member in get_args(annotation) if member is not type(None)]
        if len(members) != 1:
            return None, False
        annotation = members[0]
    is_list = get_origin(annotation) is list
    if is_list:
        annotation = get_args(annotation)[0]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, is_list
    return None, False


class _ModelBuilder(BaseModelBuilder[BuiltModel]):
    """Runtime field setters for models that do not have generated builders."""

    _model: type[BuiltModel] = PrivateAttr()

    def __init__(self, model: type[BuiltModel]) -> None:
        super().__init__()
        self._model = model

    def build(self) -> BuiltModel:
        return self._model.model_validate(self._attrs)

    def _set(self, key: str, value: Any) -> Self:
        if self._in_context:
            self._attrs[key] = value
            return self
        builder = self.__class__(self._model)
        builder._attrs = self._attrs | {key: value}
        return builder

    def __getattr__(self, name: str) -> Any:
        # Pydantic's private attributes must continue through its own lookup.
        if name.startswith("_"):
            return super().__getattr__(name)  # type: ignore[misc]
        field_name = "build" if name == "build_" else name
        field = self._model.model_fields.get(field_name)
        if field is None:
            return super().__getattr__(name)  # type: ignore[misc]
        nested, is_list = _model_field_type(field.annotation)

        def set_field(value_or_callback: Any = UNSET, /) -> Any:
            if value_or_callback is UNSET:
                if not self._in_context or nested is None:
                    raise TypeError(f"A value is required for {field_name!r}")
                result: ListBuilderContext[Any] | BuilderContextBase[Any]
                if is_list:
                    result = ListBuilderContext[Any]()
                    result._factory = nested.builder
                else:
                    result = BuilderContextBase[Any]()
                    result._builder = nested.builder()
                result._parent_builder = self
                result._field_name = field_name
                return result
            value = value_or_callback
            if callable(value) and nested is not None:
                value = value(nested.list_builder() if is_list else nested.builder())
                if isinstance(value, (BaseBuilder, GenericListBuilder)):
                    value = value.build()
            return self._set(field_name, value)

        set_field.__name__ = name
        set_field.__doc__ = field.description
        return set_field
