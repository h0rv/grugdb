from typing import NewType

from grugdb.expr import Expr, UniqueField
from grugdb.model import Row
from grugdb.query import Query, Scan

RowId = NewType("RowId", int)
RowId.__doc__ = """An internal row identifier, represented at runtime as an integer.

The type checker distinguishes `RowId` from ordinary integers. Tables assign
increasing IDs, separate from any application primary key. A primary key is a
declared unique, non-null key.

```python
row_id = users.insert(user)
users.get(row_id)
```
"""


class Table[T: Row]:
    """`Table[T]` stores rows of one declared type. `insert()` returns an internal row
    ID for retrieving the stored row, separate from any declared `id` field.

    ```python
    users = Table(User)
    row_id = users.insert(User(name="Ada"))
    users.get(row_id)  # User(name="Ada")
    ```

    Use `scan()` to start a query rather than iterating over the table itself.
    """

    def __init__(self, model: type[T]) -> None:
        if not issubclass(model, Row) or model is Row:
            raise TypeError("expected a model inheriting from Row")
        if any(spec.unique for spec in model.fields()):
            raise NotImplementedError("unique fields need indexes, which you build in chapter 6")
        self.model = model
        self._rows: dict[RowId, T] = {}
        self._next_id = 1

    def scan(self) -> Query[T]:
        """Return a lazy Query over the stored rows in insertion order.

        Each execution reads current rows, including updates and duplicates.
        An empty table yields nothing. This is a live view, not a snapshot.
        Changing the table's size during iteration raises RuntimeError.
        """
        return Scan(self._rows.values())

    def __len__(self) -> int:
        """Return the number of stored rows, counting duplicates separately.

        Return 0 for an empty table.
        """
        return len(self._rows)

    def insert(self, row: T) -> RowId:
        """Store the original row object and return a fresh internal RowId.

        IDs increase from 1 and are never reused, even after deletion.
        Equal rows are stored separately. RowId is not a model field's value.
        Require exactly self.model or raise TypeError without changing state.
        Trust the constructed row's field values without checking them again.
        """
        if type(row) is not self.model:
            raise TypeError(f"expected {self.model.__name__}, got {type(row).__name__}")
        row_id = RowId(self._next_id)
        self._next_id += 1
        self._rows[row_id] = row
        return row_id

    def get(self, row_id: RowId) -> T:
        """Return the stored row object for this internal RowId without copying.

        Raise KeyError if the ID is missing, including after deletion.
        """
        return self._rows[row_id]

    def update(self, row_id: RowId, /, **changes: object) -> T:
        """Store and return a replacement row with the requested field changes.

        Keep the internal RowId and scan position. Leave the old object intact.
        Raise KeyError for a missing ID. Invalid field names or values raise
        TypeError and leave the stored row unchanged.
        """
        row = self._rows[row_id].replace(**changes)
        self._rows[row_id] = row
        return row

    def delete(self, row_id: RowId) -> None:
        """Remove the row at this internal RowId and return None.

        Raise KeyError if the ID is missing. Never reuse a deleted ID.
        Preserve the scan order of the remaining rows.
        """
        del self._rows[row_id]

    def update_where(self, condition: Expr[T], /, **changes: object) -> int:
        """Replace rows matching the Expr predicate and return the matched count.

        Return 0 if no rows match, including in an empty table.
        Keep internal IDs and scan order. Leave original row objects intact.
        Invalid field names or values in a replacement raise TypeError.
        Leave all stored rows unchanged if any replacement fails.
        """
        new = {i: r.replace(**changes) for i, r in self._rows.items() if condition.test(r)}
        self._rows.update(new)
        return len(new)

    def delete_where(self, condition: Expr[T], /) -> int:
        """Remove rows matching the Expr predicate and return the deleted count.

        Return 0 if no rows match, including in an empty table.
        Keep unmatched rows and their scan order. Never reuse deleted IDs.
        """
        ids = [i for i, r in self._rows.items() if condition.test(r)]
        for i in ids:
            del self._rows[i]
        return len(ids)

    def lookup[K](self, field: UniqueField[T, K], key: K, /) -> T | None:
        """`table.lookup(Model.field, key)` finds the row whose unique field equals `key`,
        using an index rather than a scan. It returns `None` when no row matches.

        ```python
        # After building indexes in chapter 6:
        contacts.lookup(Contact.email, "ada@example.com")  # Contact | None
        ```
        """
        if field.model is not self.model:
            raise TypeError(f"{field.name} is not a field of {self.model.__name__}")
        field.check(key)
        raise NotImplementedError("index lookup is the chapter 6 exercise; use scan() for now")
