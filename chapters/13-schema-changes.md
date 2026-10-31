# 13. Schema changes

Suppose you released version 1 of an app and saved a snapshot with the design
from [chapter 10](10-snapshots.md).

```python
class User(Row):
    id: Column[int]
    name: Column[str]
```

A week later you add a language preference. You give it a default so that old
code keeps working.

```python
class User(Row):
    id: Column[int]
    name: Column[str]
    locale: Column[str] = column(default="en")
```

When you reopen the file, loading fails with this error:

```text
TypeError: invalid row pickle state
```

The default does not help, because pickle does not save class definitions.
Pickle saves an import path, e.g., `myapp.models.User`, and the values of each
row. When it loads the file, it imports the `User` class that exists now and
gives it the old tuple of two values. The supplied `restore_row` function sees
two values for a model with three fields and raises the error.

An error is the better outcome. If you swap the order of two `str` fields, every
row loads without an error, and each value ends up in the wrong field. If you
rename or move the class, the import fails. The file and the code have to agree
on the schema, and the file does not yet record which schema it was written
with.

## Two version numbers

A snapshot needs two version numbers:

- The format version says how the bytes are laid out. It changes when you change
  the encoding.
- The schema version says which tables and fields the data has. Adding `locale`
  increases it, and the encoding stays the same.

Neither one is the pickle protocol number. One integer schema version for the
whole database is enough.

Storing the version does not solve the problem by itself. If the version is in
the same pickle as the `User` rows, loading the pickle fails before you can read
the version. So old data has to load without using the current `User` class. One
way to do this is to store each table's field names and a plain tuple of values
for each row. You then build `Row` objects only after the migration has run.

## A migration is a decision

A migration converts data from schema version N to version N+1. You cannot
generate a migration by comparing the old and new annotations, because the same
change in the annotations can mean different things:

- Adding a field needs a value for every old row. Filling in `"en"` is one
  policy. Guessing the language from the user's country is a different policy.
- Renaming `name` to `display_name` looks the same in the annotations as
  dropping `name` and adding an empty `display_name`. The rename keeps the data,
  and the drop deletes it. The migration has to state which one it does.
- Changing a type can turn different values into the same value. If you change a
  text key to an `int`, `"01"` and `"1"` both become 1. A unique index from
  [chapter 6](06-indexes.md) then fails on rows that were valid before.

So write each migration as an explicit step. Each step names its source version
and its target version, and it says how the values change. When you load a file,
run every step from the file's version up to the current version. Run the steps
on a copy. Then check the complete result, including types, unique keys, and
rebuilt indexes. Only after that check passes, give the tables to callers or
save the file. Keep the internal row IDs and the next-ID counter the same. A
migration changes values and does not change row identities.

Before you write the migrated file, keep a backup that the old version of your
app can still open. To go back to the old version, you usually restore that
backup and lose the writes made after it.

## Your turn

Create `src/grugdb/migration.py` with a `MigrationStep` (source version, target
version, and an `apply` method) and a `migrate` function. Extend the snapshot
images and loader in `src/grugdb/storage.py` so old data reaches `migrate`
before any current `Row` is built.

To get a version 1 file to test with, write it yourself. Define the version 1
`User` class in a test module, save a database with your snapshot store from
chapter 10, and keep the file as a test fixture. Then change the class to
version 2 and load the fixture. The fixture should use the new format from this
chapter: field names and plain tuples, not pickled `Row` objects.

Done when:

- A version 1 file opens under the version 2 model, with names and row IDs
  preserved and `locale` filled in by your declared policy.
- Reopening the migrated version 2 file does not run the step again.
- A file with an unknown version, or with a missing step, is rejected and left
  untouched on disk.
- A conversion failure on the last row (say, a key collision) leaves no partly
  migrated tables and does not replace the file.

## Go deeper

- [SQLite ALTER TABLE ADD COLUMN](https://www.sqlite.org/lang_altertable.html#altertabaddcol):
  why some changes only edit metadata while new constraints must scan every row.
- [Brandur Leach on renaming a Postgres table](https://brandur.org/fragments/postgres-table-rename#the-details):
  how to rename in two deploys, so that the old and new versions of an app can
  run at the same time.

Next: [corruption and resource limits](14-corruption.md).
