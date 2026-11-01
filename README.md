# grugdb

Build a relational database in pure, typed Python. You start with tables and an
iterator query engine. Then you add joins, hash and B+ tree indexes, a query
planner, transactions, snapshots, and a write-ahead log. Parts 1 and 2 take
about a weekend. Part 3 covers durability and concurrency and takes longer.

```python
class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


users.scan().where(User.age >= 18).select(User.name).all()  # ['ann']
```

Queries are Python expressions. `User.age >= 18` builds an object that the
planner can read and the type checker can check. The engine runs the query
itself, on the row objects you inserted.

Read the course at [grugdb.horv.co](https://grugdb.horv.co), or read the
chapters here on GitHub, starting with the [introduction](chapters/00-intro.md).

## Get started

Open [chapter 1](https://grugdb.horv.co/01-rows-and-tables.html#your-turn) and
edit each assigned method in the lesson. After you pause, edits autosave and
lint, type checks, and relevant tests run automatically, along with the chapter
tests. Editors use standard keys by default. You can change them in Settings in
the sidebar. Expand the optional full workspace to read or edit whole source
files. Open Help for shortcuts and local commands.

Clearing browser data removes saved edits, and edits do not sync between
devices. Download a JSON backup of your edits or a ZIP of the Python project. If
saving fails, download a backup before leaving.

Native profiling, disk durability, crash tests, and threading require local
CPython. The browser has no shell.

<!-- local-only:start -->

For local work, you need Python 3.14 or newer and
[uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/h0rv/grugdb
cd grugdb
uv tool install poethepoet
poe start     # create a "work" branch with the exercises blanked out
poe test      # the failing tests are your task list
```

The [introduction](chapters/00-intro.md#set-up-locally) explains the workflow.

<!-- local-only:end -->

## The course

| Part              | Chapter                                                         |
| ----------------- | --------------------------------------------------------------- |
| 1. A query engine | [1. Rows and tables](chapters/01-rows-and-tables.md)            |
|                   | [2. Filtering and projection](chapters/02-filter-and-select.md) |
|                   | [3. Joins](chapters/03-joins.md)                                |
|                   | [4. Sort, limit, and grouping](chapters/04-sort-limit-group.md) |
| 2. Make it fast   | [5. Profiling](chapters/05-profiling.md)                        |
|                   | [6. Indexes and unique keys](chapters/06-indexes.md)            |
|                   | [7. Build a B+ tree](chapters/07-bplus-tree.md)                 |
|                   | [8. Query planning](chapters/08-planning.md)                    |
| 3. Make it safe   | [9. Transactions](chapters/09-transactions.md)                  |
|                   | [10. Snapshots](chapters/10-snapshots.md)                       |
|                   | [11. The write-ahead log](chapters/11-write-ahead-log.md)       |
|                   | [12. Concurrency](chapters/12-concurrency.md)                   |
| Appendix          | [13. Schema changes](chapters/13-schema-changes.md)             |
|                   | [14. Corruption and resource limits](chapters/14-corruption.md) |

grugdb is a teaching engine. It is not a replacement for SQLite, and the
[profiling chapter](chapters/05-profiling.md) measures how far apart they are.
