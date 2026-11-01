"""Checks for one assigned method at a time, independent of other exercises."""

import unittest

from grugdb import Column, Count, Max, Min, Row, RowId, Sum, Table, column
from grugdb.expr import Compare, Op
from grugdb.query import GroupBy, HashJoin, Limit, NestedLoopJoin, OrderBy, Scan, Select, Where


class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


class Order(Row):
    id: Column[int]
    user_id: Column[int | None]
    total: Column[int]


ADA = User(id=101, name="ada", age=30)
BOB = User(id=102, name="bob", age=20)
CY = User(id=103, name="cy")
USERS = (ADA, BOB, CY)
TWIN = User(id=101, name="twin", age=30)
FIRST = Order(id=1, user_id=101, total=5)
SECOND = Order(id=2, user_id=101, total=7)
THIRD = Order(id=3, user_id=103, total=2)
UNMATCHED = Order(id=4, user_id=999, total=9)
ORDERS = (FIRST, SECOND, THIRD, UNMATCHED)


def seeded_table() -> Table[User]:
    table = Table(User)
    table._rows = {RowId(2): ADA, RowId(5): BOB, RowId(8): CY}
    table._next_id = 9
    return table


class TestInsert(unittest.TestCase):
    def test_stores_the_original_row_under_an_internal_id(self) -> None:
        table = Table(User)
        row_id = table.insert(ADA)
        self.assertEqual(table._rows, {row_id: ADA})
        self.assertIs(table._rows[row_id], ADA)
        self.assertNotEqual(row_id, ADA.id)

    def test_duplicate_rows_get_increasing_ids_without_reuse(self) -> None:
        table = seeded_table()
        first = table.insert(ADA)
        second = table.insert(ADA)
        self.assertGreater(first, RowId(8))
        self.assertGreater(second, first)
        self.assertIs(table._rows[first], ADA)
        self.assertIs(table._rows[second], ADA)
        del table._rows[second]
        third = table.insert(ADA)
        self.assertGreater(third, second)
        self.assertEqual(
            table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY, first: ADA, third: ADA}
        )

    def test_wrong_model_preserves_rows_and_next_id(self) -> None:
        table = Table[Row](User)
        with self.assertRaises(TypeError):
            table.insert(FIRST)
        self.assertEqual(table._rows, {})
        self.assertEqual(table._next_id, 1)


class TestGet(unittest.TestCase):
    def test_uses_internal_ids_and_returns_original_objects(self) -> None:
        table = seeded_table()
        for row_id, row in ((RowId(2), ADA), (RowId(5), BOB), (RowId(8), CY)):
            with self.subTest(row_id=row_id):
                self.assertIs(table.get(row_id), row)
        self.assertEqual(table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY})

    def test_missing_id_raises_without_changing_storage(self) -> None:
        for table in (Table(User), seeded_table()):
            before = table._rows.copy()
            for row_id in (RowId(101), RowId(999)):
                with self.subTest(row_id=row_id), self.assertRaises(KeyError):
                    table.get(row_id)
            self.assertEqual(table._rows, before)


class TestUpdate(unittest.TestCase):
    def test_stores_and_returns_a_replacement_at_the_same_id(self) -> None:
        table = seeded_table()
        new = table.update(RowId(2), name="ann", age=31)
        self.assertEqual(new, User(id=101, name="ann", age=31))
        self.assertIs(table._rows[RowId(2)], new)
        self.assertIsNot(new, ADA)
        self.assertEqual(ADA, User(id=101, name="ada", age=30))
        self.assertEqual(table._rows, {RowId(2): new, RowId(5): BOB, RowId(8): CY})
        self.assertEqual(table._next_id, 9)

    def test_invalid_changes_preserve_the_original_row(self) -> None:
        for changes in ({"age": "old"}, {"typo": "ann"}):
            table = seeded_table()
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                table.update(RowId(2), **changes)
            self.assertEqual(table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY})
            self.assertIs(table._rows[RowId(2)], ADA)

    def test_missing_id_raises_without_changing_storage(self) -> None:
        table = seeded_table()
        with self.assertRaises(KeyError):
            table.update(RowId(999), age=31)
        self.assertEqual(table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY})


class TestDelete(unittest.TestCase):
    def test_removes_only_the_requested_internal_id(self) -> None:
        table = seeded_table()
        self.assertIsNone(table.delete(RowId(5)))
        self.assertEqual(table._rows, {RowId(2): ADA, RowId(8): CY})
        self.assertEqual(table._next_id, 9)
        with self.assertRaises(KeyError):
            table.delete(RowId(5))

    def test_missing_id_raises_without_changing_storage(self) -> None:
        for table in (Table(User), seeded_table()):
            before = table._rows.copy()
            with self.assertRaises(KeyError):
                table.delete(RowId(999))
            self.assertEqual(table._rows, before)


