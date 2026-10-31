# 6. Indexes and unique keys

To find one user by email, the engine currently reads every row:

```python
users.scan().where(User.email == "ada@example.com").first()
```

With a million users, this query can test a million rows to find one. An
**index** solves this. An index is a second data structure, kept next to the
table, that maps a key to the IDs of the rows with that key. A Python dict from
email to `RowId` works as a first index.

An index is a copy of information that is already in the table. Every insert,
update, and delete now has to change two places. If the table and the index ever
disagree, lookups return wrong answers without raising an error. Most of this
chapter is about keeping them in agreement.

## Declaring a key

Mark a field as unique by annotating it with `Unique`:

```python
from grugdb import Column, Row, Table, Unique


class User(Row):
    email: Unique[str]
    age: Column[int]
```

On a row, `user.email` is a `str`. On the class, `User.email` is a
`UniqueField[User, str]`, which is a typed reference to the field. A unique
field cannot have a default, because a second row with the same default would
conflict with the first. You pass the field to `Table.lookup`:

```python
# After this chapter:
users.lookup(User.email, "ada@example.com")  # User | None
```

The type checker knows that the key must be a `str` and that the result is a
`User`. `users.lookup(User.age, 30)` is a type error, because `age` is not
unique.

Right now, `Table(User)` raises `NotImplementedError` for any model with a
`Unique` field. We did this on purpose. A table that accepted the declaration
without enforcing it would let duplicate keys in without any error.

## When an index helps

Suppose you have a table of jobs with an index on `status`. With the index, you
can find the one failed job among a million at once. But 999,000 of the jobs are
pending, so a query for pending jobs still reads almost every row. Every status
change also has to update the index. An index helps when lookups are frequent
and each lookup matches few rows. It slows the database down when writes are
frequent and lookups match most of the table. Postgres and SQLite have the same
tradeoff, which is why they do not index every column.

## Build a hash index

Create `src/grugdb/index.py`. Start with a small interface that any equality
index can implement:

```python
class EqualityIndex[K: Hashable](Protocol):
    def add(self, key: K, row_id: RowId) -> None: ...
    def remove(self, key: K, row_id: RowId) -> None: ...
    def lookup(self, key: K) -> Iterator[RowId]: ...
```

The index stores row IDs, and the rows stay in the table. A `HashIndex` allows
many row IDs for each key. In grugdb, only `Unique` fields get an index through
the public API. The interface still allows several row IDs per key, so the same
code can serve a non-unique index later.

Use `Model.fields()` to find the declared fields. It returns a tuple of
`FieldSpec` objects, defined in `src/grugdb/model.py`. Each `FieldSpec` has a
name, a position, and a `unique` flag. To read a field from a row, call
`User.email.read(row)`. `Field.read` is defined in `src/grugdb/expr.py`.

Then connect the index to `src/grugdb/table.py`. `Table.__init__` builds an
index for each declared key instead of raising, and every write keeps the
indexes correct.

`float("nan")` is not equal to itself, so an equality lookup can never find it.
Reject keys like that instead of storing them.

## Unique indexes

A `UniqueIndex` allows at most one row ID for each key. An update may keep the
row's own key. An insert or update that conflicts with another row must fail and
leave both the table and its indexes unchanged.

Batch updates are harder to get right. Look at this batch:

```python
users.update_where(User.age > 60, email="retired@example.com")
```

No row has that email yet, so each replacement passes when you check it against
the old table. But if two users are over 60, the batch gives both of them the
same email. The opposite mistake is also easy to make.
`update_where(User.age > 30, age=31)` keeps every row's email, and a careless
check reports each row as a conflict with itself. To avoid both mistakes, check
the complete proposed state first. The proposed state is the old rows, minus the
rows being replaced, plus the new rows. Apply the batch only if that state has
no conflicts. In chapter 9, the same rule lets two rows swap emails in one
transaction.

In grugdb, `None` is an ordinary key, so a unique index allows only one row with
`None`. SQL databases allow many rows with NULL in a unique column, because NULL
is never equal to NULL in SQL. grugdb follows Python, where `None == None` is
true.

Done when:

- `lookup` returns each matching row ID once, and nothing for a missing key.
- Insert, update, delete, `update_where`, and `delete_where` keep every index in
  agreement with a scan.
- A unique conflict, including one between two rows of the same batch, changes
  nothing.
- A second row with `None` in a unique field is a conflict.
- A batch that leaves each row's unique key unchanged succeeds.
- `users.lookup(User.email, ...)` returns the stored row or `None`.

Write tests for these in `tests/test_index.py`, then run:

```sh
python -m unittest tests.test_index tests.test_table
```

## Sorted indexes and ranges

A hash index can find rows where the email equals a value. It cannot find rows
where the age is between 20 and 30, because hashing puts nearby keys in
unrelated places. A range query needs the keys in order.

Add a `SortedIndex` that keeps `(key, row_id)` pairs in a sorted list and uses
`bisect` to find the start and end of a range. Use half-open ranges, which
include `low` and exclude `high`, the same as `range()` and slicing. Each entry
includes the row ID, so equal keys stay distinct.

Finding a boundary among `n` entries takes `O(log n)` comparisons. Returning `k`
matches takes `O(k)` more. Inserting into the middle of a Python list moves
every entry after it, which is `O(n)`. The next chapter replaces the list to
avoid that cost.

Done when:

- `range(low, high)` returns the same entries that a scan would find, for empty,
  narrow, and broad ranges.
- All equal keys with different row IDs are returned, and `high` is excluded.
- Keys with no consistent ordering, e.g., a mix of `int` and `str`, are
  rejected.

Then time `range` against a scan with the same filter. Check that the results
match before you compare times.

## Go deeper

- [SQLite's query planner](https://sqlite.org/queryplanner.html), sections 1.3
  to 1.7, has diagrams of how keys, row IDs, and rows relate.
- [Anatomy of an SQL index](https://use-the-index-luke.com/sql/anatomy) shows
  what an ordered index looks like on disk.

Next: [build a B+ tree](07-bplus-tree.md).
