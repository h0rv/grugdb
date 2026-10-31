"""Importable models shared by runtime and static API checks."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, IntEnum, StrEnum
from typing import Any, Literal, NewType

from grugdb import Column, Row, Unique, column

type Email = str
type ContactEmail = Email
type Nothing = None
type Tags = frozenset[str]

# Generic aliases are deliberately unsupported; tests check they are rejected.
type Maybe[T] = T | None
type Pair[T] = tuple[T, T]

TextAlias = str
UserId = NewType("UserId", int)
OrderId = NewType("OrderId", int)


class Role(Enum):
    ADMIN = "admin"
    READER = "reader"


class Status(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class OtherRole(Enum):
    ADMIN = "admin"


class OtherStatus(StrEnum):
    ACTIVE = "active"


class OtherPriority(IntEnum):
    LOW = 1


class Place(Row):
    city: Column[str]
    postal_code: Column[int]


class Coordinates(Row):
    latitude: Column[Decimal]
    longitude: Column[Decimal]


class User(Row):
    email: Unique[ContactEmail]
    user_id: Column[UserId] = column(default=UserId(1))
    backup_email: Column[Email] = column(default="backup@example.com")
    nickname: Column[ContactEmail | None] = column(default=None)
    label: Column[TextAlias] = column(default="home")
    role: Column[Role] = column(default=Role.ADMIN)
    status: Column[Status] = column(default=Status.ACTIVE)
    priority: Column[Priority] = column(default=Priority.LOW)
    born: Column[date] = column(default=date(2000, 1, 2))
    seen: Column[datetime] = column(default=datetime(2026, 1, 2, 3, 4, 5))
    balance: Column[Decimal] = column(default=Decimal("12.50"))
    payload: Column[bytes] = column(default=b"hello")
    pair: Column[tuple[int, int]] = column(default=(1, 2))
    tagged: Column[tuple[int, str]] = column(default=(1, "one"))
    scores: Column[tuple[int, ...]] = column(default=(1, 2, 3))
    tags: Column[Tags] = column(default=frozenset({"reader"}))
    reference: Column[int | str] = column(default="external")
    enabled: Column[Literal[True]] = column(default=True)
    version: Column[Literal[1]] = column(default=1)
    administrator: Column[Literal[Role.ADMIN]] = column(default=Role.ADMIN)
    state: Column[Literal["new", "ready"]] = column(default="new")
    place: Column[Place] = column(default=Place(city="Philadelphia", postal_code=19103))
    coordinates: Column[Coordinates] = column(
        default=Coordinates(latitude=Decimal("40"), longitude=Decimal("-75"))
    )
    history: Column[tuple[Place | Coordinates, ...]] = column(default=())


class RequiredAliases(Row):
    email: Column[Email]
    alternative: Column[ContactEmail | None]
    pair: Column[tuple[Email, Email]]
    label: Column[TextAlias]


class KeywordFields(Row):
    self: Column[int] = column(default=0)
    row_id: Column[int] = column(default=0)
    pred: Column[int] = column(default=0)
    nothing: Column[Nothing] = column(default=None)


@dataclass(frozen=True, slots=True)
class FrozenAddress:
    city: str


class MutableEnum(Enum):
    VALUE = ["mutable"]  # noqa: RUF012 - intentionally unsupported schema value


type MutableList = list[str]
type ChainedMutableList = MutableList
type MutableMapping = dict[str, int]
type HiddenAny = Any
type MaybeMutable[T] = tuple[T, ...] | None
type Recursive = tuple[Recursive, ...]


def sample_user() -> User:
    return User(
        email="ann@example.com",
        nickname="annie@example.com",
        history=(
            Place(city="Philadelphia", postal_code=19103),
            Coordinates(latitude=Decimal("40"), longitude=Decimal("-75")),
        ),
    )


def runtime_construct[T](model: type[T], **values: object) -> T:
    """Exercise runtime input boundaries without hiding malformed static calls."""
    return model(**values)


def declare_field(annotation: object, *, default: object = None) -> type[Row]:
    """Build invalid declarations only when a test asks for their error."""
    model = type(
        "InvalidModel",
        (Row,),
        {
            "__module__": __name__,
            "__annotations__": {"value": annotation},
            "value": column(default=default),
        },
    )
    return model