class TestUpdateWhere(unittest.TestCase):
    def test_replaces_each_match_and_returns_its_count(self) -> None:
        table = seeded_table()
        count = table.update_where(User.id.in_([101, 103]), age=40)
        self.assertEqual(count, 2)
        self.assertEqual(
            table._rows,
            {
                RowId(2): User(id=101, name="ada", age=40),
                RowId(5): BOB,
                RowId(8): User(id=103, name="cy", age=40),
            },
        )
        self.assertIs(table._rows[RowId(5)], BOB)
        self.assertEqual((ADA.age, CY.age), (30, None))
        self.assertEqual(table._next_id, 9)

    def test_empty_or_unmatched_input_returns_zero(self) -> None:
        for table in (Table(User), seeded_table()):
            before = table._rows.copy()
            self.assertEqual(table.update_where(User.name.in_(["nobody"]), age=40), 0)
            self.assertEqual(table._rows, before)

    def test_invalid_changes_leave_all_rows_unchanged(self) -> None:
        for changes in ({"age": "old"}, {"unknown": 1}):
            table = seeded_table()
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                table.update_where(User.id.in_([101, 102, 103]), **changes)
            self.assertEqual(table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY})
            self.assertIs(table._rows[RowId(2)], ADA)


class TestDeleteWhere(unittest.TestCase):
    def test_removes_each_match_and_returns_its_count(self) -> None:
        table = seeded_table()
        self.assertEqual(table.delete_where(User.id.in_([101, 103])), 2)
        self.assertEqual(table._rows, {RowId(5): BOB})
        self.assertIs(table._rows[RowId(5)], BOB)
        self.assertEqual(table._next_id, 9)
        self.assertEqual(table.delete_where(User.age.is_none()), 0)
        self.assertEqual(table.delete_where(User.name.in_(["bob"])), 1)
        self.assertEqual(table._rows, {})

    def test_empty_or_unmatched_input_returns_zero(self) -> None:
        for table in (Table(User), seeded_table()):
            before = table._rows.copy()
            self.assertEqual(table.delete_where(User.name.in_(["nobody"])), 0)
            self.assertEqual(table._rows, before)


class TestScan(unittest.TestCase):
    def test_returns_rows_in_storage_order_and_is_repeatable(self) -> None:
        table = seeded_table()
        query = table.scan()
        self.assertEqual(list(query), list(USERS))
        self.assertEqual(list(query), list(USERS))
        self.assertIs(next(iter(query)), ADA)
        self.assertEqual(table._rows, {RowId(2): ADA, RowId(5): BOB, RowId(8): CY})

    def test_reads_current_storage_including_initially_empty_storage(self) -> None:
        table = Table(User)
        query = table.scan()
        self.assertEqual(list(query), [])
        table._rows[RowId(2)] = ADA
        self.assertEqual(list(query), [ADA])
        table._rows[RowId(2)] = BOB
        table._rows[RowId(5)] = CY
        self.assertEqual(list(query), [BOB, CY])
        del table._rows[RowId(2)]
        self.assertEqual(list(query), [CY])

    def test_size_change_invalidates_active_iteration(self) -> None:
        table = seeded_table()
        iterator = iter(table.scan())
        self.assertIs(next(iterator), ADA)
        table._rows[RowId(9)] = TWIN
        with self.assertRaises(RuntimeError):
            next(iterator)


class TestLen(unittest.TestCase):
    def test_empty_table_has_zero_rows(self) -> None:
        self.assertEqual(len(Table(User)), 0)

    def test_counts_stored_rows_including_duplicates(self) -> None:
        table = seeded_table()
        self.assertEqual(len(table), 3)
        table._rows[RowId(9)] = ADA
        self.assertEqual(len(table), 4)
        del table._rows[RowId(2)]
        self.assertEqual(len(table), 3)
        table._rows.clear()
        self.assertEqual(len(table), 0)


class TestCompare(unittest.TestCase):
    def test_each_operator_on_less_equal_and_greater_values(self) -> None:
        rows = (User(id=1, name="low", age=19), BOB, ADA)
        for op, expected in (
            (Op.EQ, [False, True, False]),
            (Op.NE, [True, False, True]),
            (Op.LT, [True, False, False]),
            (Op.LE, [True, True, False]),
            (Op.GT, [False, False, True]),
            (Op.GE, [False, True, True]),
        ):
            with self.subTest(op=op):
                condition = Compare(User.age, op, 20)
                self.assertEqual([condition.test(row) for row in rows], expected)

    def test_equality_and_inequality_use_python_none_semantics(self) -> None:
        for value, equal in ((None, [False, True]), (30, [True, False])):
            with self.subTest(value=value):
                self.assertEqual(
                    [Compare(User.age, Op.EQ, value).test(row) for row in (ADA, CY)], equal
                )
                self.assertEqual(
                    [Compare(User.age, Op.NE, value).test(row) for row in (ADA, CY)],
                    [not result for result in equal],
                )

    def test_ordering_with_none_on_either_side_is_false(self) -> None:
        for op in (Op.LT, Op.LE, Op.GT, Op.GE):
            for row, value in ((CY, 20), (ADA, None), (CY, None)):
                with self.subTest(op=op, row=row, value=value):
                    self.assertIs(Compare(User.age, op, value).test(row), False)


