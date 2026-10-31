# 4. Sort, limit, and grouping

In grugdb, operators run in the order you chain them. Suppose a table of scores
holds the values 10, 90, and 80, in that order. These two queries differ only in
the order of `limit` and `order_by`:

```python
class Score(Row):
    value: Column[int]


scores.scan().limit(2).order_by(Score.value.desc()).select(Score.value).all()  # [90, 10]
scores.scan().order_by(Score.value.desc()).limit(2).select(Score.value).all()  # [90, 80]
```

The first query takes the first two scores and then sorts them. The second query
sorts all the scores and then takes the top two. Only the second query returns
the two highest scores.

SQL prevents this mistake, because `ORDER BY` always runs before `LIMIT`, in
whatever order you write them. In grugdb you can read the execution order from
the code, but you are responsible for getting it right.

## Blocking operators

The operators from chapter 2 stream their rows. `where` can return its first
match before it reads the rest of the table, and `limit` can stop the whole tree
early.

A sort cannot stream. The smallest value might be in the last row, so a sort
must read its entire input before it returns any row. An operator that must read
all of its input first is called a blocking operator. Grouping with a
dictionary, which databases call hash aggregation, is also blocking, because a
group's total is final only when the input ends. If the input is already sorted
by the group key, a database can finish each group as soon as the key changes,
so that kind of grouping can stream.

You can see the cost of this. `order_by(...).limit(1)` on a million rows still
reads and sorts all million rows. The limit sits above the sort, so it cannot
stop the scan early.

## Limit

`limit(n, offset=0)` skips `offset` rows and returns at most `n` rows. Limit is
the operator that lets a lazy query stop early. `limit(3, offset=2)` on an
endless source should pull exactly five rows and stop. `limit(0)` should pull no
rows. The supplied code rejects negative values when the node is built.

## Sort

`order_by` takes one or more keys. A field sorts ascending, and `field.desc()`
sorts descending:

```python
users.scan().order_by(User.age.desc(), User.name)
```

This sorts by age, largest first, and sorts users of the same age by name, A to
Z. Each key has its own direction.

Python's sort is stable, which means rows with equal keys keep their input
order, also when you sort in reverse. Stability lets you sort by several keys
with several sorts. Sort by the last key first and by the first key last. The
last sort decides the main order, and rows that tie on it keep the order from
the sorts before it. Each pass can use its own direction, so a descending key
gets `reverse=True` on its pass and an ascending key does not.

Python cannot compare `None` with an integer, so `order_by` needs a rule for
`None`. grugdb sorts `None` after every other value. So `None` comes last in an
ascending sort and first in a descending sort. Postgres uses the same rule by
default.

You can get this rule from Python's own sort with a tuple key. The key
`(value is None, value)` sorts every `None` after every other value, because
`False` sorts before `True`. Python compares the second item only when the first
items are equal, so it never compares `None` with an integer. With
`reverse=True`, the same key puts `None` first.

## Group

`group_by` takes a key field and any number of aggregates:

```python
orders.scan().group_by(Order.user_id, Count(), Sum(Order.total)).all()
# [(1, 2, 12), (3, 1, 2), (None, 1, 99)]
```

The result has one tuple per distinct key, with the key first and then one total
per aggregate. Keys appear in the order the query first sees them. `Count`,
`Sum`, `Min`, and `Max` are supplied in `src/grugdb/expr.py`.

These aggregates follow SQL in some ways and differ in others:

- `Count()` counts rows, like SQL's `COUNT(*)`. grugdb has no `COUNT(col)`,
  which in SQL counts only the non-NULL values of one column.
- `Sum`, `Min`, and `Max` skip `None` values, as SQL does.
- A group whose values are all `None` sums to 0. SQL returns NULL for that
  group.
- `Min` and `Max` return `None` for that group, so their result type includes
  `None`.
- `Sum` only accepts numeric fields. ty rejects `Sum(User.name)`.

An aggregate does not need the whole group at once. Each one has a `start()`
value, and `add(total, row)` folds one more row into the running total. So
`GroupBy` keeps one running total per key and per aggregate, and it never keeps
the rows themselves. Summing a million orders for ten users holds ten numbers in
memory, not a million rows.

## Your turn

Implement `Limit.__iter__`, `OrderBy.__iter__`, and `GroupBy.__iter__` in
`src/grugdb/query.py`. For `GroupBy`, use each aggregate's `start` and `add`.

Done when:

- `limit` pulls only the skipped rows plus the returned ones. `limit(0)` pulls
  nothing, and asking for more rows than exist returns the rows that exist.
- `order_by` keeps equal keys in input order in both directions, applies several
  keys with their own directions, and sorts `None` last ascending and first
  descending.
- `group_by` yields `(key, *totals)` in first-seen key order, and empty input
  gives no groups.

```sh
python -m unittest tests.test_query
```

Every test in the file should pass now. You have a query engine with scans,
filters, projections, two join algorithms, sorting, limits, and grouping.

## Stretch goals

- Write a top-N operator. `order_by(...).limit(10)` sorts a million rows to keep
  ten of them. A heap with a fixed size (see `heapq`) holds only ten rows at a
  time. Make your operator return the same rows as a stable full sort, including
  ties and offsets, and test it against one.
- Add an `Avg` aggregate. Its running total holds two numbers, the sum and the
  count. The final value is computed from both, so `Aggregate` needs a new
  `finish(total)` step that `GroupBy` calls before it yields each group.

In Part 2 you measure how fast the engine is. The first profile finds a slow
spot outside the query operators.

## Go deeper

- Julia Evans,
  [SQL queries don't start with SELECT](https://jvns.ca/blog/2019/10/03/sql-queries-don-t-start-with-select/),
  explains the order in which SQL runs its clauses, which differs from the order
  you write them.

Next: [Part 2, profiling](05-profiling.md).
