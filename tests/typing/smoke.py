from typing import assert_type

from grugdb import (
    Column,
    Field,
    Row,
    Table,
    Unique,
    UniqueField,
    column,
)

originals: list[type[Row]] = []


def remember[T: Row](cls: type[T]) -> type[T]:
    originals.append(cls)
    return cls


@remember
class User(Row):
    email: Unique[str]
    age: Column[int]

    def summary(self) -> str:
        return f"{self.email}: {self.age}"

    def base_repr(self) -> str:
        return super().__repr__()


class WithDefault(Row):
    age: Column[int] = column(default=30)


def positive(users: Table[User]) -> None:
    user = User(email="ann@example.com", age=30)
    assert_type(user.email, str)
    assert_type(user.age, int)
    assert_type(User.email, UniqueField[User, str])
    assert_type(User.age, Field[User, int])
    assert_type(users.lookup(User.email, "ann@example.com"), User | None)
    assert_type(WithDefault().age, int)
    assert_type(WithDefault(age=31).age, int)
