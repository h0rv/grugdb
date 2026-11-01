# 10. Snapshots

So far, grugdb loses all its data when Python exits. The simplest way to keep it
is a snapshot. A snapshot writes the whole database to a file, and a later
process reads that file back.

Calling `pickle.dump` on the database is not enough. This chapter explains which
parts of the state a snapshot has to keep, and why. Use local CPython for this
chapter's filesystem and second-process tests. The browser cannot test disk
durability or start a second process.

## What has to survive

Insert two users, delete the second, save, and reopen. Then insert a third user.

If you saved only the remaining rows, the reopened table thinks the highest ID
it ever used was 1, so it gives the new user `RowId(2)`. The deleted user had
that ID. Any code that kept `RowId(2)` from before the save now finds the wrong
user. So the next-ID counter is part of the state, even though no row stores it.

The rows alone also leave out these things:

- Empty tables. A table with no rows still has a model. You can't read the model
  from the first row when there is no first row.
- The row IDs. If you put rows back through `insert()`, the table gives them new
  IDs. Loading has to keep the original IDs.
- Order. Scans return rows in insertion order, so `first()` and `limit()` depend
  on that order. If you load the rows in a different order, the same query
  returns a different answer.
- A format version. A later version of grugdb needs to recognize a file it can't
  read, instead of guessing at its meaning.

Do not save queries, callbacks, locks, or indexes. You can build the indexes
again from the rows when you load.

## Pickle and trust

Pickle turns a graph of Python objects into bytes, and turns the bytes back into
objects. It keeps every distinction our rows rely on, e.g., `None` stays
different from `""`. We start with pickle for that reason.

Pickle has two limits. First, it stores each class by its import path, e.g.,
`app.models.User`, and not the class definition. The process that loads the file
must be able to import the same model classes, and they must still have the same
fields. A `TableImage` that holds a model class therefore holds only that path.
[Chapter 13](13-schema-changes.md) deals with what happens when the class
changes. Second, loading a pickle can run any code that the file contains. Only
load files you wrote yourself. Checking the result after loading does not help,
because the code has already run by then.

Test the save and load in a second process. In the first process, the original
classes and objects are still in memory, and they can hide bugs.

## Check a loaded file before you use it

A file you wrote yesterday can still be wrong when you read it today. A full
disk can cut it short, someone can edit it by hand, or an older version of your
code can have written it. Before you give the loaded tables to any caller, check
these things:

- The format version is one you know.
- Each table holds only rows of its model.
- No row ID appears twice.
- The counter is larger than every row ID.

Do these checks before you put the data into dictionaries. If two rows share an
ID and you build a dictionary first, the second row replaces the first without
an error, and you can no longer detect the duplicate.

Loading either replaces the whole database or fails. It never merges the file
into tables you already have, and it never leaves part of a file loaded. A
missing file raises `FileNotFoundError`. Loading a missing file does not create
an empty database.

## Write the new file next to the old one

A common bug works like this. You open `db.pickle` for writing, which empties
the file, and the process dies halfway through the write. The old database is
gone, and the new file is incomplete.

Write the complete image to a temporary file in the same directory instead, in
this order:

1. Write the bytes to the temporary file.
1. Call `flush()` to hand Python's buffer to the operating system.
1. Call `os.fsync()` on the file to ask the disk to store it.
1. Call `os.replace()` to move the temporary file over the old name.
1. Call `os.fsync()` on the directory, so the rename itself is stored.

A rename within one filesystem is atomic, so a reader sees either the old file
or the new file and never a mix of the two. If anything fails before the rename,
delete the temporary file. The old database stays as it was.

The fsync calls matter only for power failures. Without step 3, the rename can
reach the disk before the file's bytes do. After a power cut, the name then
points at an empty or partial file, which is worse than keeping the old one. For
this chapter you can test only process crashes. The next chapter looks at power
failures in detail.

## Your turn

Create `src/grugdb/storage.py` with two small dataclasses:

- `TableImage` holds the model, the row IDs and rows, and the next-ID counter.
- `DatabaseImage` holds the table images and a format version.

Add a `PickleSnapshotStore` class that saves and loads a `DatabaseImage` at a
path. Because the image is separate from the store, you can later replace pickle
with your own format without changing the rest of the code. Then add
`Database.save()` and `Database.load()`.

Done when:

- A second process can load the file and query it, given importable models.
- Deleted IDs are never reused after reopening, and empty tables survive.
- Scan order and value types (`bytes`, `Decimal`, enums, nested rows) survive.
- Bad images are rejected before any table is exposed: unknown version, wrong
  row class, duplicate IDs, or a counter that's too small.
- A save that fails partway leaves the old file loadable and no temp file
  behind.
- Indexes are rebuilt on load.

Put your tests in `tests/test_storage.py`.

<!-- local-only:start -->

Run the storage tests from the repository root:

```sh
python -m unittest tests.test_storage
```

<!-- local-only:end -->

## Going further

- Replace pickle with your own encoding using `struct`. Write down one row that
  holds `None`, a non-ASCII string, raw bytes, and a `Decimal`. Then work out
  how a reader finds where each value ends and what type it has.
- Compare file size, save time, and load time with pickle in `bench/storage.py`.
  Compare only formats that keep the same types.
- After you have transactions, save on every commit. Each commit then writes the
  whole database again, even when only one row changed. The next chapter avoids
  that cost.

## Go deeper

- [SQLite's database header](https://www.sqlite.org/fileformat2.html#the_database_header):
  compare its fields with yours. Some of its fields exist because SQLite reads
  single pages instead of whole files. Find out which ones.
- [pickle](https://docs.python.org/3/library/pickle.html): read the security
  warning and the section "What can be pickled and unpickled?".

Next: [the write-ahead log](11-write-ahead-log.md).
