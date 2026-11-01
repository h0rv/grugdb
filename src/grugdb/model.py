"""Rows: immutable records whose class annotations are the database schema."""

import annotationlib
import typing
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Self, dataclass_transform, overload

from grugdb.expr import Field, UniqueField
from grugdb.schema import matches, validate_hint


class Missing(Enum):
    """Marks a field with no default. `None` can't do this, since it is a valid value."""

    VALUE = 0


MISSING = Missing.VALUE


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """What the schema knows about one field."""

    name: str
    position: int
    hint: object
    default: object
    unique: bool


class Column[K]:
    """`Column[T]` declares a field holding a value of type `T`.

    On a row, `user.name` is the value. On the class, `User.name` is a `Field` that
    names the column, for use in queries.

    ```python
    class User(Row):
        name: Column[str]
        age: Column[int | None] = column(default=None)


    User(name="Ada").name  # "Ada"
    users.scan().where(User.age >= 18)
    ```
    """

    __slots__ = ("_field", "default")

    def __init__(self, default: object = MISSING) -> None:
        self.default = default
        self._field: Field[Any, K] | None = None

    def bind(self, model: type[Row], spec: FieldSpec) -> None:
        self._field = Field(model, spec)

    @property
    def field(self) -> Field[Any, K]:
        if self._field is None:
            raise TypeError("field is not part of a Row class")
        return self._field

    @overload
    def __get__[T: Row](self, instance: None, owner: type[T]) -> Field[T, K]: ...

    @overload
    def __get__(self, instance: Row, owner: type[Row] | None = None) -> K: ...

    def __get__(self, instance: Row | None, owner: type[Row] | None = None) -> object:
        if instance is None:
            return self.field
        return instance._values[self.field.spec.position]

    def __set__(self, instance: Row, value: K) -> None:
        raise AttributeError("rows are immutable; use replace()")


class Unique[K](Column[K]):
    """`Unique[T]` declares a field whose values must be unique across a table.

    On the class, `Contact.email` is a `UniqueField` you can pass to `Table.lookup`.
    Creating a table with unique fields raises `NotImplementedError` until you
    build indexes.

    ```python
    class Contact(Row):
        email: Unique[str]
    ```
    """

    __slots__ = ()

    def bind(self, model: type[Row], spec: FieldSpec) -> None:
        self._field = UniqueField(model, spec)

    @overload
    def __get__[T: Row](self, instance: None, owner: type[T]) -> UniqueField[T, K]: ...

    @overload
    def __get__(self, instance: Row, owner: type[Row] | None = None) -> K: ...

    def __get__(self, instance: Row | None, owner: type[Row] | None = None) -> object:
        if instance is None:
            return self.field
        return instance._values[self.field.spec.position]


def column[K](*, default: K) -> Column[K]:
    """`column(default=...)` gives a field a default value.

    ```python
    class User(Row):
        age: Column[int | None] = column(default=None)
    ```
    """
    return Column[K](default)


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(column,))
class Row:
    """`Row` is the base class for immutable records. Annotate each field with
    `Column[T]` or `Unique[T]` and pass values by keyword.

    ```python
    class User(Row):
        id: Column[int]
        name: Column[str]


    user = User(id=1, name="Ada")
    ```
    """

    __slots__ = ("_values",)
    _values: tuple[object, ...]
    _schema: ClassVar[tuple[FieldSpec, ...]] = ()

    def __init_subclass__(cls) -> None:
        cls._schema = build_schema(cls)

    @classmethod
    def fields(cls) -> tuple[FieldSpec, ...]:
        return cls._schema

    def __init__(self, /, **values: object) -> None:
        if type(self) is Row:
            raise TypeError("define a model by subclassing Row")
        unknown = values.keys() - {spec.name for spec in self._schema}
        if unknown:
            raise TypeError(f"unknown fields: {', '.join(sorted(unknown))}")
        packed: list[object] = []
        for spec in self._schema:
            value = values.get(spec.name, spec.default)
            if value is MISSING:
                raise TypeError(f"missing field: {spec.name}")
            if not matches(value, spec.hint):
                raise TypeError(f"invalid value for {spec.name}: {value!r}")
            packed.append(value)
        object.__setattr__(self, "_values", tuple(packed))

    def replace(self, /, **changes: object) -> Self:
        values = {spec.name: self._values[spec.position] for spec in self._schema}
        return type(self)(**(values | changes))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("rows are immutable; use replace()")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("rows are immutable")

    def __repr__(self) -> str:
        fields = ", ".join(f"{s.name}={self._values[s.position]!r}" for s in self._schema)
        return f"{type(self).__name__}({fields})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Row) and type(self) is type(other) and self._values == other._values
        )

    def __hash__(self) -> int:
        return hash((type(self), self._values))

    def __reduce__(self) -> tuple[object, tuple[type[Row], tuple[object, ...]]]:
        return restore_row, (type(self), self._values)


RESERVED = frozenset(
    {
        "__init__",
        "__setattr__",
        "__delattr__",
        "__eq__",
        "__hash__",
        "__reduce__",
        "fields",
        "replace",
    }
)


def build_schema(cls: type[Row]) -> tuple[FieldSpec, ...]:
    """Read a Row subclass's annotations into field specs and install descriptors."""
    if cls.__bases__ != (Row,):
        raise TypeError("rows cannot inherit from other rows")
    if RESERVED & cls.__dict__.keys():
        raise TypeError(f"{cls.__name__} overrides Row machinery")
    names = annotationlib.get_annotations(cls, format=annotationlib.Format.FORWARDREF)
    hints = typing.get_type_hints(cls, localns={cls.__name__: cls}, include_extras=True)
    specs: list[FieldSpec] = []
    for name in names:
        if name.startswith("_"):
            raise TypeError(f"field names cannot start with an underscore: {name}")
        hint = hints[name]
        kind = typing.get_origin(hint)
        if kind not in (Column, Unique):
            raise TypeError(f"{name} must be annotated Column[T] or Unique[T]")
        (value_hint,) = typing.get_args(hint)
        validate_hint(value_hint)
        match cls.__dict__.get(name, MISSING):
            case Missing():
                default = MISSING
            case Column() as declared:
                default = declared.default
            case _:
                raise TypeError(f"use column(default=...) to give {name} a default")
        if kind is Unique and default is not MISSING:
            raise TypeError(f"unique field {name} cannot have a default")
        if default is not MISSING and not matches(default, value_hint):
            raise TypeError(f"invalid default for {name}")
        spec = FieldSpec(name, len(specs), value_hint, default, kind is Unique)
        descriptor = Unique[Any]() if kind is Unique else Column[Any](default)
        descriptor.bind(cls, spec)
        setattr(cls, name, descriptor)
        specs.append(spec)
    stray = [n for n, v in cls.__dict__.items() if isinstance(v, Column) and n not in names]
    if stray:
        raise TypeError(f"fields need an annotation: {', '.join(stray)}")
    return tuple(specs)


def restore_row[T: Row](model: type[T], values: tuple[object, ...]) -> T:
    """Rebuild a pickled row through its constructor, so values are checked again."""
    names = [spec.name for spec in model.fields()]
    if len(values) != len(names):
        raise TypeError("invalid row pickle state")
    return model(**dict(zip(names, values, strict=True)))
