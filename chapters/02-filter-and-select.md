# 2. Filtering and projection

Consider this query:

```python
users.scan().where(User.age >= 18).limit(3).all()
```

Suppose the table holds a million users and the first three are adults. The
database should read three rows to answer this query. It should not read a
million rows, and it should not filter all of them into a list and then keep
three.

## A tree of iterators

Postgres and MySQL run a query as a tree of small operators. Each operator does
one job, e.g., dropping the rows that fail a test. Each operator pulls rows from
the operator below it, one row at a time, and only when the operator above asks
for a row. This design is called the iterator model. It is also called the
Volcano model, after the paper that described it. SQLite takes a different
approach. It compiles each query into bytecode and runs that bytecode in a small
virtual machine called the VDBE. The rows still flow one at a time.

Python already supports this design. An operator is an object with an `__iter__`
method:

```python
def __iter__(self) -> Iterator[T]: ...
```

The query above is a tree with three nodes:

```text
Limit(3)
  └── Where(age >= 18)
        └── Scan(users)
```

`all()` asks `Limit` for rows. `Limit` asks `Where`, and `Where` asks `Scan`. A
row moves back up the tree only if it passes the filter. After the third row,
`Limit` stops asking, so the operators below it stop reading. As a result, the
query reads three rows instead of a million.

Building a query reads no rows. `users.scan().where(...)` only builds the tree.
The table is read each time you iterate over the query, so if you run the same
query after an insert, the result includes the new row. You can run a query
object as many times as you want.

## Conditions are objects

The `where` above receives `User.age >= 18`. `User.age` is a field reference
from chapter 1, and its `>=` method returns a `Compare` object instead of a
bool. The object holds the field, the operator, and the value:

```python
condition = User.age >= 18
condition  # User.age >= 18
condition.test(User(id=1, name="ann", age=30))  # True
```

`Where` calls `condition.test(row)` for each row. Other condition types are
supplied in `src/grugdb/expr.py`:

```python
(User.age >= 18) & (User.name == "ann")  # both must hold
(User.age < 18) | User.age.is_none()  # either may hold
~User.name.in_(["root", "admin"])  # the opposite
```

The parentheses are needed because `&` and `|` bind tighter than comparisons in
Python. Python's own `and`, `or`, and `not` cannot be overloaded. A `Compare`
object raises `TypeError` if you use one of them, because otherwise `a and b`
would silently keep only one of the two conditions.

### Comparisons with None

A row's field can be `None`, and Python raises `TypeError` for `None > 3`. A
query should not stop halfway through because one row has a missing age, so
grugdb defines a rule. An ordering comparison (`<`, `<=`, `>`, `>=`) with `None`
on either side is false. `==` and `!=` follow Python, so `None == None` is true.
To find missing values, use `User.age.is_none()`.

```python
users.scan().where(User.age < 21).all()  # skips users whose age is None
users.scan().where(~(User.age < 21)).all()  # includes users whose age is None
```

Every grugdb condition is either true or false. This is called two-valued logic.
The second line above follows from it. `User.age < 21` is false for a missing
age, so `~(User.age < 21)` is true for that row.

SQL uses three-valued logic instead. A comparison with `NULL` is neither true
nor false. Its result is a third value, `UNKNOWN`, and a `WHERE` clause keeps a
row only when the condition is true. `NOT UNKNOWN` is still `UNKNOWN`, so in SQL
`WHERE NOT (age < 21)` drops the rows whose age is `NULL`, while grugdb keeps
them. `age = NULL` is also `UNKNOWN` for every row, so SQL has a separate
operator, `age IS NULL`, to find missing values. In grugdb, `User.age == None`
works because Python's `None == None` is true. Keep these differences in mind
when you compare grugdb results with a SQL database.

## Filter and project

Two operators cover most of what a SQL `SELECT ... WHERE` does.

- A filter (`where`) keeps the rows that match a condition. The row type stays
  the same, so a `Query[User]` stays a `Query[User]`.
- A projection (`select`) turns each row into the values of some fields.
  `select(User.name)` turns a `Query[User]` into a `Query[str]`, and
  `select(User.name, User.age)` gives a `Query[tuple[str, int | None]]`. The
  type checker tracks the change.

Duplicates stay in the result unless an operator removes them, and rows keep the
order the operator below produced them in.

## Your turn

`Compare.test` reads the field from the row with `self.field.read(row)` and
applies the rule for `None` described above. `Where` keeps matching rows.
`Select` yields plain values for one field and tuples for several fields. The
`Query` methods that build these nodes, `where` and `select`, are supplied.

The tests check laziness with a source that counts how many rows have been
pulled from it. You can use the same method to check your own operators.

Done when:

- Each of the six comparison operators filters rows correctly.
- An ordering comparison with `None` is false, and `User.age == None` finds the
  rows whose age is `None`.
- Neither operator reads a row until someone asks for one.
  `.where(...).limit(3)` on an endless source stops after the third match.
- Order and duplicates are preserved, and empty input gives empty output.
- Running a query twice reads the table twice and leaves the query unchanged.

<!-- local-only:start -->

When working locally, run the query tests from the repository root:

```sh
python -m unittest tests.test_query
```

The join, sort, and grouping tests in that file keep failing until you finish
the next two chapters.

<!-- local-only:end -->

Implement these methods:

- `Compare.test` in `src/grugdb/expr.py`.
- `Where.__iter__` in `src/grugdb/query.py`.
- `Select.__iter__` in `src/grugdb/query.py`.

## What the database can see

Because a condition is an object, the database can read it as well as run it.
`(User.age >= 18).field` is `User.age`, and `.op` is `Op.GE`. `Op` is a
`StrEnum`, so `Op.GE == ">="` is also true. A database that knows a query
filters on `age` can reorder filters, move a filter below a join, or answer the
filter from an index. In [chapter 8](08-planning.md) you write a planner that
does one of these things.

## Go deeper

- Andy Pavlo, [Query execution I](https://www.youtube.com/watch?v=HNtlew7mCc4),
  a CMU database course lecture on the iterator model and blocking operators.
  Our `__iter__` plays the role of the lecture's `Next()`.

Next: [joins](03-joins.md).
