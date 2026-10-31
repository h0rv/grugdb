import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from grugdb import Column, Database, Row
from grugdb.query import HashJoin, NestedLoopJoin


class User(Row):
    id: Column[int]
    country: Column[str]


class Order(Row):
    id: Column[int]
    user_id: Column[int]
    total: Column[int]


@dataclass(frozen=True, slots=True)
class PlainUser:
    id: int
    country: str


COUNTRIES = ["US", "CA", "MX", "BR", "FR", "DE", "JP", "IN", "UK", "AU"]


def make(n_users: int) -> tuple[Database, list[User], list[Order]]:
    rng = random.Random(0)
    db = Database()
    users = [User(id=i, country=rng.choice(COUNTRIES)) for i in range(n_users)]
    orders = [
        Order(id=i, user_id=rng.randrange(n_users), total=rng.randrange(100))
        for i in range(n_users * 3)
    ]
    for u in users:
        db.table(User).insert(u)
    for o in orders:
        db.table(Order).insert(o)
    return db, users, orders


def best_of(fn: Callable[[], object], runs: int = 3) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times)


def ms(seconds: float) -> str:
    return f"{seconds * 1000:9.2f} ms"


def nested_time(n: int) -> float:
    db, _, _ = make(n)
    users, orders = db.table(User), db.table(Order)
    return best_of(NestedLoopJoin(users.scan(), orders.scan(), User.id == Order.user_id).all)


def hash_time(n: int) -> float:
    db, _, _ = make(n)
    users, orders = db.table(User), db.table(Order)
    return best_of(HashJoin(users.scan(), orders.scan(), User.id == Order.user_id).all)


def joins() -> None:
    print("join strategies, users x 3*users orders")
    for n in (100, 200, 400, 800):
        nested, hashed = nested_time(n), hash_time(n)
        print(f"  n={n:>6}  nested {ms(nested)}  hash {ms(hashed)}  {nested / hashed:6.0f}x")
    print(f"  n=100000  hash {ms(hash_time(100_000))}  (300k orders)")


def overhead() -> None:
    print("query layer vs hand-written comprehension, 500k rows")
    db, users_list, _ = make(500_000)
    users = db.table(User)
    query = users.scan().where(User.country == "US").select(User.id)

    def by_hand() -> list[int]:
        return [u.id for u in users_list if u.country == "US"]

    assert query.all() == by_hand()
    layer, by_hand_time = best_of(query.all), best_of(by_hand)
    print(f"  grugdb {ms(layer)}  comprehension {ms(by_hand_time)}  {layer / by_hand_time:4.2f}x")


def pushdown() -> None:
    print("filter after join vs before join, 100k users")
    db, _, _ = make(100_000)
    users, orders = db.table(User), db.table(Order)

    on = User.id == Order.user_id
    after = users.scan().join(orders.scan(), on).where(User.country == "US")
    before = users.scan().where(User.country == "US").join(orders.scan(), on)
    assert after.all() == before.all()
    print(f"  after {ms(best_of(after.all))}  before {ms(best_of(before.all))}")


def construction() -> None:
    print("building 100k rows: Row vs slotted dataclass")
    n = 100_000

    def rows() -> list[User]:
        return [User(id=i, country="US") for i in range(n)]

    def plain_rows() -> list[PlainUser]:
        return [PlainUser(id=i, country="US") for i in range(n)]

    row, plain = best_of(rows), best_of(plain_rows)
    print(f"  Row {ms(row)}  dataclass {ms(plain)}  {row / plain:4.0f}x")


def sqlite_comparison() -> None:
    print("grugdb vs in-memory sqlite3, 100k users")
    n = 100_000
    rows = [User(id=i, country=COUNTRIES[i % len(COUNTRIES)]) for i in range(n)]
    plain = [PlainUser(id=r.id, country=r.country) for r in rows]
    values = [(r.id, r.country) for r in rows]

    def grug_insert() -> None:
        users = Database().table(User)
        for r in rows:
            users.insert(r)

    def sqlite_insert() -> None:
        con = sqlite3.connect(":memory:")
        con.execute("create table users (id integer, country text)")
        con.executemany("insert into users values (?, ?)", values)

    users = Database().table(User)
    for r in rows:
        users.insert(r)
    con = sqlite3.connect(":memory:")
    con.execute("create table users (id integer, country text)")
    con.executemany("insert into users values (?, ?)", values)

    def grug_count() -> int:
        return users.scan().where(User.country == "US").count()

    def plain_count() -> int:
        return sum(1 for u in plain if u.country == "US")

    def sqlite_count() -> int:
        (count,) = con.execute("select count(*) from users where country = 'US'").fetchone()
        assert isinstance(count, int)
        return count

    assert grug_count() == plain_count() == sqlite_count()
    print(
        f"  insert built rows  grugdb {ms(best_of(grug_insert))}  "
        f"sqlite {ms(best_of(sqlite_insert))}"
    )
    print(
        f"  filter + count     grugdb {ms(best_of(grug_count))}  "
        f"dataclass loop {ms(best_of(plain_count))}  sqlite {ms(best_of(sqlite_count))}"
    )


if __name__ == "__main__":
    joins()
    overhead()
    pushdown()
    construction()
    sqlite_comparison()
