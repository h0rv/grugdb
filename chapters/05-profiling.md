# 5. Profiling

Part 1 ended with a working query engine. Before you make it faster, measure
where the time goes. The benchmark in `bench/run.py` uses a model with two
fields:

```python
class User(Row):
    id: Column[int]
    country: Column[str]
```

`poe bench` builds 100,000 of these rows and the same records as a slotted
dataclass:

```text
building 100k rows: Row vs slotted dataclass
  Row    243.74 ms  dataclass     19.50 ms    12x
```

So the two-field `Row` takes 12 times as long as the dataclass. The `User` model
from Part 1 has a third field of type `int | None`. Building 100,000 of those
rows takes 555 ms, which is 30 times the dataclass. We ran every number in this
chapter on an Apple M5 with CPython 3.14. Your numbers will be different, but
the ratios should be close.

## Profile row construction

To profile the three-field model, save this as `build_rows.py` in the repository
root:

```python
from grugdb import Column, Row, column


class User(Row):
    id: Column[int]
    name: Column[str]
    age: Column[int | None] = column(default=None)


rows = [User(id=i, name="ann", age=30) for i in range(100_000)]
```

Run it under `cProfile`, sorted by the time spent inside each function:

```sh
python -m cProfile -s tottime build_rows.py | head -14
```

```text
14200001 function calls (13900001 primitive calls) in 1.858 seconds

   ncalls  tottime  cumtime  filename:lineno(function)
600000/400000    0.403    1.041  schema.py:30(validate_hint)
  8000000    0.349    0.349  {built-in method builtins.isinstance}
400000/300000    0.245    1.671  schema.py:57(matches)
  1000000    0.194    0.335  typing.py:2495(get_origin)
  1000000    0.189    0.318  typing.py:2525(get_args)
  1000000    0.161    0.239  schema.py:13(resolve)
```

The profiler slows the program down about three times, so compare the functions
with each other and ignore the totals.

The profile shows 142 function calls for each row, and 80 of them are calls to
`isinstance`. `Row.__init__` calls `matches(value, hint)` once for each field.
Each call to `matches` runs `resolve` to unwrap type aliases, runs
`validate_hint` to check that the hint is a supported type, and splits
`int | None` into its parts with `get_origin` and `get_args`. Only after that
does it look at the value. The set of values that `Column[int | None]` accepts
is the same for every row, but the code works it out again for each of the
100,000 rows.

## Your turn

Work out each field's check once, when the class is defined. When you define a
`Row` subclass, `build_schema` in `src/grugdb/model.py` already goes through
every field and calls `validate_hint` on it. At that point, turn each hint into
a small checking function, e.g., one that accepts an `int` or `None` and nothing
else. Store that function with the field. `Row.__init__` then calls the stored
function for each value.

You can decide where to build the checking functions. `src/grugdb/schema.py` is
a good place, next to `matches`. Keep `matches` working, because other code and
the tests still use it.

Done when:

- `python -m unittest` still passes, including the nested value and annotation
  tests. The checks must stay as strict as before, so `True` is still rejected
  for an `int` field.
- Building a row does no hint resolution. Run the profiler again and check that
  `resolve` and `validate_hint` are no longer called for each row.
- `poe bench` shows the two-field `Row` construction within 3 times the
  dataclass time. Write down the number you get.

## A second profile: reading fields in a query

The same method found a slow spot in the query engine while this course was
being written. A query reads fields through `Field.read`, which takes a row and
returns one value. The first version of `Field.read` imported a module and ran
an `isinstance` check on every call. A filter calls it once per row, so a filter
over 500,000 rows took 5.8 times as long as the same filter written as a list
comprehension.

The fix was a fast path. Almost every row a query reads is an instance of the
field's own model, so `Field.read` now checks `type(row) is self.model` first
and reads the value straight from the row's tuple. Joined rows, which are
tuples, take the slower path. After the change, the same benchmark printed this:

```text
query layer vs hand-written comprehension, 500k rows
  grugdb     57.91 ms  comprehension     29.05 ms  1.99x
```

The remaining cost comes from evaluating a condition object for each row. On
100,000 rows, a filter written as `where(User.age >= 18)` took 22.6 ms, and a
plain generator that reads `user.age` directly took 10.3 ms. The condition
object costs that extra time, and in return a planner can read the condition.
Chapter 8 uses that.

## The cost of the rest of the engine

The table below compares grugdb with a plain loop over dataclasses and with
SQLite, which ships with Python as `sqlite3`. Both databases hold the same
100,000 two-field users from `bench/run.py` in memory.

| 100k users                    | grugdb   | dataclass loop | sqlite3  |
| ----------------------------- | -------- | -------------- | -------- |
| Insert rows that are built    | 6.28 ms  |                | 20.83 ms |
| Filter on country, then count | 11.23 ms | 0.83 ms        | 1.66 ms  |

The insert numbers do not compare the same work. A grugdb insert puts an
existing Python object into a dict. A SQLite insert converts each tuple into its
own record format, adds it to a B-tree, and runs it inside transaction
machinery. grugdb also skips the conversion back to Python objects when you read
results.

grugdb is slower at scans. For each row, grugdb runs the `Where` operator, calls
`test` on the condition, and calls `Field.read`. SQLite compiles the query to
bytecode and runs it in an interpreter written in C, over packed records, with
no Python calls per row. The dataclass loop is the fastest pure Python can do
here, with one attribute read and one comparison per row. grugdb is about 13
times slower than that loop, and the difference is the cost of the operators and
the condition objects.

## Memory layout

A Python object is a header plus pointers to other objects. A `Row` keeps its
values in one tuple, and each `int` in that tuple is a separate object. Type
annotations do not change this layout. These layouts are worth comparing:

| Layout                 | What it trades                                             |
| ---------------------- | ---------------------------------------------------------- |
| `dict[RowId, Row]`     | Fast lookup and delete by ID; one object per row           |
| `list[Row]`            | Better scan locality; deletes leave holes or shift entries |
| Slotted dataclass      | Native per-field slots instead of one tuple                |
| `array.array`          | One packed column of machine ints or floats                |
| `struct` + `bytearray` | Explicit binary rows; encoding cost on every access        |
| `mmap`                 | File-backed bytes; still not Python objects                |

The strict types make a compact layout possible. Because the schema guarantees
that every value in a `Column[int]` is an `int`, you can store that column in an
`array.array("q")`. That uses eight bytes per value, instead of a pointer plus a
separate `int` object.

Measure retained memory with `tracemalloc`. `sys.getsizeof` only counts the
outer object, not the objects it points to.

## Going further

- Try a slotted dataclass or `NamedTuple` layout for `Row`, and measure
  construction, field access, and memory.
- Store one `int` column as an `array.array` and compare a filter over it with
  `Table.scan`.
- Report the spread of timings from `best_of`, not only the fastest run.

## Go deeper

- [Too many objects](https://pythonspeed.com/articles/python-object-memory/)
  explains why a million small Python objects use so much memory.
- [The Python profilers](https://docs.python.org/3/library/profile.html)
  explains how to read `cProfile` output.

Next: [indexes and unique keys](06-indexes.md).
