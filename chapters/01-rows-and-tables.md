# 1. Rows and tables

A row is one record, such as one user. A table holds many rows that have the
same fields. The schema lists those fields and the type of value each one holds.

In SQL you write the schema in a `CREATE TABLE` statement. In grugdb, the schema
is a class:

```python
from grugdb import Column, Database, Row, column


class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


user = User(id=42, name="ann", age=30)
user.name  # 'ann'
```

Each annotation declares one field. `Column[int]` means the field holds an
`int`. Use `column(default=...)` when a field has a default value.

A `Row` behaves like a frozen dataclass. You pass fields by keyword, and you
cannot change a row after it is built. Unlike a dataclass, `Row` checks every
value against its declared type when the row is built:

```python
User(id=42, name="ann", age="30")
# TypeError: invalid value for age: '30'
```

This check is how the database enforces its schema, and the check is strict. A
`bool` is not accepted as an `int`. An enum field accepts the enum member and
rejects its string value.

These field types are allowed:

- scalars such as `int`, `str`, `bytes`, `Decimal`, and `datetime`
- enums
- tuples and frozensets
- unions and `Literal`
- other `Row` models, nested inside a field
- `type` aliases such as `type Email = str`, and `NewType`

Lists, dicts, and `Any` are rejected. The section on immutable rows below
explains why. To nest a record, use another `Row` model instead of a dataclass.

## Tables and row IDs

`Database.table(User)` returns the table for that row class. `insert` returns a
`RowId`:

```python
db = Database()
users = db.table(User)
row_id = users.insert(user)

row_id  # 1
users.get(row_id).name  # 'ann'
```

There are now two IDs. `user.id` is 42, and it is application data. `row_id` is
1, and the table uses it to find the row. A row keeps its row ID for as long as
it exists, even after an update. SQLite works the same way. Every SQLite table
has a hidden `rowid` that is separate from your primary key. Postgres has a
similar hidden column called `ctid`, but `ctid` is the physical location of the
row on disk, and it changes when the row is updated.

Nothing stops you from inserting two users with `id=42`. They get different row
IDs. In chapter 6 you build unique indexes, which reject duplicate keys.

`RowId` is a `NewType` over `int`. At runtime a `RowId` is an integer, but the
type checker rejects `users.get(42)`. This catches the mistake of passing an
application ID where the table expects its own row ID.

## Reading a table

You cannot iterate over a table directly. You read it by starting a query:

```python
users.scan().all()
# [User(id=42, name='ann', age=30)]
```

`scan()` does not copy any rows. It returns a description of "read every row",
and the table is read each time you run that description. If you insert a row
and run the same scan again, the result includes the new row. Inserting a row
while a scan is in progress is not supported. Python's dictionary iterator
raises `RuntimeError` when it detects the change.

## Why rows are immutable

Updating a row builds a new row:

```python
new_user = users.update(row_id, age=31)
user.age  # still 30
```

Building a new row costs some time, but it has three benefits:

- Code that holds the old row never sees it change.
- The old row and the new row can share their unchanged values.
- Transactions in Part 3 can keep the old version until commit without copying
  it, because nothing can change it in place.

These benefits depend on every value inside the row being immutable too. A
frozen row with a `list` field can still be changed with
`user.tags.append(...)`, and the database would not know. For this reason the
schema rejects mutable field types and allows `tuple` and `frozenset` instead.

To build a changed copy of a row yourself, call `replace`:

```python
older = user.replace(age=31)
older.age  # 31
user.age  # 30
```

`replace` builds the new row through the normal constructor, so it checks every
value again. It raises `TypeError` for a value of the wrong type or a field name
that does not exist.

## Fields on the class

A field accessed on the class is different from the same field on a row.
`user.age` is `30`. `User.age` is a `Field[User, int | None]`, which is a
reference to the age field itself:

```python
User.age  # User.age
User.age >= 18  # User.age >= 18
```

Comparing a field reference with a value does not produce `True` or `False`. It
builds an object that describes the condition, and a query uses that object to
test each row. Chapter 2 explains how. Chapter 6 uses field references to name
the field an index covers.

## Your turn

Open `src/grugdb/table.py`. `Table` stores rows in a `dict[RowId, T]` and gives
out increasing IDs. You write these methods: `insert`, `get`, `update`,
`delete`, `update_where`, `delete_where`, `scan`, and `__len__`.

`insert` accepts only rows whose class is exactly the table's model, which is
stored in `self.model`. `update` builds its new row with `replace`. `scan` wraps
the stored rows in a `Scan` query node from `src/grugdb/query.py`.

Be careful with batch updates. `update_where(User.age == 30, age=31)` changes
every row that matches the condition. The condition has a `test(row)` method
that returns whether a row matches. If the third new row is invalid, the table
must still hold the first two old rows. To get this, build every new row before
you store any of them. `delete_where` has a similar trap. Deleting from a
dictionary while you iterate over it raises `RuntimeError`, so collect the IDs
first and delete them afterwards.

Done when:

- `insert` rejects a row whose class is not exactly the table's model, and
  returns a fresh `RowId`.
- `get`, `update`, and `delete` raise `KeyError` for an unknown ID.
- A failed `update` or `update_where` leaves the table exactly as it was.
- Two equal rows can be inserted and get different IDs.
- `scan()` sees every successful write the next time it runs.

```sh
python -m unittest tests.test_table
```

In the next chapter you turn `scan()` into a query engine.

## Go deeper

- [SQLite rowid tables](https://www.sqlite.org/rowidtable.html) describes
  SQLite's hidden `rowid`, which is close to our internal row ID.
- [PostgreSQL system columns](https://www.postgresql.org/docs/current/ddl-system-columns.html)
  describes `ctid`, a physical row location that changes on update.

Next: [filtering and projection](02-filter-and-select.md).