class TestWhere(unittest.TestCase):
    def test_keeps_matching_rows_duplicates_and_order_on_each_execution(self) -> None:
        rows = [CY, ADA, CY, BOB]
        query = Where(Scan(rows), User.id.in_([101, 103]))
        self.assertEqual(list(query), [CY, ADA, CY])
        self.assertEqual(list(query), [CY, ADA, CY])
        rows.append(ADA)
        self.assertEqual(list(query), [CY, ADA, CY, ADA])
        self.assertEqual(rows, [CY, ADA, CY, BOB, ADA])

    def test_empty_and_unmatched_input(self) -> None:
        for rows in ((), USERS):
            self.assertEqual(list(Where(Scan(rows), User.name.in_(["nobody"]))), [])

    def test_building_and_taking_one_match_do_not_consume_the_rest(self) -> None:
        source = iter(USERS)
        query = Where(Scan(source), User.name.in_(["bob", "cy"]))
        self.assertIs(next(source), ADA)
        self.assertIs(next(iter(query)), BOB)
        self.assertEqual(list(source), [CY])


class TestSelect(unittest.TestCase):
    def test_one_field_yields_scalars_and_multiple_fields_yield_tuples(self) -> None:
        source = Scan((CY, ADA, CY))
        single = Select(source, (User.name,))
        self.assertEqual(list(single), ["cy", "ada", "cy"])
        self.assertEqual(list(single), ["cy", "ada", "cy"])
        self.assertEqual(
            list(Select(source, (User.age, User.name, User.id))),
            [(None, "cy", 103), (30, "ada", 101), (None, "cy", 103)],
        )

    def test_empty_input_and_fields_from_raw_joined_rows(self) -> None:
        self.assertEqual(list(Select(Scan(()), (User.name,))), [])
        pairs = Scan(((ADA, SECOND), (CY, THIRD)))
        self.assertEqual(list(Select(pairs, (Order.total, User.name))), [(7, "ada"), (2, "cy")])

    def test_building_and_taking_one_value_do_not_consume_the_rest(self) -> None:
        source = iter(USERS)
        query = Select(Scan(source), (User.name,))
        self.assertIs(next(source), ADA)
        self.assertEqual(next(iter(query)), "bob")
        self.assertEqual(list(source), [CY])

    def test_unreadable_or_ambiguous_field_raises(self) -> None:
        for rows in ((FIRST,), ((ADA, TWIN),)):
            with self.subTest(rows=rows), self.assertRaises(TypeError):
                list(Select(Scan(rows), (User.name,)))


class TestNestedLoopJoin(unittest.TestCase):
    def test_duplicate_keys_yield_every_pair_in_left_then_right_order(self) -> None:
        query = NestedLoopJoin(Scan((ADA, TWIN, CY)), Scan(ORDERS), User.id == Order.user_id)
        expected = [(ADA, FIRST), (ADA, SECOND), (TWIN, FIRST), (TWIN, SECOND), (CY, THIRD)]
        self.assertEqual(list(query), expected)
        self.assertEqual(list(query), expected)

    def test_empty_unmatched_and_none_keys(self) -> None:
        for left, right in (((), ORDERS), (USERS, ()), (USERS, (UNMATCHED,))):
            self.assertEqual(
                list(NestedLoopJoin(Scan(left), Scan(right), User.id == Order.user_id)), []
            )
        null = Order(id=5, user_id=None, total=0)
        query = NestedLoopJoin(Scan(USERS), Scan((null,)), User.age == Order.user_id)
        self.assertEqual(list(query), [(CY, null)])

    def test_construction_is_lazy_and_one_shot_right_matches_each_left_row(self) -> None:
        rows = [FIRST]
        right = iter(rows)
        query = NestedLoopJoin(Scan((ADA, TWIN)), Scan(right), User.id == Order.user_id)
        rows.append(SECOND)
        self.assertEqual(list(query), [(ADA, FIRST), (ADA, SECOND), (TWIN, FIRST), (TWIN, SECOND)])
        self.assertEqual(list(right), [])


