from typing import NewType

from .expr import Expr, UniqueField
from .model import Row
from .query import Query, Scan

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
        """`table.scan()` returns a `Query` over the table's rows. It reads rows directly
        without using an index.

        ```python
        users = Table(User)
        users.insert(User(name="Ada"))
        list(users.scan())  # [User(name="Ada")]
        ```
        """
        return Scan(self._rows.values())

    def __len__(self) -> int:
        return len(self._rows)

    def insert(self, row: T) -> RowId:
        if type(row) is not self.model:
            raise TypeError(f"expected {self.model.__name__}, got {type(row).__name__}")
        row_id = RowId(self._next_id)
        self._next_id += 1
        self._rows[row_id] = row
        return row_id

    def get(self, row_id: RowId) -> T:
        return self._rows[row_id]

    def update(self, row_id: RowId, /, **changes: object) -> T:
        row = self._rows[row_id].replace(**changes)
        self._rows[row_id] = row
        return row

    def delete(self, row_id: RowId) -> None:
        del self._rows[row_id]

    def update_where(self, condition: Expr[T], /, **changes: object) -> int:
        new = {i: r.replace(**changes) for i, r in self._rows.items() if condition.test(r)}
        self._rows.update(new)
        return len(new)

    def delete_where(self, condition: Expr[T], /) -> int:
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
