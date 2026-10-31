"""Static assertions. Index lookups here are never executed at runtime."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, assert_type

from grugdb import Count, Database, Field, Query, RowId, Sum, UniqueField
from tests.typing.models import (
    ContactEmail,
    Coordinates,
    Email,
    KeywordFields,
    Place,
    Priority,
    RequiredAliases,
    Role,
    Status,
    User,
    UserId,
)


def positive(database: Database) -> None:
    keyword_fields = KeywordFields(self=1, row_id=2, pred=3, nothing=None)
    rows = database.table(KeywordFields)
    row_id = rows.insert(keyword_fields)
    assert_type(row_id, RowId)
    assert_type(rows.get(row_id), KeywordFields)
    assert_type(rows.update(row_id, self=2), KeywordFields)
    rows.delete(row_id)
    assert_type(keyword_fields.self, int)
    assert_type(keyword_fields.nothing, None)
    assert_type(keyword_fields.replace(self=2), KeywordFields)
    coordinates = Coordinates(latitude=Decimal("40"), longitude=Decimal("-75"))
    place = Place(city="Philadelphia", postal_code=19103)
    user = User(
        email="ann@example.com",
        user_id=UserId(7),
        backup_email="backup@example.com",
        nickname=None,
        label="work",
        role=Role.READER,
        status=Status.DISABLED,
        priority=Priority.HIGH,
        born=date(2000, 1, 2),
        seen=datetime(2026, 1, 2, 3, 4, 5),
        balance=Decimal("1.25"),
        payload=b"hello",
        pair=(1, 2),
        tagged=(1, "one"),
        scores=(1, 2, 3),
        tags=frozenset({"reader"}),
        reference=7,
        enabled=True,
        version=1,
        administrator=Role.ADMIN,
        state="ready",
        place=place,
        coordinates=coordinates,
        history=(place, coordinates),
    )
    assert_type(user, User)
    assert_type(user.email, ContactEmail)
    assert_type(user.user_id, UserId)
    assert_type(user.backup_email, Email)
    assert_type(user.nickname, ContactEmail | None)
    assert_type(user.label, str)
    assert_type(user.role, Role)
    assert_type(user.status, Status)
    assert_type(user.priority, Priority)
    assert_type(user.born, date)
    assert_type(user.seen, datetime)
    assert_type(user.balance, Decimal)
    assert_type(user.payload, bytes)
    assert_type(user.pair, tuple[int, int])
    assert_type(user.tagged, tuple[int, str])
    assert_type(user.scores, tuple[int, ...])
    assert_type(user.tags, frozenset[str])
    assert_type(user.reference, int | str)
    assert_type(user.enabled, Literal[True])
    assert_type(user.version, Literal[1])
    assert_type(user.administrator, Literal[Role.ADMIN])
    assert_type(user.state, Literal["new", "ready"])
    assert_type(user.place, Place)
    assert_type(user.coordinates, Coordinates)
    assert_type(user.history, tuple[Place | Coordinates, ...])
    assert_type(coordinates.latitude, Decimal)
    assert_type(User(email="default@example.com").nickname, ContactEmail | None)

    aliases = RequiredAliases(
        email="ann@example.com", alternative="backup@example.com", pair=("a", "b"), label="home"
    )
    assert_type(aliases, RequiredAliases)
    assert_type(aliases.email, Email)
    assert_type(aliases.alternative, ContactEmail | None)
    assert_type(aliases.pair, tuple[Email, Email])
    assert_type(aliases.label, str)
    RequiredAliases(email="ann@example.com", alternative=None, pair=("a", "b"), label="work")

    users = database.table(User)
    places = database.table(Place)
    assert_type(User.email, UniqueField[User, ContactEmail])
    assert_type(User.role, Field[User, Role])
    assert_type(users.lookup(User.email, "ann@example.com"), User | None)
    query = users.scan()
    assert_type(query.where(User.role == Role.ADMIN), Query[User])
    assert_type(query.where((User.role == Role.ADMIN) & ~User.nickname.is_none()), Query[User])
    assert_type(query.select(User.email).all(), list[ContactEmail])
    assert_type(query.select(User.email, User.role), Query[tuple[ContactEmail, Role]])
    assert_type(query.order_by(User.born.desc(), User.email), Query[User])
    assert_type(
        query.group_by(User.role, Count(), Sum(User.balance)), Query[tuple[Role, int, Decimal]]
    )
    joined = query.join(places.scan(), User.label == Place.city)
    assert_type(joined, Query[tuple[User, Place]])
    assert_type(
        joined.where(Place.postal_code > 1).select(User.email, Place.city),
        Query[tuple[ContactEmail, str]],
    )
    assert_type(user.replace(role=Role.READER), User)