class TestHashJoin(unittest.TestCase):
    def test_duplicate_keys_yield_every_pair_in_left_then_right_order(self) -> None:
        query = HashJoin(Scan((ADA, TWIN, CY)), Scan(ORDERS), User.id == Order.user_id)
        expected = [(ADA, FIRST), (ADA, SECOND), (TWIN, FIRST), (TWIN, SECOND), (CY, THIRD)]
        self.assertEqual(list(query), expected)
        self.assertEqual(list(query), expected)

    def test_empty_unmatched_and_none_keys(self) -> None:
        for left, right in (((), ORDERS), (USERS, ()), (USERS, (UNMATCHED,))):
            self.assertEqual(list(HashJoin(Scan(left), Scan(right), User.id == Order.user_id)), [])
        null = Order(id=5, user_id=None, total=0)
        query = HashJoin(Scan(USERS), Scan((null,)), User.age == Order.user_id)
        self.assertEqual(list(query), [(CY, null)])

    def test_construction_is_lazy_and_one_shot_right_matches_each_left_row(self) -> None:
        rows = [FIRST]
        right = iter(rows)
        query = HashJoin(Scan((ADA, TWIN)), Scan(right), User.id == Order.user_id)
        rows.append(SECOND)
        self.assertEqual(list(query), [(ADA, FIRST), (ADA, SECOND), (TWIN, FIRST), (TWIN, SECOND)])
        self.assertEqual(list(right), [])


class TestOrderBy(unittest.TestCase):
    def test_directions_none_placement_and_stable_ties(self) -> None:
        source = Scan((ADA, CY, TWIN, BOB))
        self.assertEqual(list(OrderBy(source, (User.age,))), [BOB, ADA, TWIN, CY])
        self.assertEqual(list(OrderBy(source, (User.age.desc(),))), [CY, ADA, TWIN, BOB])

    def test_multiple_keys_repeat_without_mutating_the_input(self) -> None:
        rows = [TWIN, CY, ADA, BOB]
        query = OrderBy(Scan(rows), (User.age.desc(), User.name))
        self.assertEqual(list(query), [CY, ADA, TWIN, BOB])
        self.assertEqual(list(query), [CY, ADA, TWIN, BOB])
        self.assertEqual(rows, [TWIN, CY, ADA, BOB])

    def test_empty_input_and_no_sort_keys(self) -> None:
        self.assertEqual(list(OrderBy(Scan(()), (User.name,))), [])
        self.assertEqual(list(OrderBy(Scan(USERS), ())), list(USERS))


class TestGroupBy(unittest.TestCase):
    def test_first_seen_groups_and_independent_totals_skip_none(self) -> None:
        rows = (BOB, ADA, User(id=4, name="bob"), CY, User(id=5, name="ada", age=10))
        query = GroupBy(
            Scan(rows), User.name, (Count(), Sum(User.age), Min(User.age), Max(User.age))
        )
        expected = [("bob", 2, 20, 20, 20), ("ada", 2, 40, 10, 30), ("cy", 1, 0, None, None)]
        self.assertEqual(list(query), expected)
        self.assertEqual(list(query), expected)

    def test_no_aggregates_and_none_group_keys(self) -> None:
        query = GroupBy(Scan((CY, ADA, CY, BOB, TWIN)), User.age, ())
        self.assertEqual(list(query), [(None,), (30,), (20,)])
        self.assertEqual(list(GroupBy(Scan(()), User.age, (Count(),))), [])

    def test_fields_from_both_sides_of_raw_joined_rows(self) -> None:
        pairs = Scan(((ADA, FIRST), (ADA, SECOND), (CY, THIRD)))
        query = GroupBy(pairs, User.name, (Count(), Sum(Order.total)))
        self.assertEqual(list(query), [("ada", 2, 12), ("cy", 1, 2)])


class TestLimit(unittest.TestCase):
    def test_offset_and_limit_consume_only_the_requested_prefix(self) -> None:
        source = iter(USERS)
        query = Limit(Scan(source), 1, offset=1)
        self.assertEqual(list(query), [BOB])
        self.assertEqual(list(source), [CY])

    def test_zero_limit_does_not_consume_even_with_an_offset(self) -> None:
        source = iter(USERS)
        self.assertEqual(list(Limit(Scan(source), 0, offset=100)), [])
        self.assertEqual(list(source), list(USERS))

    def test_empty_short_repeatable_and_invalid_limits(self) -> None:
        source = Scan(USERS)
        query = Limit(source, 10, offset=1)
        self.assertEqual(list(query), [BOB, CY])
        self.assertEqual(list(query), [BOB, CY])
        self.assertEqual(list(Limit(source, 1, offset=10)), [])
        self.assertEqual(list(Limit(Scan(()), 10)), [])
        for n, offset in ((-1, 0), (1, -1)):
            with self.subTest(n=n, offset=offset), self.assertRaises(ValueError):
                Limit(source, n, offset)


if __name__ == "__main__":
    unittest.main()
