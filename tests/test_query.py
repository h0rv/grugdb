import unittest
from collections.abc import Iterator
from typing import Any

from grugdb import Column, Count, Database, Max, Min, Query, Row, Sum, column
from grugdb.query import HashJoin, Limit, NestedLoopJoin, Scan


class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


class Order(Row):
    id: Column[int]
    user_id: Column[int | None]
    total: Column[int]


class N(Row):
    n: Column[int]


class Counting(Query[N]):
    """An endless source that records how many rows were pulled from it."""

    def __init__(self) -> None:
        self.pulled = 0

    def __iter__(self) -> Iterator[N]:
        while True:
            self.pulled += 1
            yield N(n=self.pulled)


def numbers(*values: int) -> Query[N]:
    return Scan(tuple(N(n=value) for value in values))


class TestQuery(unittest.TestCase):
    def setUp(self) -> None:
        db = Database()
        self.users = db.table(User)
        self.orders = db.table(Order)
        for user in [
            User(id=1, name="ann", age=30),
            User(id=2, name="bob", age=25),
            User(id=3, name="cy", age=30),
            User(id=4, name="dee"),
        ]:
            self.users.insert(user)
        for order in [
            Order(id=10, user_id=1, total=5),
            Order(id=11, user_id=1, total=7),
            Order(id=12, user_id=3, total=2),
            Order(id=13, user_id=None, total=99),
        ]:
            self.orders.insert(order)

    def names(self, query: Query[User]) -> list[str]:
        return query.select(User.name).all()

    # Expressions

    def test_compare_operators(self) -> None:
        """Each comparison operator filters rows by Python comparison of the field value."""
        scan = self.users.scan()
        self.assertEqual(self.names(scan.where(User.age == 30)), ["ann", "cy"])
        self.assertEqual(self.names(scan.where(User.age != 30)), ["bob", "dee"])
        self.assertEqual(self.names(scan.where(User.age < 30)), ["bob"])
        self.assertEqual(self.names(scan.where(User.age <= 30)), ["ann", "bob", "cy"])
        self.assertEqual(self.names(scan.where(User.age > 25)), ["ann", "cy"])
        self.assertEqual(self.names(scan.where(User.age >= 25)), ["ann", "bob", "cy"])

    def test_ordering_comparison_with_none_is_false(self) -> None:
        """An ordering comparison with None is false instead of raising, as in SQL."""
        scan = self.users.scan()
        self.assertNotIn("dee", self.names(scan.where(User.age < 100)))
        self.assertNotIn("dee", self.names(scan.where(~(User.age < 100) & (User.age > 0))))
        self.assertEqual(self.names(scan.where(User.age == None)), ["dee"])  # noqa: E711

    def test_combinators_is_none_and_in(self) -> None:
        """&, |, ~, is_none(), and in_() combine and test conditions."""
        scan = self.users.scan()
        self.assertEqual(self.names(scan.where((User.age == 30) & (User.id > 1))), ["cy"])
        self.assertEqual(
            self.names(scan.where((User.id == 2) | User.age.is_none())), ["bob", "dee"]
        )
        self.assertEqual(self.names(scan.where(~(User.age == 30))), ["bob", "dee"])
        self.assertEqual(self.names(scan.where(User.name.in_(["cy", "ann"]))), ["ann", "cy"])

    def test_python_boolean_operators_are_rejected(self) -> None:
        """Using and, or, not, or if on a condition raises instead of silently dropping half."""
        with self.assertRaises(TypeError):
            bool(User.age >= 18)

    def test_conditions_check_values_when_built(self) -> None:
        """A comparison value of the wrong type fails when the condition is built."""
        text: Any = "18"
        number: Any = 3
        with self.assertRaises(TypeError):
            User.age.__ge__(text)
        with self.assertRaises(TypeError):
            User.name.in_(["ann", number])

    def test_join_condition_is_not_a_bool(self) -> None:
        """A join condition raises if Python asks for its truth value."""
        with self.assertRaises(TypeError):
            bool(User.id == Order.user_id)

    # Filtering and projection

    def test_select_needs_a_field(self) -> None:
        """select() with no fields raises instead of yielding empty tuples."""
        no_fields: list[Any] = []
        with self.assertRaises(TypeError):
            self.users.scan().select(*no_fields)

    def test_where_select(self) -> None:
        """Filtering and projection compose to return matching names in input order."""
        self.assertEqual(self.names(self.users.scan().where(User.age > 26)), ["ann", "cy"])

    def test_select_several_fields_yields_tuples(self) -> None:
        """Selecting several fields produces one tuple per row."""
        query = self.users.scan().where(User.id > 3).select(User.id, User.name)
        self.assertEqual(query.all(), [(4, "dee")])

    def test_where_select_empty(self) -> None:
        """Filtering and projection each produce empty output for empty input."""
        self.assertEqual(numbers().where(N.n > 0).all(), [])
        self.assertEqual(numbers().select(N.n).all(), [])

    def test_where_preserves_duplicates_and_order(self) -> None:
        """Filtering retains duplicate matches in their original input order."""
        self.assertEqual(numbers(3, 1, 3, 2).where(N.n != 2).select(N.n).all(), [3, 1, 3])

    def test_where_and_select_are_lazy(self) -> None:
        """Building a query pulls nothing, and taking three matches pulls only what it needs."""
        source = Counting()
        query = source.where(N.n.in_(range(2, 100, 2))).select(N.n)
        self.assertEqual(source.pulled, 0)
        self.assertEqual(query.limit(3).all(), [2, 4, 6])
        self.assertEqual(source.pulled, 6)

    def test_queries_are_reusable_and_do_not_mutate_parents(self) -> None:
        """Repeated query execution leaves parent query descriptions unchanged."""
        base = self.users.scan().where(User.age == 30)
        narrower = base.where(User.name == "ann")
        self.assertEqual(base.count(), 2)
        self.assertEqual(narrower.count(), 1)
        self.assertEqual(base.count(), 2)

    def test_queries_read_current_rows_on_each_execution(self) -> None:
        """Repeating a query reads current rows without changing an earlier result list."""
        query = self.users.scan().where(User.age == 30)
        before = query.all()
        self.users.insert(User(id=5, name="eli", age=30))
        self.assertEqual(query.count(), 3)
        self.assertEqual(len(before), 2)

    def test_first_count(self) -> None:
        self.assertEqual(self.users.scan().first(), User(id=1, name="ann", age=30))
        self.assertIsNone(self.users.scan().where(User.id > 99).first())
        self.assertEqual(self.users.scan().count(), 4)

    # Limit

    def test_limit_is_lazy(self) -> None:
        """A finite limit on infinite input pulls only the requested rows."""
        source = Counting()
        self.assertEqual(source.limit(3).select(N.n).all(), [1, 2, 3])
        self.assertEqual(source.pulled, 3)
        zero = Counting()
        self.assertEqual(zero.limit(0, offset=5).all(), [])
        self.assertEqual(zero.pulled, 0)

    def test_limit_offset_consumes_only_requested_rows(self) -> None:
        """Skipping two rows and taking three consumes exactly five input rows."""
        source = Counting()
        self.assertEqual(source.limit(3, offset=2).select(N.n).all(), [3, 4, 5])
        self.assertEqual(source.pulled, 5)

    def test_limit_beyond_end(self) -> None:
        """A limit beyond the input end returns only available rows."""
        source = numbers(1, 2, 3)
        self.assertEqual(source.limit(10).select(N.n).all(), [1, 2, 3])
        self.assertEqual(source.limit(10, offset=2).select(N.n).all(), [3])
        self.assertEqual(source.limit(10, offset=5).all(), [])

    def test_limit_rejects_negative(self) -> None:
        """Negative limits and offsets raise ValueError."""
        for n, offset in ((-1, 0), (1, -1)):
            with self.subTest(n=n, offset=offset), self.assertRaises(ValueError):
                Limit(self.users.scan(), n, offset)

    # Joins

    def both_joins(
        self, left: Query[User], right: Query[Order]
    ) -> tuple[list[tuple[User, Order]], list[tuple[User, Order]]]:
        on = User.id == Order.user_id
        return NestedLoopJoin(left, right, on).all(), HashJoin(left, right, on).all()

    def test_joins_agree_and_keep_order(self) -> None:
        """Both joins return each match in left order, then right order within each left row."""
        nested, hashed = self.both_joins(self.users.scan(), self.orders.scan())
        self.assertEqual(nested, hashed)
        self.assertEqual([(u.id, o.id) for u, o in hashed], [(1, 10), (1, 11), (3, 12)])

    def test_join_uses_a_hash_join(self) -> None:
        """Query.join builds a hash join for an equality between fields."""
        joined = self.users.scan().join(self.orders.scan(), User.id == Order.user_id)
        self.assertIsInstance(joined, HashJoin)

    def test_joins_with_empty_or_unmatched_input(self) -> None:
        """Both joins produce no pairs when an input is empty or no keys match."""
        empty_users: Query[User] = Scan(())
        empty_orders: Query[Order] = Scan(())
        unmatched = Scan((Order(id=1, user_id=99, total=1),))
        for left, right in (
            (empty_users, self.orders.scan()),
            (self.users.scan(), empty_orders),
            (self.users.scan(), unmatched),
        ):
            self.assertEqual(self.both_joins(left, right), ([], []))

    def test_duplicate_keys_produce_every_pair(self) -> None:
        """Two left rows and two right rows sharing a key produce all four ordered pairs."""
        users = Scan((User(id=1, name="a"), User(id=1, name="b")))
        nested, hashed = self.both_joins(users, self.orders.scan())
        self.assertEqual(nested, hashed)
        self.assertEqual(
            [(u.name, o.id) for u, o in hashed], [("a", 10), ("a", 11), ("b", 10), ("b", 11)]
        )

    def test_nested_join_consumes_right_once_per_execution(self) -> None:
        """A nested-loop join consumes its right source once on each execution."""

        class Right(Query[Order]):
            def __init__(self) -> None:
                self.executions = 0

            def __iter__(self) -> Iterator[Order]:
                self.executions += 1
                yield Order(id=1, user_id=1, total=1)

        right = Right()
        query = NestedLoopJoin(self.users.scan(), right, User.id == Order.user_id)
        self.assertEqual(len(query.all()), 1)
        self.assertEqual(right.executions, 1)
        query.all()
        self.assertEqual(right.executions, 2)

    def test_none_keys_match_by_python_equality(self) -> None:
        """Both joins match None keys, because None == None in Python."""

        class A(Row):
            k: Column[int | None]

        class B(Row):
            k: Column[int | None]

        left, right = Scan((A(k=None),)), Scan((B(k=None),))
        on = A.k == B.k
        self.assertEqual(NestedLoopJoin(left, right, on).count(), 1)
        self.assertEqual(HashJoin(left, right, on).count(), 1)

    def test_join_then_where_then_select(self) -> None:
        """Fields from either side of a join can be filtered and selected."""
        query = (
            self.users.scan()
            .join(self.orders.scan(), User.id == Order.user_id)
            .where(Order.total > 4)
            .select(User.name, Order.total)
        )
        self.assertEqual(query.all(), [("ann", 5), ("ann", 7)])

    def test_self_join_field_is_ambiguous(self) -> None:
        """Reading a field from a row that joins the same model twice raises TypeError."""
        pairs = self.users.scan().join(self.users.scan(), User.id == User.id)
        self.assertEqual(pairs.count(), 4)
        with self.assertRaisesRegex(TypeError, "ambiguous"):
            pairs.select(User.name).all()

    # Sorting

    def test_order_by_empty(self) -> None:
        """Sorting empty input produces empty output."""
        self.assertEqual(numbers().order_by(N.n).all(), [])

    def test_order_by_ascending_and_descending(self) -> None:
        """order_by sorts ascending, and desc() sorts descending."""
        scan = self.users.scan()
        self.assertEqual(self.names(scan.order_by(User.name.desc())), ["dee", "cy", "bob", "ann"])
        self.assertEqual(self.names(scan.order_by(User.name)), ["ann", "bob", "cy", "dee"])

    def test_order_by_puts_none_last_ascending_and_first_descending(self) -> None:
        """None sorts after every value, so it is last ascending and first descending."""
        scan = self.users.scan()
        self.assertEqual(self.names(scan.order_by(User.age)), ["bob", "ann", "cy", "dee"])
        self.assertEqual(self.names(scan.order_by(User.age.desc())), ["dee", "ann", "cy", "bob"])

    def test_order_by_is_stable(self) -> None:
        """Rows with equal keys keep their input order in both directions."""
        scan = self.users.scan().where(User.age == 30)
        self.assertEqual(self.names(scan.order_by(User.age)), ["ann", "cy"])
        self.assertEqual(self.names(scan.order_by(User.age.desc())), ["ann", "cy"])

    def test_order_by_several_keys(self) -> None:
        """Later keys break ties left by earlier keys, each in its own direction."""
        query = self.users.scan().order_by(User.age.desc(), User.name.desc())
        self.assertEqual(self.names(query), ["dee", "cy", "ann", "bob"])

    # Grouping

    def test_group_by_aggregates(self) -> None:
        """Grouping orders by user produces per-user counts, sums, minimums, and maximums."""
        query = self.orders.scan().group_by(Order.user_id, Count(), Sum(Order.total))
        self.assertEqual(query.all(), [(1, 2, 12), (3, 1, 2), (None, 1, 99)])
        extremes = self.orders.scan().group_by(Order.user_id, Min(Order.total), Max(Order.total))
        self.assertEqual(extremes.all()[0], (1, 5, 7))

    def test_group_by_keeps_first_seen_key_order(self) -> None:
        """Groups appear in the order their keys are first seen."""
        query = numbers(2, 1, 2, 3, 1).group_by(N.n, Count())
        self.assertEqual(query.all(), [(2, 2), (1, 2), (3, 1)])

    def test_aggregates_skip_none(self) -> None:
        """Sum, Min, and Max skip None values, and Count counts every row."""
        query = self.users.scan().group_by(User.age, Count(), Sum(User.age))
        self.assertEqual(query.all(), [(30, 2, 60), (25, 1, 25), (None, 1, 0)])
        self.assertEqual(
            self.users.scan().group_by(User.age, Min(User.age)).all()[-1], (None, None)
        )

    def test_group_by_on_joined_rows(self) -> None:
        """Grouping a join can use fields from either side."""
        query = (
            self.users.scan()
            .join(self.orders.scan(), User.id == Order.user_id)
            .group_by(User.name, Count(), Sum(Order.total))
        )
        self.assertEqual(query.all(), [("ann", 2, 12), ("cy", 1, 2)])

    def test_group_by_empty(self) -> None:
        """Empty input produces no groups."""
        self.assertEqual(numbers().group_by(N.n, Count()).all(), [])


if __name__ == "__main__":
    unittest.main()
