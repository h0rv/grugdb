# 8. Query planning

In chapter 6, you built an index for each `Unique` field, such as `User.email`.
This query still reads every row and never uses that index:

```python
users.scan().where(User.email == "ada@example.com")
```

The query asks for a scan, so the engine scans. A query planner is the part of a
database that rewrites a query into a faster plan with the same result. Postgres
would see `WHERE email = 'ada@example.com'`, notice the index on `email`, and
use it. This chapter gives grugdb the same ability, starting with a way to see
what a query will do.

## The planner can read the query

`User.email == "ada@example.com"` does not compare anything when Python runs it.
It builds a `Compare` object, and the object records the field, the operator,
and the value:

```python
condition = User.age >= 18
condition.field  # User.age
condition.op  # Op.GE
condition.value  # 18
```

The query is also a tree of plain objects. `users.scan().where(condition)` is a
`Where` node whose `child` is a `Scan` and whose `condition` is the `Compare`
above. A planner can walk that tree and ask each node what it is.

This is why grugdb uses expressions instead of Python functions. A function such
as `lambda user: user.age >= 18` can only be called. The database cannot tell
whether it compares a field, calls an API, or returns a random value, so it
cannot replace the function with an index lookup. An expression describes
exactly what it tests, so the planner can.

grugdb already makes one planning decision.
`join(orders, User.id == Order.user_id)` builds a hash join, because the
condition is a `JoinOn`, an equality between two fields. The join method can see
that it is an equality, so it picks the algorithm from [chapter 3](03-joins.md)
that only works for equalities.

## Build explain()

To check a planner's choices, you first need to see them. Postgres and SQLite
both have an `EXPLAIN` command for this. Add `Query.explain()` in
`src/grugdb/query.py`. It returns an `ExplainResult`, which you define in a new
file, `src/grugdb/plan.py`. It describes the operator tree without running it.
The output could look like this:

```text
Limit n=10                                 estimated 10      observed 10
  OrderBy Order.total desc                 estimated 9,812   observed 9,812
    HashJoin User.id == Order.user_id      estimated 30,000  observed 9,812
      Where User.country == 'US'           estimated 10,000  observed 3,271
        Scan User                          estimated 10,000  observed 10,000
      Scan Order                           estimated 30,000  observed 30,000
```

Record two kinds of numbers separately. Estimated rows are what a node expects
to produce before the query runs. A scan can estimate exactly, because the table
knows its own length. A filter or a join has to guess, and a simple first guess
is "as many rows as my input". Observed rows are what each node actually
produced when the query ran. To count them, run the query through the plan and
have each node count the rows it yields.

Planners make bad choices when their estimates are wrong. In the sample above,
the join expected 30,000 rows and produced 9,812. You can only see a mistake
like that when you record both numbers.

Done when:

- `explain()` describes `Scan` and every operator from Part 1, nested in the
  same way as the query.
- Each node shows what it was built from, e.g., the condition of a `Where`, the
  fields of a `Select`, or the `n` and offset of a `Limit`.
- Calling `explain()` never tests a condition or reads a row. It shows estimated
  rows only.
- After the query runs, the result shows observed rows next to the estimated
  rows for every node, and `Scan` estimates match the table's length.

Write these tests in `tests/test_plan.py`, then run:

```sh
python -m unittest tests.test_plan
```

## A planner with one rule

Next, let the database choose a plan. Write a `Planner` in `src/grugdb/plan.py`
with one rule. When it finds a `Where` over a `Scan`, and the condition is a
`Compare` with `==` on a `UniqueField`, it replaces both nodes with a new query
node, `IndexLookup`. In grugdb, unique fields are the only fields with an index,
so the rule only needs to handle them. `IndexLookup` holds the table, the field,
and the key, and it yields the one matching row, or nothing. In every other
case, the planner leaves the tree alone.

`explain()` shows the choice. The plan for
`users.scan().where(User.email == "ada@example.com")` changes from this:

```text
Where User.email == 'ada@example.com'
  Scan User
```

to this:

```text
IndexLookup User.email == 'ada@example.com'
```

One rule is enough to start, because even one rule must keep the query's
meaning. Both plans must return the same rows under the same `==` rules. A
unique index returns at most one row, so the order of the rows cannot differ
between the two plans.

The rule also has to match the whole condition.
`(User.email == x) & (User.age > 30)` can still use the email index. The plan
looks up the row by email and then tests the rest of the condition on it.
`(User.email == x) | (User.age > 30)` cannot use the index alone, because rows
with any email can match the second half.

Real planners do not apply rules like this one blindly. Postgres is cost-based.
It estimates the cost of each possible plan and picks the cheapest. It reads its
estimates from table statistics, which `ANALYZE` collects, e.g., the number of
rows and the most common values of each column. When a lookup would match a
large part of a table, or the table is small, Postgres scans instead of using
the index. A unique lookup matches at most one row, so grugdb's rule always
helps.

## Moving filters

Moving a filter below a join can save a lot of work. In `poe bench`, filtering
100k users before the join took 52.64 ms, and filtering after the join took
150.36 ms. The users are the left side of the hash join, which is the side that
probes. With the filter first, fewer users probe the hash table, and the join
produces fewer pairs. The orders are the build side, so the join still reads
every order to build its hash table.

A planner can only make this rewrite if it is sure the query means the same
thing afterward. With Python functions, it cannot be sure. Moving a function
changes how many times it runs, and if the function has a side effect, e.g.,
logging or a network call, the program behaves differently. grugdb expressions
have no side effects. Testing `User.country == "US"` once per user or once per
joined pair gives the same rows, so rewrites are safe for the operations grugdb
defines.

Two limits remain. First, the rewrite is safe for inner joins, which are the
only joins grugdb has. In an outer join, rows from one side appear even when
they have no match, with NULL in place of the other side. Moving a filter below
that side can remove rows the outer join would have kept, so the result changes.
Second, an expression can still raise an error, e.g., the "ambiguous"
`TypeError` from reading a field of a self-join. If a rewrite moves a condition,
the query can raise a different error, or raise at a different row.

## Going further

- Push a `Where` below a join when its condition only reads fields from one
  side. Check with `explain()` that the rewrite happened and with a test that
  the rows are the same.
- Estimate how many rows a filter matches from statistics you collect, e.g., the
  number of distinct values in a column, and compare the estimate with the
  observed count.
- Choose between a full sort and a bounded top-N for `order_by(...).limit(n)`.
- Decide when the hash join may build on the smaller side. The swap changes the
  output order, so it is only allowed when the caller does not depend on order.

Start with one tested rule. A general optimizer is a separate project.

## Go deeper

- Phil Eaton's
  [index walkthrough](https://notes.eatonphil.com/database-basics-indexes.html)
  has `getApplicableIndexes`, a planner rule in a few lines.
- Andy Pavlo's
  [query planning lecture](https://www.youtube.com/watch?v=X8EHO8VLeG0) covers
  logical plans and physical plans.
- Wilson Lin's [CoreNN](https://blog.wilsonl.in/corenn/) describes how one
  workload shaped a database's design.

Next: [transactions](09-transactions.md).
