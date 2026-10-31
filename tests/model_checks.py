"""Run with `uv run python -m tests.model_checks`."""

import base64
import pickle
import re
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

from grugdb import Column, Field, Row, Table, Unique, UniqueField, column
from grugdb.model import restore_row as _restore
from tests.typing.smoke import User, WithDefault, originals


def assign(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


@contextmanager
def raises(error: type[Exception], *, match: str = "") -> Generator[None]:
    try:
        yield
    except error as exc:
        assert re.search(match, str(exc)), str(exc)
    else:
        raise AssertionError(f"expected {error.__name__}")


def test_row__construction__should_keep_identity_slots_methods_and_freezing() -> None:
    user = User(email="ann@example.com", age=30)
    assert originals == [User]
    assert type(user) is User
    assert user._values == ("ann@example.com", 30)
    assert user.summary() == "ann@example.com: 30"
    assert user.base_repr() == repr(user) == "User(email='ann@example.com', age=30)"
    assert user == User(email="ann@example.com", age=30)
    assert hash(user) == hash(User(email="ann@example.com", age=30))
    for name in ("email", "age", "_values", "extra"):
        with raises(AttributeError):
            setattr(user, name, "mutation")
        with raises(AttributeError):
            delattr(user, name)
    with raises(AttributeError):
        object.__setattr__(user, "email", "mutation")
    object.__setattr__(user, "_values", ("bypass", 99))
    assert user.email == "bypass"  # Documented deliberate bypass.


def test_constructor__dynamic_bad_input__should_validate_before_packing() -> None:
    for values in (
        {"email": 1, "age": 30},
        {"email": "x", "age": True},
        {"email": "x"},
        {"email": "x", "age": 30, "typo": 1},
    ):
        with raises(TypeError):
            instance = object.__new__(User)
            Row.__init__(instance, **values)
    with raises(TypeError, match="define a model"):
        Row()
    assert WithDefault().age == 30
    assert WithDefault(age=31).age == 31


def test_field_refs__class_access__should_name_model_fields() -> None:
    user = User(email="ann", age=30)
    assert User.email is User.email
    assert isinstance(User.email, UniqueField)
    assert isinstance(User.age, Field) and not isinstance(User.age, UniqueField)
    assert User.age.name == "age" and User.age.model is User
    assert User.age.read(user) == 30
    assert User._schema is not None
    with raises(FrozenInstanceError):
        assign(User._schema[0], "name", "changed")


def test_table_lookup__wrong_model_or_key__should_reject_before_index() -> None:
    class Other(Row):
        email: Unique[str]

    table = object.__new__(Table)
    table.model = User
    with raises(TypeError, match="not a field"):
        table.lookup(Other.email, "x")
    with raises(TypeError, match="invalid value"):
        table.lookup(User.email, cast("str", 1))
    with raises(NotImplementedError):
        table.lookup(User.email, "x")


def test_row__bad_declarations__should_reject_mutability_and_inheritance() -> None:
    def mutable() -> None:
        class Mutable(Row):
            values: Column[list[int]]

    def mismatched() -> None:
        type(
            "Mismatched",
            (Row,),
            {
                "__module__": __name__,
                "__annotations__": {"value": Column[str]},
                "value": "not a column() declaration",
            },
        )

    def inherited() -> None:
        class Child(User):
            pass

    def custom_init() -> None:
        class Custom(Row):
            def __init__(self) -> None:
                pass

    def bad_default() -> None:
        class BadDefault(Row):
            age: Column[int] = Column(default=[])

    for invalid in (mutable, mismatched, inherited, custom_init, bad_default):
        with raises(TypeError):
            invalid()


def test_field__declaration__should_be_real_descriptor() -> None:
    assert type(User.__dict__["email"]) is Unique
    assert type(User.__dict__["age"]) is Column
    assert isinstance(column(default=1), Column)


def test_pickle__same_and_second_process__should_restore_validated_original_model() -> None:
    user = User(email="pickle", age=42)
    payload = pickle.dumps(user)
    restored = pickle.loads(payload)
    assert restored == user and type(restored) is User
    with raises(AttributeError):
        assign(restored, "email", "mutated")
    encoded = base64.b64encode(payload).decode("ascii")
    code = (
        "import base64,pickle; from tests.typing.smoke import User; "
        f"row=pickle.loads(base64.b64decode({encoded!r})); "
        "assert type(row) is User; assert row.email == 'pickle'; "
        "assert row.age == 42; print('child OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "child OK\n"
    for bad in (("pickle", "not an int"), ("missing",), ("x", 1, 2), ([], 1)):
        with raises(TypeError):
            _restore(User, bad)
    corrupted = User(email="x", age=1)
    object.__setattr__(corrupted, "_values", ("x", []))
    with raises(TypeError, match="age"):
        pickle.loads(pickle.dumps(corrupted))


if __name__ == "__main__":
    tests = [
        test_row__construction__should_keep_identity_slots_methods_and_freezing,
        test_constructor__dynamic_bad_input__should_validate_before_packing,
        test_field_refs__class_access__should_name_model_fields,
        test_table_lookup__wrong_model_or_key__should_reject_before_index,
        test_row__bad_declarations__should_reject_mutability_and_inheritance,
        test_field__declaration__should_be_real_descriptor,
        test_pickle__same_and_second_process__should_restore_validated_original_model,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} runtime checks passed.")
