import datetime
import unittest
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal, NewType

from grugdb import Column, Row
from grugdb.schema import matches, validate_hint


class Color(Enum):
    RED = 1


class Place(Row):
    city: Column[str]


class TestMatches(unittest.TestCase):
    def test_plain_values(self) -> None:
        for value, hint in (
            (1, int),
            (True, bool),
            ("ann", str),
            (b"ann", bytes),
            (datetime.date(2026, 1, 1), datetime.date),
            (Decimal("1.10"), Decimal),
            (Color.RED, Color),
        ):
            with self.subTest(hint=hint):
                self.assertTrue(matches(value, hint))
        self.assertFalse(matches("1", int))
        self.assertFalse(matches(True, int))
        self.assertFalse(matches(datetime.datetime(2026, 1, 1), datetime.date))

    def test_float_accepts_int_but_not_bool(self) -> None:
        self.assertTrue(matches(1, float))
        self.assertTrue(matches(1.5, float))
        self.assertFalse(matches(True, float))
        self.assertFalse(matches("1", float))

    def test_optional_and_union(self) -> None:
        self.assertTrue(matches(None, int | None))
        self.assertTrue(matches(3, int | None))
        self.assertFalse(matches("3", int | None))
        self.assertTrue(matches("x", int | str))

    def test_literal_distinguishes_bool_and_int(self) -> None:
        self.assertTrue(matches("a", Literal["a", "b"]))
        self.assertFalse(matches("c", Literal["a", "b"]))
        self.assertFalse(matches(True, Literal[1]))
        self.assertFalse(matches(1, Literal[True]))
        self.assertTrue(matches(None, Literal[None]))
        self.assertTrue(matches(Color.RED, Literal[Color.RED]))

    def test_tuples_and_frozensets(self) -> None:
        self.assertTrue(matches((1, "a"), tuple[int, str]))
        self.assertFalse(matches((1, 2), tuple[int, str]))
        self.assertFalse(matches((1,), tuple[int, str]))
        self.assertTrue(matches((1, 2, 3), tuple[int, ...]))
        self.assertTrue(matches((), tuple[int, ...]))
        self.assertTrue(matches((), tuple[()]))
        self.assertFalse(matches((1, "x"), tuple[int, ...]))
        self.assertFalse(matches([1], tuple[int, ...]))
        self.assertTrue(matches(frozenset({1}), frozenset[int]))
        self.assertFalse(matches(frozenset({"x"}), frozenset[int]))

    def test_nested_rows_are_checked_by_type(self) -> None:
        """A nested row matches its own model, because its fields were checked when built."""
        self.assertTrue(matches(Place(city="Philadelphia"), Place))
        self.assertFalse(matches("Philadelphia", Place))
        self.assertTrue(matches((Place(city="Philadelphia"),), tuple[Place, ...]))

    def test_unsupported_annotations_fail_explicitly(self) -> None:
        """Schema validation explicitly rejects mutable and unsupported annotations."""
        for hint in (
            Any,
            list[int],
            dict[str, int],
            set[int],
            Sequence[int],
            object,
            Annotated[int, "positive"],
        ):
            with (
                self.subTest(hint=hint),
                self.assertRaisesRegex(TypeError, "unsupported annotation"),
            ):
                validate_hint(hint)
            with (
                self.subTest(hint=hint),
                self.assertRaisesRegex(TypeError, "unsupported annotation"),
            ):
                matches(None, hint)

    def test_newtype_uses_underlying_runtime_type(self) -> None:
        user_id = NewType("user_id", int)
        self.assertTrue(matches(user_id(1), user_id))
        self.assertFalse(matches("1", user_id))

    def test_nested_mutability_is_rejected(self) -> None:
        """Frozen dataclasses are not supported field types; use a nested Row."""

        @dataclass(frozen=True)
        class MutableContents:
            tags: list[str]

        with self.assertRaisesRegex(TypeError, "unsupported annotation"):
            validate_hint(MutableContents)

    def test_enum_with_mutable_value_is_rejected(self) -> None:
        class MutableEnum(Enum):
            VALUE = ["a"]  # noqa: RUF012 - deliberately unsupported enum value

        with self.assertRaisesRegex(TypeError, "unsupported values"):
            validate_hint(MutableEnum)


if __name__ == "__main__":
    unittest.main()
