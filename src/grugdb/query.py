"""Queries: trees of small operators that pull rows from the operator below them."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from typing import Any, overload

from grugdb.expr import Aggregate, Desc, Expr, Field, JoinOn, SortKey


class Query[T](Iterable[T]):
    """`Query[T]` describes how to produce rows of type `T`. Building a query reads
    nothing. Iterating it, or calling `all()`, runs it.

    ```python
    adults = users.scan().where(User.age >= 18).select(User.name)
    adults.all()  # ["Ada", ...]
    ```
    """

    @overload
    def where[L, R](
        self: Query[tuple[L, R]], condition: Expr[L] | Expr[R] | Expr[L | R], /
    ) -> Query[tuple[L, R]]: ...

    @overload
    def where(self, condition: Expr[T], /) -> Query[T]: ...

    def where(self, condition: Expr[Any], /) -> Query[Any]:
        return Where(self, condition)

    @overload
    def select[L, R, A](self: Query[tuple[L, R]], a: Field[L, A] | Field[R, A], /) -> Query[A]: ...

    @overload
    def select[L, R, A, B](
        self: Query[tuple[L, R]], a: Field[L, A] | Field[R, A], b: Field[L, B] | Field[R, B], /
    ) -> Query[tuple[A, B]]: ...

    @overload
    def select[A](self, a: Field[T, A], /) -> Query[A]: ...

    @overload
    def select[A, B](self, a: Field[T, A], b: Field[T, B], /) -> Query[tuple[A, B]]: ...

    @overload
    def select[A, B, C](
        self, a: Field[T, A], b: Field[T, B], c: Field[T, C], /
    ) -> Query[tuple[A, B, C]]: ...

    def select(self, *fields: Field[Any, Any]) -> Query[Any]:
        if not fields:
            raise TypeError("select() needs at least one field")
        return Select(self, fields)

    def join[U](self, other: Query[U], on: JoinOn[T, U], /) -> Query[tuple[T, U]]:
        return HashJoin(self, other, on)

    @overload
    def order_by[L, R](
        self: Query[tuple[L, R]], *keys: SortKey[L] | SortKey[R]
    ) -> Query[tuple[L, R]]: ...

    @overload
    def order_by(self, *keys: SortKey[T]) -> Query[T]: ...

    def order_by(self, *keys: SortKey[Any]) -> Query[Any]:
        return OrderBy(self, keys)

    @overload
    def group_by[L, R, K](
        self: Query[tuple[L, R]], key: Field[L, K] | Field[R, K], /
    ) -> Query[tuple[K]]: ...

    @overload
    def group_by[L, R, K, A](
        self: Query[tuple[L, R]],
        key: Field[L, K] | Field[R, K],
        a: Aggregate[L, A] | Aggregate[R, A],
        /,
    ) -> Query[tuple[K, A]]: ...

    @overload
    def group_by[L, R, K, A, B](
        self: Query[tuple[L, R]],
        key: Field[L, K] | Field[R, K],
        a: Aggregate[L, A] | Aggregate[R, A],
        b: Aggregate[L, B] | Aggregate[R, B],
        /,
    ) -> Query[tuple[K, A, B]]: ...

    @overload
    def group_by[K](self, key: Field[T, K], /) -> Query[tuple[K]]: ...

    @overload
    def group_by[K, A](self, key: Field[T, K], a: Aggregate[T, A], /) -> Query[tuple[K, A]]: ...

    @overload
    def group_by[K, A, B](
        self, key: Field[T, K], a: Aggregate[T, A], b: Aggregate[T, B], /
    ) -> Query[tuple[K, A, B]]: ...

    def group_by(self, key: Field[Any, Any], *aggregates: Aggregate[Any, Any]) -> Query[Any]:
        return GroupBy(self, key, aggregates)

    def limit(self, n: int, offset: int = 0) -> Query[T]:
        return Limit(self, n, offset)

    def all(self) -> list[T]:
        return list(self)

    def first(self) -> T | None:
        for row in self:
            return row
        return None

    def count(self) -> int:
        return sum(1 for _ in self)


@dataclass(frozen=True)
class Scan[T](Query[T]):
    source: Iterable[T]

    def __iter__(self) -> Iterator[T]:
        return iter(self.source)


@dataclass(frozen=True)
class Where[T](Query[T]):
    child: Query[T]
    condition: Expr[Any]

    def __iter__(self) -> Iterator[T]:
        """Lazily yield rows for which the Expr predicate tests true.

        Preserve input order and duplicates without changing row objects.
        Read only as far as needed for requested matches.
        Empty input or no matches yields nothing.
        """
        return (row for row in self.child if self.condition.test(row))


@dataclass(frozen=True)
class Select(Query[Any]):
    """Yields one field's value per row, or a tuple when there are several fields."""

    child: Query[Any]
    fields: tuple[Field[Any, Any], ...]

    def __iter__(self) -> Iterator[Any]:
        """Lazily yield selected field values for each input row.

        One field yields a scalar; several yield a tuple in field order.
        Preserve input order, duplicates, and None values. Empty input yields
        nothing. Raise TypeError for an unreadable or ambiguous field.
        """
        if len(self.fields) == 1:
            (field,) = self.fields
            return (field.read(row) for row in self.child)
        return (tuple(field.read(row) for field in self.fields) for row in self.child)


