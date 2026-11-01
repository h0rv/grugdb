# 9. Transactions

Ann sends Bob 10 dollars. The transfer takes two writes:

```python
accounts.update(ann_id, balance=ann.balance - 10)
# ... something raises here ...
accounts.update(bob_id, balance=bob.balance + 10)
```

If something fails between those two lines, 10 dollars has left Ann's account
and has not reached Bob's. The failure could be a bug, a constraint violation,
or a `KeyboardInterrupt`. Each write is correct on its own, but the two writes
are only correct together.

A **transaction** groups writes into one unit. Either all of the writes happen,
or none of them do:

```python
# After this chapter's exercise:
with db.transaction() as tx:
    accounts = tx.table(Account)
    accounts.update(ann_id, balance=ann.balance - 10)
    accounts.update(bob_id, balance=bob.balance + 10)
```

If the block ends normally, both changes commit. If the block raises, neither
change commits.

## ACID

Databases describe transactions with four properties:

- Atomicity means that all of the transaction's changes happen, or none do.
- Consistency means that the constraints you declared, e.g., unique keys, still
  hold afterwards.
- Isolation means that when transactions run at the same time, the result is the
  same as if they had run one at a time. Databases also offer weaker levels that
  allow specific, named mistakes in exchange for speed.
- Durability means that once a commit is acknowledged, it survives a crash.

This chapter builds atomicity and consistency, in memory. Durability needs a
disk, which [chapter 10](10-snapshots.md) and
[chapter 11](11-write-ahead-log.md) cover. Isolation only comes up when several
transactions run at once, which [chapter 12](12-concurrency.md) covers.

## Stage, then commit

The transaction's writes go to a private place first. Queries inside the
transaction see them. All other code sees the old committed state until the
commit replaces it with the new state in one step.

The immutable rows from [chapter 1](01-rows-and-tables.md) help here. You do not
have to copy a row before you stage an update, because nothing can change the
committed row. The old version and the new version both exist until the commit
picks one.

The simplest design copies the whole `dict[RowId, Row]` when the transaction
starts. The copy shares every row object with the original, so no row is
duplicated. It still costs one pointer per row, so a table with a million rows
copies a million pointers for every transaction, even one that changes a single
row. The alternative is an overlay: the transaction stores only the rows it
inserted, updated, or deleted, and a read checks the overlay before the
committed table. An overlay is faster for large tables and harder to get right.
Start with the copy.

One design for the table view that `tx.table(Account)` returns has four steps:

1. On first use, copy the committed row dict and the table's indexes.
1. Send every read and write through the copies.
1. On commit, check the final state, then replace the committed dict and indexes
   with the copies in one step.
1. On rollback, throw the copies away.

The commit also checks the final state, not each write by itself. Two staged
updates can each pass a check and still conflict, e.g., when they give two users
the same unique email. If the commit finds a conflict, it rejects the whole
transaction, and the committed state stays as it was. The opposite case also
happens. When two users swap emails, the state after the first update has a
conflict, but the final state does not, so grugdb's commit accepts it.

That last rule is a choice. Postgres and SQLite check a unique constraint after
each row is written, so the same swap fails in both of them. Postgres can delay
the check to commit time if you declare the constraint `DEFERRABLE`. The indexes
from [chapter 6](06-indexes.md) must switch to the new state at the same moment
as the rows. Otherwise a lookup could find a row that a scan cannot find.

## Keep the rules small

Postgres allows many transactions at once. SQLite allows many readers but only
one writer at a time. Both have nested transactions through savepoints. grugdb
allows one active transaction per database, on one thread. You still need to
make these decisions before you write code:

- Outside access. While a transaction is active, code might use an old table
  handle directly. Reject that access, because the write would bypass the
  transaction.
- Row IDs after rollback. If a rolled-back insert used `RowId(5)`, decide
  whether the next insert may reuse 5. Either answer works, as long as a stale
  ID never refers to a different live row.
- Finished transactions. After a commit or rollback, the transaction object can
  no longer be used. Calling it again should raise.
- Failed commits. If a commit fails partway through switching state, the
  database must end up fully old or fully new, or refuse further use. It must
  never be left partly updated without an error.

## Your turn

Create `src/grugdb/transaction.py` with a `Transaction` class, and add
`Database.transaction()` in `db.py`. `Transaction.table(Model)` returns a table
view, and reads through that view see the staged writes. The context manager
commits when the block ends normally and rolls back when it raises. Add explicit
`commit()` and `rollback()` methods as well. Then add checks to the existing
`Table` methods so that old handles cannot bypass an active transaction.

Done when:

- The transfer above, with an exception between the two updates, leaves both
  balances unchanged.
- Queries inside a transaction see its own inserts, updates, and deletes.
- A unique key conflict found at commit rejects every change in the transaction.
- Old table handles raise while a transaction is active.
- A second concurrent `db.transaction()`, or any use of a finished transaction,
  raises.
- A rolled-back insert can never make a stale `RowId` point at a different row.

Put your tests in `tests/test_transaction.py`.

<!-- local-only:start -->

When working locally, run the transaction tests from the repository root:

```sh
python -m unittest tests.test_transaction
```

<!-- local-only:end -->

Commits are now atomic, but they only exist in memory. When Python exits, every
committed transaction is lost. The next chapter saves the database to disk.

## Go deeper

- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
  has an introduction and examples of what each isolation level protects
  against. You will use it in chapter 12.

Next: [snapshots](10-snapshots.md).
