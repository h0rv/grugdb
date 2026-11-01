import unittest
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated
from unittest.mock import patch

from grugdb import Column, Database, Row, RowId, Table, Unique, column
from grugdb.schema import matches


class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


class EmailUser(Row):
    email: Unique[str]


def construct[T](factory: type[T], **values: object) -> T:
    return factory(**values)


class TestTable(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database()
        self.users = self.db.table(User)

    def test_same_class_same_table(self) -> None:
        self.assertIs(self.db.table(User), self.users)

    def test_insert_get(self) -> None:
        """Insert stores the row, increases len, and returns its internal ID."""
        value = User(id=1, name="ann", age=30)
        row_id = self.users.insert(value)
        self.assertIs(self.users.get(row_id), value)
        self.assertEqual(len(self.users), 1)

    def test_bad_constructor_values_leave_table_unchanged(self) -> None:
        """Invalid constructor values leave the table empty."""
        for values in ({"id": "x", "name": "ann"}, {"id": 1, "name": "ann", "age": "old"}):
            with self.subTest(values=values), self.assertRaises(TypeError):
                self.users.insert(construct(User, **values))
        self.assertEqual(len(self.users), 0)

    def test_insert_trusts_constructed_row(self) -> None:
        """Insert stores a constructed row without checking its fields again."""
        value = User(id=1, name="ann")
        with patch("grugdb.model.matches", side_effect=AssertionError("already parsed")):
            row_id = self.users.insert(value)
        self.assertIs(self.users.get(row_id), value)

    def test_update_constructs_replacement_once(self) -> None:
        """Update checks replacement values once through row construction."""
        row_id = self.users.insert(User(id=1, name="ann", age=30))
        with patch("grugdb.model.matches", wraps=matches) as parse_field:
            changed = self.users.update(row_id, age=31)
        self.assertEqual(parse_field.call_count, len(User.fields()))
        self.assertEqual(changed.age, 31)

    def test_wrong_row_class_is_rejected(self) -> None:
        """A table rejects a row of another model class."""

        class Other(Row):
            id: Column[int]

        widened = Table[Row](User)
        with self.assertRaises(TypeError):
            widened.insert(Other(id=1))
        self.assertEqual(len(widened), 0)

    def test_requires_a_row_model(self) -> None:
        @dataclass(frozen=True)
        class Plain:
            value: int

        for model in (Row, Plain, int):
            with self.subTest(model=model), self.assertRaises(TypeError):
                construct(type(self.users), model=model)

    def test_update_replaces_row(self) -> None:
        """Update stores a replacement without changing the original row."""
        old = User(id=1, name="ann", age=30)
        row_id = self.users.insert(old)
        new = self.users.update(row_id, age=31)
        self.assertEqual(new, User(id=1, name="ann", age=31))
        self.assertEqual(old.age, 30)
        self.assertIs(self.users.get(row_id), new)

    def test_invalid_update_preserves_old_row(self) -> None:
        """Invalid update values or field names preserve the stored row."""
        row_id = self.users.insert(User(id=1, name="ann"))
        with self.assertRaises(TypeError):
            self.users.update(row_id, age="old")
        self.assertIsNone(self.users.get(row_id).age)
        with self.assertRaises(TypeError):
            self.users.update(row_id, typo="bob")
        self.assertEqual(self.users.get(row_id).name, "ann")

    def test_delete(self) -> None:
        """Delete reduces len and makes the deleted ID unavailable to get."""
        row_id = self.users.insert(User(id=1, name="ann"))
        self.users.delete(row_id)
        self.assertEqual(len(self.users), 0)
        with self.assertRaises(KeyError):
            self.users.get(row_id)

    def test_update_where_stages_validation(self) -> None:
        """Bulk update returns the matched count and preserves rows on validation failure."""
        self.users.insert(User(id=1, name="ann", age=30))
        self.users.insert(User(id=2, name="bob", age=25))
        self.assertEqual(self.users.update_where(User.age.in_([30]), age=31), 1)
        self.assertEqual([user.age for user in self.users.scan()], [31, 25])
        with self.assertRaises(TypeError):
            self.users.update_where(User.id.in_([1, 2]), age="bad")
        self.assertEqual([user.age for user in self.users.scan()], [31, 25])

    def test_delete_where(self) -> None:
        """Bulk delete returns the matched count and keeps unmatched rows in scan order."""
        for i in range(5):
            self.users.insert(User(id=i, name=f"u{i}"))
        self.assertEqual(self.users.delete_where(User.id.in_([0, 2, 4])), 3)
        self.assertEqual([user.id for user in self.users.scan()], [1, 3])

    def test_mutability_and_annotation_metadata_are_rejected(self) -> None:
        """Model declarations reject mutable fields and unsupported annotation metadata."""

        def mutable() -> None:
            class Mutable(Row):
                tags: Column[list[str]]

        def metadata() -> None:
            class Constrained(Row):
                value: Column[Annotated[int, "positive"]]

        for declaration in (mutable, metadata):
            with self.assertRaises(TypeError):
                declaration()

    def test_row_inheritance_cannot_bypass_schema_checks(self) -> None:
        with self.assertRaises(TypeError):
            type("Child", (User,), {"__annotations__": {"tags": list[str]}})

    def test_duplicate_rows_have_distinct_internal_ids(self) -> None:
        """Equal rows get distinct increasing IDs, with no reuse after deletion."""
        value = User(id=1, name="ann")
        first = self.users.insert(value)
        second = self.users.insert(value)
        self.assertNotEqual(first, second)
        self.assertEqual(self.users.scan().all(), [value, value])
        self.users.delete(first)
        self.assertGreater(self.users.insert(value), second)

    def test_missing_ids_raise_key_error(self) -> None:
        """Get, update, and delete raise KeyError for missing internal IDs."""
        deleted_id = self.users.insert(User(id=1, name="ann"))
        self.users.delete(deleted_id)
        for row_id in (RowId(999), deleted_id):
            for operation in (self.users.get, self.users.update, self.users.delete):
                with (
                    self.subTest(row_id=row_id, operation=operation.__name__),
                    self.assertRaises(KeyError),
                ):
                    operation(row_id)
        self.assertEqual(len(self.users), 0)

    def test_scan_and_len_follow_successful_writes(self) -> None:
        """Scan reflects insert, update, and delete while len tracks stored rows."""
        scan = self.users.scan()
        self.assertEqual(scan.all(), [])
        self.assertEqual(len(self.users), 0)
        first = self.users.insert(User(id=1, name="ann"))
        second = self.users.insert(User(id=2, name="bob"))
        self.assertEqual(scan.all(), [User(id=1, name="ann"), User(id=2, name="bob")])
        self.assertEqual(len(self.users), 2)
        replacement = self.users.update(first, age=31)
        self.assertEqual(scan.all(), [replacement, User(id=2, name="bob")])
        self.assertEqual(len(self.users), 2)
        self.users.delete(second)
        self.assertEqual(scan.all(), [replacement])
        self.assertEqual(len(self.users), 1)

    def test_write_during_scan_invalidates_live_iteration(self) -> None:
        self.users.insert(User(id=1, name="ann"))
        iterator = iter(self.users.scan())
        next(iterator)
        self.users.insert(User(id=2, name="bob"))
        with self.assertRaises(RuntimeError):
            next(iterator)

    def test_table_is_not_implicitly_iterable(self) -> None:
        self.assertNotIsInstance(self.users, Iterable)

    def test_index_declarations_fail_before_table_registration(self) -> None:
        """Unsupported unique declarations fail before registering a table."""
        with self.assertRaises(NotImplementedError):
            self.db.table(EmailUser)
        self.assertNotIn(EmailUser, self.db._tables)
        with self.assertRaises(NotImplementedError):
            self.db.table(EmailUser)


if __name__ == "__main__":
    unittest.main()
