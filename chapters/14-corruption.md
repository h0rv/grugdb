# 14. Corruption and resource limits

Compare two damaged log files.

In the first file, the process was killed while it wrote the last record, so the
file ends halfway through that record. Recovery should throw that record away.
The record was never committed, and no caller was told that it succeeded.

In the second file, one byte changed inside a transaction that committed last
week. To recovery, this damage looks the same as the first case, because in both
files the last record fails its check. Throwing this record away loses data that
you promised to keep, and no error tells anyone about the loss.

A second kind of failure happens when the process runs out of memory or disk
space in the middle of an operation. That kind needs its own rules, which come
after the checksums.

## What a checksum can and cannot tell you

Start with framing. Framing means each record begins with a fixed header that
holds a format version and the length of the payload. Check the header before
you read the payload. Check the length against a reasonable maximum before you
allocate memory for it. If a bit flips in a length field, your code should not
try to allocate 4 GB.

Then add a checksum. A checksum is a short value that you compute from the
record's bytes and store with the record. When you read the record, compute the
checksum again. If the two values differ, the bytes changed. The checksum should
cover the header too.

A good first choice is CRC32, which Python provides as `zlib.crc32`. CRC32
detects accidental damage, e.g., flipped bits or a torn write. It does not
detect deliberate changes, because anyone who edits a record can compute a new
CRC32 for it. A cryptographic hash or signature is needed for that. A CRC32 also
cannot tell a current record from an old one. If the log file is reused, an old
record left over from an earlier run still has a valid checksum. Production logs
add a value to each record that changes per log file, e.g., SQLite's salt
values, to reject such leftovers.

A checksum cannot tell you whether a record was committed. A bad last record can
come from a crash during an append, or from damage to a committed record. Only
the commit evidence in your log from [chapter 11](11-write-ahead-log.md) can
tell these cases apart. When the evidence is not enough to decide, stop recovery
and report the problem. Never skip a bad record in the middle of the log, and
never open a damaged file as an empty database.

A disk read error is a third case. The read returned no bytes, so treat it as an
I/O failure and not as the end of the file.

## Set budgets before memory runs out

Some operators keep all of their input in memory:

- A sort keeps its whole input before it returns the first row.
- Both joins keep the right side in memory.
- A transaction keeps its staged changes next to the committed rows.
- Saving a snapshot may need one more full buffer of bytes.

Catching `MemoryError` does not work as a plan. The cleanup code may need memory
too, and the operating system may kill the process before Python raises the
error. Set explicit budgets instead, counted in rows or in bytes, and check them
as an operator or a transaction grows. When a budget runs out, raise an error
before you publish any change. A row budget is simple to count, but a million
short strings use much less memory than a million long ones.

The disk can also run out of space. Handle `ENOSPC` with the same publication
rules as in [chapter 11](11-write-ahead-log.md). If the write fails before
publication, the old state must survive. If you cannot tell whether publication
happened, refuse further work until the caller reopens the database.

## Cause failures on purpose

You cannot wait for a disk to fail, so you simulate the failures. Wrap the file
object that your store writes through, and make the wrapper fail on a chosen
call. For example, the third write returns a short count, and the fourth write
raises `ENOSPC`. Then move the failure point forward one call at a time through
a small commit, and reopen the database after each run. SQLite tests itself this
way.

Write down what each failure must leave behind:

| Injected failure                      | Required result                                      |
| ------------------------------------- | ---------------------------------------------------- |
| Truncated uncommitted tail            | Reopen the last committed state                      |
| Damaged committed record              | Refuse to open and keep the file for diagnosis       |
| Read error                            | Report an I/O error, not end of file                 |
| Short write or `ENOSPC` before commit | No success reported, previous state intact           |
| `fsync` error around publication      | Report an uncertain outcome and require reopening    |
| Budget exceeded                       | Raise, with no partial transaction or partial result |

## Integrity checks and restores

A checksum checks the bytes. An integrity check checks that the data is
consistent:

- Row IDs are unique.
- Each counter is larger than every row ID in its table.
- Each index, built again from the rows, gives the same lookups as the index in
  memory.

Neither check can bring back a lost value. Only a backup can bring it back, and
only if you have practiced restoring from that backup. Copy the damaged file to
a safe place before you try any repair.

## Your turn

Extend `PickleSnapshotStore` in `src/grugdb/storage.py` (and `LogStore` in
`src/grugdb/log.py`, if you built it) with framing, checksums, and length
limits. Add a `DatabaseImage.validate` integrity check. Put budgets on sorting,
joins, and transaction staging. Write a faulty file wrapper in
`tests/test_failures.py`.

Done when:

- Every row of the failure table above is a passing test.
- A corrupted length field is rejected without a large allocation.
- Duplicate row IDs or a bad counter fail `validate` before any table is
  exposed.

## The end of the course

You have built these parts:

- typed rows and an iterator query engine
- hash indexes, a sorted index, and a B+ tree
- a planner with `explain()`
- transactions, snapshots, and a write-ahead log
- checks that detect damaged files

Production databases use the same parts, with many more edge cases handled.
These resources go further:

- [SQLite's source](https://sqlite.org/src/doc/trunk/README.md) and its
  [architecture overview](https://www.sqlite.org/arch.html): the source is small
  and has detailed comments.
- [CMU 15-445](https://15445.courses.cs.cmu.edu/), Andy Pavlo's database course.
  Several earlier chapters link to its lectures.
- *Database Internals* by Alex Petrov covers storage engines and distributed
  systems in depth.

## Go deeper

- [Dan Luu, "Files are hard"](https://danluu.com/file-consistency/): how
  filesystems behave on errors, and why silent corruption needs its own check.
- [SQLite anomaly testing](https://www.sqlite.org/testing.html#anomaly_testing):
  moving the failure point step by step, including failures during recovery.
- [SQLite malformed-file tests](https://www.sqlite.org/testing.html#malformed_database_files):
  why damaging structural bytes tests different code from ordinary queries.
