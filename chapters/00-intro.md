# Introduction

In this course you build a relational database in pure, typed Python. You start
with tables and a query engine. Then you add joins, hash and B+ tree indexes, a
query planner that explains its choices, transactions, snapshots that survive a
restart, and a write-ahead log that keeps committed data when the process is
killed in the middle of a commit. Along the way you learn what Postgres and
SQLite do when you run a query.

The starting engine is about 650 lines of code, not counting docstrings and
comments. You can read all of it in one sitting. This is a query on it:

```python
class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


class Order(Row):
    id: Column[int]
    user_id: Column[int]
    total: Column[int]


users.scan().where(User.age >= 18).select(User.name).all()
# ['ann']

purchases = users.scan().join(orders.scan(), User.id == Order.user_id)
purchases.select(User.name, Order.total).all()
# [('ann', 5), ('ann', 7), ('bob', 2)]
```

The schema is a Python class, and the query is Python code. The database stores
the row objects you insert, and a query returns those same objects. The type
checker knows that `User.age` holds an `int | None`, so it rejects
`User.age >= "18"`.

## What you will build

The course has three parts and an appendix.

- Part 1 builds a query engine with tables, filters, projections, joins,
  sorting, and grouping. You learn why databases run a query as a tree of small
  operators, and you measure a hash join against a nested-loop join.
- Part 2 makes the engine faster. You profile row construction and fix its
  bottleneck. Then you add hash indexes, sorted indexes, a B+ tree, and a
  planner.
- Part 3 makes the engine safe. You add transactions that commit all their
  changes or none of them, snapshots on disk, and a write-ahead log. Then you
  let several threads use the database at once.
- The appendix covers schema changes and corrupted files.

Parts 1 and 2 take about a weekend. Part 3 takes longer, because durability and
concurrency are harder to get right and to test.

## The one big tradeoff

A condition such as `User.age >= 18` does not compare anything when Python runs
it. `User.age` is a field reference, and comparing it with 18 builds a small
object that records the field, the operator, and the value. The query stores
that object and tests it against each row when the query runs.

Because the condition is data, the database can read it. In chapter 8 you write
a planner that reads `User.email == "ada@example.com"` and answers it from an
index instead of reading every row. The type checker can read it too, so it
rejects a field from the wrong table or a value of the wrong type.

The tradeoff is that conditions have limits and costs:

- Python cannot overload `and`, `or`, and `not`, so you combine conditions with
  `&`, `|`, and `~`. Those operators bind tighter than `>=`, so each comparison
  needs parentheses, e.g., `(User.age >= 18) & (User.name == "ann")`.
- Python cannot overload `in` or `is None` either, so grugdb has
  `User.id.in_([1, 2])` and `User.age.is_none()` instead.
- You can only filter with the operations grugdb supports. You cannot call your
  own function inside a condition.
- Building and testing condition objects is slower than plain Python. Chapter 5
  measures the difference.

SQL also lets the database read the query, because a SQL query is a string that
the database parses. The difference is where the work goes. With SQL, your
program builds query strings and converts the results back into its own objects.
With grugdb, there is no query language and no conversion.

## What this is not

grugdb is a teaching engine. It is not a replacement for SQLite. Chapter 5
compares the two on the same data, and SQLite is several times faster at
filtering.

grugdb is not an ORM. An ORM such as SQLAlchemy translates Python expressions
into SQL and sends them to a separate database server. In grugdb, the engine
runs the query itself, on Python objects in memory, and you write that engine.

The snapshots in chapter 10 use Python's `pickle` module. Loading a pickle can
run any code the file contains, so only load files you created yourself.

## Why the code uses so many types

`Column[int]` is the database's schema. `Row` checks each value against it every
time a row is built, so a string such as `"30"` cannot get into an `age` column.
`RowId` is a separate type from `int`, so the type checker stops you from
passing a user's application ID where the table expects its own internal ID.

Later chapters depend on knowing the type of each field. An index can rely on
its keys having one type. A planner can read which field a condition uses. A
compact storage layout can store integers as packed machine values instead of
one Python object per value.

## Set up

You need Python 3.14 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Run these
commands from the repository:

```sh
uv tool install poethepoet
poe start     # switch to a "work" branch with the exercises blanked out
poe site      # open the course in your browser
```

The `main` branch holds the finished reference engine for Part 1. `poe start`
creates a branch called `work`. On that branch, each method you implement in
chapters 1 to 4 contains `raise NotImplementedError` instead of its code, so
most tests fail at first. The failing tests are your list of tasks. The supplied
tests cover chapters 1 to 5. From chapter 6 on, the engine features do not exist
yet, and you write the tests yourself from each chapter's "Done when" list.

You edit files in `src/grugdb/` and run every command from the repository root:

```sh
poe test      # run the tests
poe bench     # run the benchmarks
poe all       # lint, type check, test, and build the site
```

Your work is in an ordinary git branch. If you are stuck,
`git diff main -- src/grugdb/query.py` shows the reference code, and
`git merge main` brings in course updates.

## How to work

Each chapter explains an idea and then gives you a small piece to build, with a
short "Done when" list. Read the method's docstring first. Then guess what a
small example should return, and make the tests pass. When a test fails, make
the input smaller until you can see the cause.

To learn with a coding agent, ask it to read the
[tutor skill](../.agents/skills/tutor/SKILL.md). It helps you reason about an
exercise without writing the code for you. For example:

> Read .agents/skills/tutor/SKILL.md. Tutor me through chapter 1.

Next: [rows and tables](01-rows-and-tables.md).
