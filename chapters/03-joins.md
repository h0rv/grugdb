# 3. Joins

A join answers questions such as "which user placed each order?" This chapter
covers two ways to compute a join. On 800 users and 2,400 orders, they took
these times:

```text
nested-loop join   155.76 ms
hash join            0.25 ms
```

Both joins read the same data and return the same pairs, and the hash join is
617 times faster. Each join is a few lines of Python, and the whole difference
comes from the algorithm. Postgres `EXPLAIN` output shows the same two
algorithms as `Hash Join` and `Nested Loop`. Postgres also has a third, merge
join, which sorts both inputs on the key and walks them side by side.

## What a join produces

An inner join pairs each left row with each right row that satisfies a
condition:

```python
joined = users.scan().join(orders.scan(), User.id == Order.user_id)
```

Comparing two fields with `==` builds a `JoinOn` object, the same way comparing
a field with a value builds a `Compare`. The result is a
`Query[tuple[User, Order]]`. A user with three orders appears three times, and a
user with no orders does not appear. If two left rows and three right rows share
a key, the result has all six pairs. The inputs can be any query, so you can
join filtered users.

After a join, you can use fields from either side. grugdb finds the row of the
matching model inside each pair:

```python
big_orders = joined.where(Order.total > 4).select(User.name, Order.total)
big_orders.all()  # [('ann', 5), ('ann', 7)]
```

A table joined with itself is a special case. The join runs, but `User.name`
then matches both sides of each pair, and reading it raises a `TypeError` that
says the field is ambiguous. SQL solves this with table aliases, e.g.,
`FROM users AS a JOIN users AS b`. grugdb has no aliases.

## Nested-loop join

The simplest join compares every left row with every right row. With `L` left
rows and `R` right rows, it tests the condition `L × R` times. For 800 users and
2,400 orders, that is almost two million tests, and those tests take most of the
156 ms.

The operator reads the left side once. It visits the right side once for every
left row, so it reads the right side into a list first. The list uses memory,
and the right input must be finite.

Real databases rarely run a nested loop over two full tables. They use it when
the inner side has an index, so each left row costs one index lookup instead of
a pass over the right side. This is called an index nested-loop join.

## Hash join

Most joins test equality, e.g., `User.id == Order.user_id`. For an equality
join, a hash join does much less work. It runs in two phases.

1. In the build phase, it reads the right side once and puts each row in a
   dictionary, keyed by the row's join key.
1. In the probe phase, it reads the left side and looks up each row's key in the
   dictionary.

A dictionary lookup takes about the same time at any dictionary size. So the
total work is about `L + R + output` instead of `L × R`. The output term remains
in every case. If every left key matches every right key, the join still returns
`L × R` pairs.

A hash join needs hashable keys, and it holds the whole build side in memory.
Because a `JoinOn` always describes an equality, `Query.join` always builds a
hash join. The nested-loop join stays useful as the simple version you can check
the hash join against.

## Your turn

`NestedLoopJoin` and `HashJoin` receive the same `JoinOn`. Its `left` field
reads rows from the left input, its `right` field reads rows from the right
input, and `JoinOn.test(left_row, right_row)` checks one pair. Both joins must
return the same pairs in the same order. Pairs follow left input order, and
within each left row they follow right input order.

Done when:

- Both joins agree on ordinary data, duplicate keys on both sides, no matches,
  and empty inputs.
- The nested-loop join reads its right input once per execution, not once per
  left row.
- Keys match by Python `==`, so two `None` keys match. SQL never joins NULL
  keys, so this is one place where grugdb differs from SQL.
- Fields from either side can be filtered and selected after the join.

<!-- local-only:start -->

When working locally, run the query tests from the repository root:

```sh
python -m unittest tests.test_query
```

<!-- local-only:end -->

Implement these methods in `src/grugdb/query.py`:

- `NestedLoopJoin.__iter__`
- `HashJoin.__iter__`

## Measure it

Measure native performance with local CPython once both joins work. The browser
runs Python through WebAssembly, so its timings are not comparable. On our
machine, the benchmark printed this:

<!-- local-only:start -->

Run the benchmark from the repository root:

```sh
poe bench
```

<!-- local-only:end -->

```text
join strategies, users x 3*users orders
  n=   100  nested      2.30 ms  hash      0.03 ms      75x
  n=   200  nested      9.20 ms  hash      0.07 ms     140x
  n=   400  nested     38.51 ms  hash      0.12 ms     317x
  n=   800  nested    155.76 ms  hash      0.25 ms     617x
  n=100000  hash    122.73 ms  (300k orders)
```

Each time the number of users doubles, the nested-loop time grows about four
times and the hash join time about doubles. This growth is what `L × R` and
`L + R` predict. At 100,000 users the nested-loop join would take about 40
minutes, and the hash join takes about an eighth of a second.

The benchmark also measures where the filter goes. With 100,000 users, filtering
before the join took 52.64 ms, and filtering after the join took 150.36 ms.
Filtering first sends fewer rows to the probe phase. It does not shrink the
right side, so the build phase costs the same. A SQL planner moves filters below
joins on its own. In grugdb a condition such as `User.country == "US"` is a data
object, so a planner can see which model it reads and move it. You build that
planner in chapter 8.

As a stretch goal, make `HashJoin` build its dictionary from whichever side is
smaller. Swapping the sides changes the output order, which changes what
`limit(10)` returns. grugdb promises an output order, so the swap changes
results here. A SQL query without `ORDER BY` promises no order, so a SQL planner
can swap the sides whenever it likes.

## Go deeper

- Andy Pavlo, [Join algorithms](https://www.youtube.com/watch?v=MFazkaZKs1s), a
  lecture on nested-loop joins and the build and probe phases of a hash join.
  The lecture counts disk pages, which our in-memory engine does not have.

Next: [sort, limit, and grouping](04-sort-limit-group.md).
