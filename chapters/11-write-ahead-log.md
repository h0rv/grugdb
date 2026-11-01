# 11. The write-ahead log

A database has to keep its data correct when the process dies in the middle of a
commit. You can test this directly. Start the transfer from chapter 9 in a child
process, kill the child during the commit, and reopen the database. Use local
CPython for this chapter's crash and durability tests. The browser cannot start
child processes or test durable filesystem writes.

```python
# A sketch of the test you'll write. transfer.py commits Ann -> Bob and
# calls os._exit(1) at the step named on its command line.
subprocess.run([sys.executable, "transfer.py", "--crash-after", "file-write"])
db = Database.load(path)
# Ann and Bob must now have (100, 50) or (90, 60), and no other pair.
```

Any other pair of balances means the database lost money.

`os._exit` skips `finally` blocks, context managers, and buffer flushing, so it
behaves like `kill -9`. It does not behave like a power failure. This chapter
explains the difference between the two.

The chapter has two parts. Part 1 makes the snapshots from chapter 10 durable,
so a commit writes a full snapshot safely. Part 2 replaces the snapshot per
commit with a log, which is how production databases do it.

## Part 1: durable snapshots

### Where your bytes are

When `write()` returns, your data is almost certainly not on disk yet. The data
passes through several layers, and each call moves it one step further.

| Call                  | What it guarantees                                                                             |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| `file.write()`        | Bytes are in Python's buffer, inside your process.                                             |
| `file.flush()`        | Bytes are handed to the operating system. They survive your process dying.                     |
| `os.fsync(fd)`        | The OS asks the disk to store the file's bytes. They should survive a power cut.               |
| `os.replace(a, b)`    | The name `b` now points at the new file, atomically. The rename itself may still be in memory. |
| `fsync` the directory | The rename is stored too. On POSIX, a directory entry is data like any other.                  |

If you skip the last step, the new file can be fully on disk while the name
still points at the old file after a power failure. These guarantees also depend
on the filesystem and the disk, so write down which ones you assume.

Two more rules apply to `os.fsync`:

- On macOS, `os.fsync` hands the data to the drive but does not make the drive
  flush its own cache. To get the guarantee in the table on macOS, call
  `fcntl.fcntl(fd, fcntl.F_FULLFSYNC)` instead.
- If `os.fsync` fails, do not call it again and assume the data is safe. On
  Linux, the kernel can drop the unwritten pages after a failed fsync, so a
  second call can succeed even though the data never reached the disk. This is
  why grugdb refuses further work after a failed save, instead of retrying.

### When a commit is done

Choose an acknowledgment point. After this point, a return from `commit()` means
the commit survives a crash. With snapshots, the acknowledgment point comes
after the directory fsync.

A crash before that point must leave the old state, and a crash after it must
leave the new state. A crash at the point itself is the hard case. The commit
reached the disk, but the process died before it told the caller, so the caller
does not know the outcome. If the caller is a script that credits an account and
runs again whenever it fails, Bob gets paid twice. An atomic commit prevents a
partly applied transaction. It does not stop the application from applying a
whole transaction twice.

If a save fails after the rename might have happened, memory and disk may no
longer agree. Do not guess which one is right. Mark the database unusable and
make the caller reopen it.

### Your turn: durable snapshots

Extend `PickleSnapshotStore.save` with the fsync steps above, and make
`Transaction.commit` save a snapshot before it reports success. In the docstring
of `Transaction.commit`, write a short failure table. For each of these crash
points, say what reopening shows:

- during serialization
- during the write
- after the fsync
- after the rename
- right before `commit()` returns

Done when:

- A commit that returned is present after reopening.
- A crash at any step leaves a complete old or complete new database, never a
  mix across tables.
- Leftover temp files are ignored on load.
- Disk-full and permission errors raise instead of reporting success.
- A damaged committed file is an error, not an empty database.
- After an uncertain commit, every table method refuses to run until reopened.

Test with a child process that calls `os._exit` at each step, then reopen the
database in the parent process. Put the tests in `tests/test_recovery.py`:

<!-- local-only:start -->

Run the recovery tests from the repository root:

```sh
python -m unittest tests.test_recovery
```

<!-- local-only:end -->

## Part 2: the log

### Why a snapshot per commit is too slow

When you change one balance, the snapshot approach writes every row in the
database again. Production databases avoid this. They append a short record of
the change to a write-ahead log (WAL), fsync the log, and treat the commit as
done. They update the main database file later, in large batches.

When you reopen the database, you load the last snapshot and then replay the
log. To replay means to apply each committed change that the log recorded after
that snapshot. The log is called "write-ahead" because you write it before you
update the database file.

Log the result of each change, not the operation. If you replay "credit Bob 10"
on different data, or replay it twice, you get a different answer. If you replay
"Bob's row is now `Account(balance=60)`", you get the same answer every time.

### A log, record by record

Each record in the log says which transaction it belongs to and what kind of
record it is. A change record holds the new value of one row. A commit record
says that its transaction is complete. Suppose the snapshot holds Ann with 100
and Bob with 50, and transaction T1 moves 10 from Ann to Bob. The log grows like
this:

```text
record 1  txn=T1  change  Account RowId(1) -> Account(name="ann", balance=90)
record 2  txn=T1  change  Account RowId(2) -> Account(name="bob", balance=60)
record 3  txn=T1  commit
```

Recovery loads the snapshot, then reads the log from the start. It keeps the
change records for each transaction aside until it reads that transaction's
commit record. Only then does it apply them. If the process dies after record 2,
recovery finds two changes for T1 and no commit, so it applies nothing, and Ann
and Bob still have 100 and 50.