@dataclass(frozen=True)
class NestedLoopJoin[T, U](Query[tuple[T, U]]):
    left: Query[T]
    right: Query[U]
    on: JoinOn[T, U]

    def __iter__(self) -> Iterator[tuple[T, U]]:
        """Yield (left, right) tuples for all pairs with equal join fields.

        Keep left input order, then right order within each left row.
        Include every duplicate match. None keys match other None keys.
        Empty input on either side or no matching keys yields nothing.
        Read the right input once per execution before yielding any matches.
        """
        right = list(self.right)
        return ((a, b) for a in self.left for b in right if self.on.test(a, b))


@dataclass(frozen=True)
class HashJoin[T, U](Query[tuple[T, U]]):
    left: Query[T]
    right: Query[U]
    on: JoinOn[T, U]

    def __iter__(self) -> Iterator[tuple[T, U]]:
        """Yield (left, right) tuples for all pairs with equal join fields.

        Keep left input order, then right order within each left row.
        Include every duplicate match. None keys match other None keys.
        Empty input on either side or no matching keys yields nothing.
        Read the right input once per execution before yielding any matches.
        """
        buckets: dict[object, list[U]] = {}
        for b in self.right:
            buckets.setdefault(self.on.right.read(b), []).append(b)
        for a in self.left:
            for b in buckets.get(self.on.left.read(a), ()):
                yield a, b


@dataclass(frozen=True)
class OrderBy[T](Query[T]):
    """Sorts by each key in turn. Rows with equal keys keep their input order. `None`
    sorts after every other value, so it comes last ascending and first descending,
    as in Postgres.
    """

    child: Query[T]
    keys: tuple[SortKey[Any], ...]

    def __iter__(self) -> Iterator[T]:
        """Yield rows sorted by the keys, with earlier keys taking priority.

        Sort ascending unless a key uses desc(). Keep input order for ties.
        Place None last ascending and first descending.
        Read all input before yielding. Do not change input rows or order.
        Empty input yields nothing. No keys preserves input order.
        """
        rows = list(self.child)
        for key in reversed(self.keys):
            field, reverse = (key.field, True) if isinstance(key, Desc) else (key, False)

            def nones_last(row: object, field: Field[Any, Any] = field) -> tuple[bool, object]:
                value = field.read(row)
                return value is None, value

            rows.sort(key=nones_last, reverse=reverse)
        return iter(rows)


@dataclass(frozen=True)
class GroupBy(Query[Any]):
    """Yields `(key, *totals)` per distinct key, in the order keys first appear."""

    child: Query[Any]
    key: Field[Any, Any]
    aggregates: tuple[Aggregate[Any, Any], ...]

    def __iter__(self) -> Iterator[Any]:
        """Yield (key, *totals) tuples in the order keys first appear.

        Include a group for None keys. Apply each aggregate to that group's
        rows and keep totals in aggregate order, using its None semantics.
        With no aggregates, yield (key,) tuples. Empty input yields nothing.
        Read all input before yielding without changing input rows.
        """
        groups: dict[object, list[object]] = {}
        for row in self.child:
            key = self.key.read(row)
            if key not in groups:
                groups[key] = [aggregate.start() for aggregate in self.aggregates]
            totals = groups[key]
            groups[key] = [
                aggregate.add(total, row)
                for aggregate, total in zip(self.aggregates, totals, strict=True)
            ]
        return ((key, *totals) for key, totals in groups.items())


@dataclass(frozen=True)
class Limit[T](Query[T]):
    child: Query[T]
    n: int
    offset: int = 0

    def __post_init__(self) -> None:
        if self.n < 0 or self.offset < 0:
            raise ValueError("limit and offset must be >= 0")

    def __iter__(self) -> Iterator[T]:
        """Lazily skip offset rows, then yield at most n rows in input order.

        Consume no rows beyond that prefix. If n is 0, read nothing.
        Empty input or an offset past the end yields nothing.
        Negative n or offset raises ValueError when the Limit is constructed.
        """
        if self.n == 0:
            return iter(())
        return islice(self.child, self.offset, self.offset + self.n)
