"""Field references and the expressions built from them.

`User.age >= 18` does not compare anything. It builds a `Compare` object that a query
can evaluate against each row, and that a planner can read.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, assert_never, overload

if TYPE_CHECKING:
    from .model import FieldSpec

# Rows store their values in a tuple[object, ...]. The schema checked each value's type
# when the row was built, but the static type is gone once it is inside the tuple.
type Value = Any


class Op(StrEnum):
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="

    def apply(self, left: Value, right: Value) -> bool:
        match self:
            case Op.EQ:
                return bool(left == right)
            case Op.NE:
                return bool(left != right)
            case Op.LT:
                return bool(left < right)
            case Op.LE:
                return bool(left <= right)
            case Op.GT:
                return bool(left > right)
            case Op.GE:
                return bool(left >= right)
            case _:
                assert_never(self)


class Expr[T](ABC):
    """`Expr[T]` is a condition on rows of model `T`. Combine conditions with `&`, `|`,
    and `~`. Python's `and`, `or`, and `not` can't be overloaded, so they raise.

    ```python
    adults = users.scan().where((User.age >= 18) & ~User.name.in_(["root"]))
    ```
    """

    @abstractmethod
    def test(self, row: object) -> bool: ...

    def __and__[U](self, other: Expr[U]) -> Expr[T | U]:
        return And[T | U](self, other)

    def __or__[U](self, other: Expr[U]) -> Expr[T | U]:
        return Or[T | U](self, other)

    def __invert__(self) -> Expr[T]:
        return Not(self)

    def __bool__(self) -> bool:
        raise TypeError("use &, |, and ~ to combine conditions, not and, or, and not")


@dataclass(frozen=True, slots=True, eq=False)
class Field[T, K]:
    """`User.age` on the class is a `Field[User, int | None]`. It names one column of a
    model. Comparing it with a value builds a condition instead of a bool.

    ```python
    User.age >= 18  # Compare(User.age, ">=", 18)
    User.id == Order.user_id  # JoinOn(User.id, Order.user_id)
    ```
    """

    model: type[T]
    spec: FieldSpec

    @property
    def name(self) -> str:
        return self.spec.name

    def read(self, row: Value) -> Value:
        """Read this field from a row, or from the matching side of a joined pair.

        A query row is a model instance, or a `(left, right)` pair after a join, so
        `row` is typed loosely here.
        """
        if type(row) is self.model:
            return row._values[self.spec.position]
        if type(row) is tuple:
            sides = [side for side in row if type(side) is self.model]
            if len(sides) == 1:
                return sides[0]._values[self.spec.position]
            if sides:
                raise TypeError(f"{self} is ambiguous: the row joins {self.model.__name__} twice")
        raise TypeError(f"{self} cannot be read from {type(row).__name__}")

    def check(self, value: K) -> K:
        """Return `value` unchanged if it fits the field's declared type."""
        from .schema import matches

        if not matches(value, self.spec.hint):
            raise TypeError(f"invalid value for {self}: {value!r}")
        return value

    @overload
    def __eq__[U](self, other: Field[U, Any]) -> JoinOn[T, U]: ...

    @overload
    def __eq__(self, other: K) -> Compare[T]: ...

    def __eq__(self, other: Any) -> Any:  # ty: ignore[invalid-method-override]
        if isinstance(other, Field):
            return JoinOn(self, other)
        return Compare(self, Op.EQ, self.check(other))

    def __ne__(self, other: K) -> Compare[T]:  # ty: ignore[invalid-method-override]
        return Compare(self, Op.NE, self.check(other))

    def __lt__(self, other: K) -> Compare[T]:
        return Compare(self, Op.LT, self.check(other))

    def __le__(self, other: K) -> Compare[T]:
        return Compare(self, Op.LE, self.check(other))

    def __gt__(self, other: K) -> Compare[T]:
        return Compare(self, Op.GT, self.check(other))

    def __ge__(self, other: K) -> Compare[T]:
        return Compare(self, Op.GE, self.check(other))

    def __repr__(self) -> str:
        return f"{self.model.__name__}.{self.name}"

    def is_none(self) -> IsNone[T]:
        return IsNone(self)

    def in_(self, values: Iterable[K]) -> In[T]:
        return In(self, frozenset(self.check(value) for value in values))

    def desc(self) -> Desc[T]:
        return Desc(self)


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class UniqueField[T, K](Field[T, K]):
    """A `Field` declared with `Unique[T]`. Only these can be passed to `Table.lookup`."""