### The interrupted transfer

The table shows what recovery must do with the log it finds after a crash at
different moments during T1.

| What the log shows after the crash                                               | What recovery must do                                     |
| -------------------------------------------------------------------------------- | --------------------------------------------------------- |
| T1's changes and its commit record, all valid                                    | Apply both: 90 and 60.                                    |
| T1's first change, then nothing: a clean, provably incomplete tail               | Discard T1: 100 and 50.                                   |
| T1 fully synced, but the process died before `commit()` returned                 | Apply both: 90 and 60. The caller can't assume it failed. |
| A damaged record inside an acknowledged transaction, or a tail it can't classify | Stop and report damage. Don't guess.                      |

A damaged last record usually means the crash happened during an append. It can
also mean that a committed record was damaged later. Your record format decides
how well recovery can tell these cases apart. So each record needs a length,
which tells the reader where the record ends. Each record also needs a checksum,
which is a number computed from the record's bytes. The reader computes the
number again and compares it, to check that the bytes have not changed. Write
down which bytes the checksum covers.

Recovery must never apply Ann's change on its own. If recovery finds the debit
without its commit record, the debit must not become visible.

This gives the rule for commit. Write the transaction's records and its commit
record, fsync the log, and only then return. If an append or an fsync fails, you
no longer know what the end of the log contains. Refuse further commits until
you have checked it.

An fsync takes a long time compared to writing a few records, and it often sets
the limit on commits per second. Production databases use group commit for this
reason. Several transactions append their records, and one fsync then makes all
of them durable at once.

### Recover twice

You must be able to run recovery more than once and get the same result. Suppose
a committed transaction after the snapshot inserted a row as `RowId(27)`.

| Action                                         | Correct result                   | Common bug                                   |
| ---------------------------------------------- | -------------------------------- | -------------------------------------------- |
| Reopen                                         | One row, `RowId(27)`.            | The row gets a freshly allocated ID instead. |
| Reopen again                                   | Still one row, `RowId(27)`.      | Two copies, because replay ran twice.        |
| `load()` into a database that already has data | The recovered state replaces it. | Recovered rows are added on top.             |

Replay must also know which log records the snapshot already includes, so that
it does not apply them a second time. Production databases number every record
with a log sequence number (LSN) that only goes up. The snapshot stores the LSN
of the last record it includes, and replay skips every record at or below it.
You can do the same with a record counter. Do not ignore an unexpected duplicate
ID. It can mean that the log is damaged.

### Checkpoints

The log grows with every commit, and replay gets slower as it grows. A
checkpoint fixes this in three steps:

1. Write a new snapshot that includes every change up to some transaction.
1. Store that position, the replay position, together with the snapshot.
1. Delete the log records that the snapshot covers.

Say the log holds committed T1 and T2, and you checkpoint through T1. Recovery
must still apply T2. The table shows what recovery must do after a crash at each
step.

| Crash point                                              | What recovery must do                                          |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| Before the checkpoint is durably published               | Use the old snapshot and replay T1 and T2.                     |
| After the checkpoint, before old log records are removed | Use the checkpoint, skip T1, replay T2.                        |
| During or after removing T1's records                    | Use the checkpoint and replay T2. T2 must survive the cleanup. |

Watch for two mistakes:

- Publish the checkpoint and its replay position together, so that neither one
  ever exists without the other.
- Do not shorten the log in place. If the process crashes halfway through
  rewriting it, you can lose T2. Write the records you keep to a new file and
  rename it, the same way as in chapter 10.

### Your turn: the log

Create `src/grugdb/log.py` with typed records and a `LogStore` with `append`,
`recover`, and `checkpoint`. Connect `append` to `Transaction.commit` and
`recover` to `Database.load`.

The database now needs a place for two files. One option, which is only a
proposal, is a `Database.open(directory)` method. The directory holds the
snapshot and the log, e.g., `snapshot.pickle` and `log.bin`. Logging is on for
any database opened this way.

Each record holds these fields:

- a transaction ID
- a record kind, either change or commit
- a record number, which works like an LSN
- for a change record, the table, the `RowId`, the new row or a mark that the
  row was deleted, and the next-ID counter
- a format version
- a length
- a checksum

If you encode records with pickle, the rule from chapter 10 still applies. Only
load files you wrote yourself. A checksum does not make pickle safe.

Done when:

- Every row of the interrupted-transfer table holds, tested by killing a child
  process between the two changes, before the commit record, and after the
  fsync.
- Reopening twice, and loading into a non-empty database, give exactly the state
  of the recover-twice table.
- A failed append blocks further commits until the log is checked.
- Every row of the checkpoint table holds, reopening twice after each crash.
- `Database.save()` while logging is on acts as a checkpoint.

Add these tests to `tests/test_recovery.py`.

Postgres, and SQLite in WAL mode, recover from crashes with a write-ahead log
too. Their logs record changes to fixed-size pages of the database file, not
whole rows. Postgres also stores an LSN on every page, so replay can skip a
change that is already on the page. SQLite's default mode is a rollback journal,
described below.

## Go deeper

- [SQLite atomic commit](https://sqlite.org/atomiccommit.html): read the
  hardware assumptions and the crash-testing section. SQLite's default mode uses
  a rollback journal. A rollback journal saves the old data before a change,
  while our log saves the new data.
- [SQLite write-ahead logging](https://sqlite.org/wal.html): the overview
  explains how SQLite runs checkpoints.
- [Corruption](14-corruption.md): what you can and cannot recover when the log
  itself is damaged.

Next: [concurrency](12-concurrency.md).
