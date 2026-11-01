# 12. Concurrency

Chapter 9 allowed one transaction at a time, on one thread. This chapter drops
the one-thread rule and lets a second thread use the database. A reader scans
`accounts` and adds up the balances, while a writer moves 10 dollars from Ann to
Bob. Use local CPython for this chapter. The browser workspace cannot run
threading tests.

Chapter 9's commit swaps in all of a transaction's changes at once, so this
reader can never see the debit without the credit. The problem appears as soon
as some write skips that rule, e.g., two plain `accounts.update()` calls outside
a transaction. If the reader passes Ann after the first update and reaches Bob
before the second, its total is 10 dollars short, even though both balances end
up correct.

Preventing this is isolation, the I in ACID. A database gives isolation when the
result of running transactions at the same time is the same as running them one
at a time in some order. This strongest level is called serializable. Databases
also offer weaker levels, which allow some of these named anomalies:

- A dirty read sees another transaction's change before it commits.
- A non-repeatable read reads the same row twice and gets two different values,
  because another transaction committed in between.
- A phantom runs the same query twice and gets a different set of rows.
- A lost update happens when two transactions read the same value and both write
  a new value based on it, so one write is lost.
- Write skew happens when two transactions each change a different row, based on
  a condition that the other transaction breaks. Isolation is a separate problem
  from durability. A database can survive every crash and still show readers a
  state that never existed.

Python's global interpreter lock (GIL) keeps a single dictionary operation from
being interrupted halfway. A transaction is many operations, and the GIL can
switch threads between any two of them, so the GIL does not provide isolation.

## Start with one lock

The simplest correct design uses one `threading.Lock` for the whole database.
Every transaction and every read acquires the lock, does its work, and releases
the lock. Only one operation runs at a time, so this design is serializable and
none of the anomalies above can happen.

This design is slow when many threads want the lock. It is easy to get right,
but it still has two traps.

### A lazy query runs after scan() returns

`users.scan()` returns a query object, and the rows are read later, when someone
iterates over it. If `scan()` acquires the lock and releases it before it
returns, the reading happens without the lock. So the lock has to cover the
iteration. A caller can stop iterating early and never come back:

```python
first = next(iter(users.scan()))  # the generator is abandoned, not finished
```

In CPython, the abandoned generator is usually freed right away, because nothing
refers to it anymore. Freeing it runs its cleanup and releases the lock. But if
the generator is part of a reference cycle, or the code runs on another Python
implementation, it waits for the garbage collector, and the lock stays held
until then. You have two options:

- Hold the lock only while the query runs, and make the caller release it
  explicitly.
- Read the whole result into a list while holding the lock, and release the lock
  before returning.

Start with the second option. It costs memory for the whole result, but no
caller can forget to release the lock.

### A callback can call the database

A `where` predicate can run any Python code. If the predicate queries the
database while the scan holds a lock that cannot be acquired twice by the same
thread, the thread waits for itself forever. A reentrant lock, which the same
thread can acquire again, avoids the hang. It leaves a harder question open,
because a write from inside a predicate would change the table halfway through
the scan. Decide whether callbacks may use the database at all.

## Your turn

Add one lock to `Database` and use it in `Database.transaction`, in every
`Table` method (including old handles), and in `Scan.__iter__`. Document the
read boundary and the rule for abandoned scans in the `Table.scan` docstring.

Done when:

- The summing reader never sees a half-applied transfer, however you interleave
  the threads.
- A transaction that raises still releases the lock.
- An abandoned scan doesn't block later writers forever.
- No table method can observe rows and indexes out of sync.

Put the tests in `tests/test_concurrency.py`.

<!-- local-only:start -->

Run the concurrency tests from the repository root:

```sh
python -m unittest tests.test_concurrency
```

<!-- local-only:end -->

Threading bugs often do not show up on a normal run. Use `threading.Event` or
`threading.Barrier` to force the bad interleaving. Do not rely on `sleep` to
produce it.

## Going further

- Readers that do not wait for writers. Give each reader a fixed committed
  version of the database to scan while a writer works. A version is a
  `dict[RowId, Row]` plus its indexes. Rows are immutable, so two versions can
  share most of their row objects. The hard parts are keeping the row map and
  the indexes from the same version, and deciding when to delete an old version.
  This design is called multi-version concurrency control (MVCC). Postgres keeps
  every row version in the table, marks each version with the transactions that
  created and deleted it (its `xmin` and `xmax`), and later removes dead
  versions with `VACUUM`.
- Writers that overlap. Let two transactions run at the same time and check for
  conflicts at commit. Test a lost update and write skew. For write skew, use
  two doctors who each go off call because the other one is still on call. A
  check for "did both transactions write the same row?" catches the lost update
  but not the write skew. State whether you promise snapshot isolation, which
  allows write skew, or full serializability.
- Free-threaded Python. Run the same tests on a free-threaded CPython build.
  Threads that run in parallel do not make a change with several steps atomic.
  If your locking is correct, the tests pass on both builds.

This chapter does not cover two things. Async does not speed up query execution,
because query execution uses the CPU and does not wait on I/O. A
`threading.Lock` only coordinates threads in one process, so two processes that
share a file need file locks.

## Go deeper

- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html):
  which anomalies each isolation level allows, with examples.
- [Python free-threading guide](https://docs.python.org/3/howto/free-threading-python.html):
  what still needs explicit locking without the GIL.

The appendix is optional. It covers schema changes and damaged files.

Next (optional): [schema changes](13-schema-changes.md).