@dataclass(frozen=True, slots=True)
class Compare[T](Expr[T]):
    """`field op value`, such as `User.age >= 18`.

    grugdb uses two-valued logic, so every condition is true or false. `==` and `!=`
    follow Python, so `None == None` is true. An ordering comparison (`<`, `<=`,
    `>`, `>=`) with `None` on either side is false instead of raising. SQL uses a
    third value, UNKNOWN, so `NOT (age < 21)` in SQL still drops NULL ages, while
    `~(User.age < 21)` here keeps them.
    """

    field: Field[T, Any]
    op: Op
    value: object

    def test(self, row: object) -> bool:
        value = self.field.read(row)
        if self.op in (Op.EQ, Op.NE):
            return self.op.apply(value, self.value)
        return value is not None and self.value is not None and self.op.apply(value, self.value)

    def __repr__(self) -> str:
        return f"{self.field!r} {self.op} {self.value!r}"


@dataclass(frozen=True, slots=True)
class And[T](Expr[T]):
    left: Expr[Any]
    right: Expr[Any]

    def test(self, row: object) -> bool:
        return self.left.test(row) and self.right.test(row)

    def __repr__(self) -> str:
        return f"({self.left!r}) & ({self.right!r})"


@dataclass(frozen=True, slots=True)
class Or[T](Expr[T]):
    left: Expr[Any]
    right: Expr[Any]

    def test(self, row: object) -> bool:
        return self.left.test(row) or self.right.test(row)

    def __repr__(self) -> str:
        return f"({self.left!r}) | ({self.right!r})"


@dataclass(frozen=True, slots=True)
class Not[T](Expr[T]):
    inner: Expr[T]

    def test(self, row: object) -> bool:
        return not self.inner.test(row)

    def __repr__(self) -> str:
        return f"~({self.inner!r})"


@dataclass(frozen=True, slots=True)
class IsNone[T](Expr[T]):
    field: Field[T, Any]

    def test(self, row: object) -> bool:
        return self.field.read(row) is None

    def __repr__(self) -> str:
        return f"{self.field!r} is None"


@dataclass(frozen=True, slots=True)
class In[T](Expr[T]):
    field: Field[T, Any]
    values: frozenset[object]

    def test(self, row: object) -> bool:
        return self.field.read(row) in self.values

    def __repr__(self) -> str:
        return f"{self.field!r} in {set(self.values)!r}"


@dataclass(frozen=True, slots=True)
class JoinOn[L, R]:
    """`User.id == Order.user_id`: an equality between fields of two models."""

    left: Field[L, Any]
    right: Field[R, Any]

    def test(self, left: object, right: object) -> bool:
        return bool(self.left.read(left) == self.right.read(right))

    def __bool__(self) -> bool:
        raise TypeError("a join condition is not a bool; pass it to join()")

    def __repr__(self) -> str:
        return f"{self.left!r} == {self.right!r}"


@dataclass(frozen=True, slots=True)
class Desc[T]:
    """`User.age.desc()` sorts by age, largest first."""

    field: Field[T, Any]


class Aggregate[T, V](ABC):
    """Folds the rows of one group into a value of type `V`, one row at a time."""

    @abstractmethod
    def start(self) -> Value: ...

    @abstractmethod
    def add(self, total: Value, row: object) -> Value: ...


@dataclass(frozen=True, slots=True)
class Count(Aggregate[Any, int]):
    """The number of rows in the group."""

    def start(self) -> Value:
        return 0

    def add(self, total: Value, row: object) -> Value:
        return total + 1


@dataclass(frozen=True, slots=True)
class Sum[T, N: (int, float, Decimal)](Aggregate[T, N]):
    """The sum of a numeric field over the group. `None` values are skipped, and a
    group with no other values sums to 0. SQL would return NULL for that group.
    """

    field: Field[T, N] | Field[T, N | None]

    def start(self) -> Value:
        return 0

    def add(self, total: Value, row: object) -> Value:
        value = self.field.read(row)
        return total if value is None else total + value


@dataclass(frozen=True, slots=True)
class Min[T, K](Aggregate[T, K | None]):
    """The smallest value of a field in the group, skipping `None`."""

    field: Field[T, K]

    def start(self) -> Value:
        return None

    def add(self, total: Value, row: object) -> Value:
        value = self.field.read(row)
        if value is None or (total is not None and value >= total):
            return total
        return value


@dataclass(frozen=True, slots=True)
class Max[T, K](Aggregate[T, K | None]):
    """The largest value of a field in the group, skipping `None`."""

    field: Field[T, K]

    def start(self) -> Value:
        return None

    def add(self, total: Value, row: object) -> Value:
        value = self.field.read(row)
        if value is None or (total is not None and value <= total):
            return total
        return value


type SortKey[T] = Field[T, Any] | Desc[T]
