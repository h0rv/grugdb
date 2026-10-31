"""Runtime checks for supported immutable annotations."""

import pickle
import subprocess
import sys
import unittest
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from grugdb import Column, Database, Row, Unique
from grugdb.schema import matches, validate_hint
from tests.typing.models import (
    ChainedMutableList,
    ContactEmail,
    Coordinates,
    Email,
    FrozenAddress,
    HiddenAny,
    KeywordFields,
    Maybe,
    MaybeMutable,
    MutableEnum,
    MutableMapping,
    OtherPriority,
    OtherRole,
    OtherStatus,
    Pair,
    Place,
    Priority,
    RequiredAliases,
    Role,
    Status,
    Tags,
    User,
    UserId,
    declare_field,
    runtime_construct,
    sample_user,
)


class TestModelTypes(unittest.TestCase):
    def test_constructor__complex_defaults__should_preserve_values(self) -> None:
        user = User(email="ann@example.com")
        self.assertIs(user.role, Role.ADMIN)
        self.assertIs(user.status, Status.ACTIVE)
        self.assertIs(user.priority, Priority.LOW)
        self.assertEqual(user.born, date(2000, 1, 2))
        self.assertEqual(user.seen, datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(user.balance, Decimal("12.50"))
        self.assertEqual(user.payload, b"hello")
        self.assertEqual(user.pair, (1, 2))
        self.assertEqual(user.scores, (1, 2, 3))
        self.assertEqual(user.tags, frozenset({"reader"}))
        self.assertEqual(user.place, Place(city="Philadelphia", postal_code=19103))
        self.assertEqual(user.coordinates.latitude, Decimal("40"))
        self.assertIsNone(user.nickname)
        self.assertEqual(user.label, "home")

    def test_constructor__aliases_and_union_branches__should_accept_values(self) -> None:
        aliases = RequiredAliases(
            email="ann@example.com", alternative=None, pair=("a", "b"), label="home"
        )
        self.assertEqual(aliases.pair, ("a", "b"))
        for reference in (1, "external"):
            with self.subTest(reference=reference):
                user = User(email="x", reference=reference, scores=(), tags=frozenset())
                self.assertEqual(user.reference, reference)
        self.assertEqual(sample_user().nickname, "annie@example.com")

    def test_constructor__wrong_field_values__should_reject_without_coercion(self) -> None:
        cases: tuple[tuple[str, object], ...] = (
            ("email", 123),
            ("nickname", 123),
            ("label", 123),
            ("role", "admin"),
            ("role", OtherRole.ADMIN),
            ("status", "active"),
            ("status", OtherStatus.ACTIVE),
            ("priority", 1),
            ("priority", OtherPriority.LOW),
            ("born", datetime(2000, 1, 2)),
            ("seen", date(2026, 1, 2)),
            ("balance", 12.5),
            ("payload", "hello"),
            ("payload", bytearray(b"hello")),
            ("pair", (1, "two")),
            ("pair", (1, 2, 3)),
            ("pair", [1, 2]),
            ("scores", (1, "two")),
            ("tags", frozenset({1})),
            ("tags", {"reader"}),
            ("reference", Decimal("1")),
            ("reference", None),
            ("enabled", 1),
            ("version", True),
            ("administrator", Role.READER),
            ("state", "missing"),
            ("place", "Philadelphia"),
            ("coordinates", Place(city="Philadelphia", postal_code=19103)),
            ("history", ("Philadelphia",)),
        )
        for name, value in cases:
            with self.subTest(field=name, value=value), self.assertRaises(TypeError):
                runtime_construct(User, **{"email": "ann@example.com", name: value})

    def test_constructor__nested_rows__should_validate_when_built(self) -> None:
        """A nested row is checked when it is built, so a bad one never reaches its parent."""
        with self.assertRaises(TypeError):
            runtime_construct(Place, city=1, postal_code="19103")
        user = sample_user()
        self.assertIsInstance(user.history[0], Place)
        self.assertIsInstance(user.history[1], Coordinates)

    def test_constructor__keyword_field_names_and_none_alias__should_work(self) -> None:
        value = KeywordFields(self=1, row_id=2, pred=3, nothing=None)
        self.assertEqual(value.self, 1)
        self.assertEqual(value.replace(self=4).self, 4)
        table = Database().table(KeywordFields)
        row_id = table.insert(value)
        changed = table.update(row_id, self=5, row_id=6)
        self.assertEqual((changed.self, changed.row_id), (5, 6))
        self.assertEqual(table.update_where(KeywordFields.pred == 3, self=7, pred=8), 1)
        self.assertEqual((table.get(row_id).self, table.get(row_id).pred), (7, 8))
        with self.assertRaises(TypeError):
            runtime_construct(KeywordFields, nothing="not None")

    def test_constructor__newtype__should_validate_underlying_runtime_value(self) -> None:
        nominal = User(email="ann@example.com", user_id=UserId(7))
        self.assertEqual(runtime_construct(User, email="ann@example.com", user_id=7), nominal)
        for value in (True, "7", None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                runtime_construct(User, email="ann@example.com", user_id=value)

    def test_schema__aliases__should_resolve_to_their_values(self) -> None:
        for value, hint in (
            ("ann@example.com", Email),
            ("ann@example.com", ContactEmail),
            (frozenset({"a"}), Tags),
            (UserId(7), UserId),
            ((), tuple[()]),
            (True, Literal[True]),
            (Role.ADMIN, Literal[Role.ADMIN]),
            (Priority.LOW, Literal[Priority.LOW]),
        ):
            with self.subTest(hint=hint, value=value):
                validate_hint(hint)
                self.assertTrue(matches(value, hint))
        for value, hint in (
            (1, Email),
            (True, Literal[1]),
            (1, Literal[True]),
            ("active", Literal[Status.ACTIVE]),
            (OtherPriority.LOW, Literal[Priority.LOW]),
        ):
            with self.subTest(hint=hint, value=value):
                self.assertFalse(matches(value, hint))

    def test_schema__mutable_and_unsupported_types__should_fail_explicitly(self) -> None:
        for hint in (
            list[str],
            dict[str, int],
            Any,
            ChainedMutableList,
            MutableMapping,
            HiddenAny,
            MaybeMutable[list[str]],
            Maybe[int],
            Pair[int],
            FrozenAddress,
            MutableEnum,
            Sequence[int],
            Callable[[], int],
            object,
        ):
            with self.subTest(hint=hint), self.assertRaises(TypeError):
                validate_hint(hint)

    def test_row__unsupported_declarations__should_reject_at_definition(self) -> None:
        for annotation in (Column[ChainedMutableList], Column[HiddenAny], Column[Maybe[int]], int):
            with self.subTest(annotation=annotation), self.assertRaises(TypeError):
                declare_field(annotation)

    def test_row__defaults__should_be_checked(self) -> None:
        for annotation, default in (
            (Column[ContactEmail], 1),
            (Column[tuple[int, int]], (1, "two")),
            (Column[Role], "admin"),
            (Unique[str], "a unique default"),
        ):
            with self.subTest(annotation=annotation), self.assertRaises(TypeError):
                declare_field(annotation, default=default)

    def test_table__unique_field__should_wait_for_indexes(self) -> None:
        with self.assertRaises(NotImplementedError):
            Database().table(User)

    def test_table__nested_rows__should_scan_and_replace_without_conversion(self) -> None:
        class Entry(Row):
            place: Column[Place]
            sequence: Column[UserId]

        original = Place(city="Philadelphia", postal_code=19103)
        entries = Database().table(Entry)
        row_id = entries.insert(Entry(place=original, sequence=UserId(7)))
        self.assertIs(entries.get(row_id).place, original)
        query = entries.scan().where(Entry.place == original).select(Entry.sequence)
        self.assertEqual(query.all(), [7])
        entries.update(row_id, place=original.replace(city="Boston"))
        self.assertEqual(query.count(), 0)
        with self.assertRaises(TypeError):
            entries.update(row_id, place="not a row")

    def test_pickle__importable_complex_model__should_roundtrip_in_second_process(self) -> None:
        original = sample_user()
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory(prefix="grugdb-trusted-pickle-") as directory:
            path = Path(directory) / "user.pickle"
            # Both processes only load the trusted file created by this test.
            path.write_bytes(pickle.dumps(original))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import pickle, sys; from pathlib import Path; "
                    "from tests.typing.models import User, sample_user; "
                    "path = Path(sys.argv[1]); value = pickle.loads(path.read_bytes()); "
                    "assert type(value) is User; assert value == sample_user(); "
                    "path.write_bytes(pickle.dumps(value))",
                    str(path),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            restored = pickle.loads(path.read_bytes())
        self.assertIs(type(restored), User)
        self.assertEqual(restored, original)
        self.assertEqual(hash(restored), hash(original))


if __name__ == "__main__":
    unittest.main()
