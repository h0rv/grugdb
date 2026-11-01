from typing import Any, cast

from grugdb.model import Row
from grugdb.table import Table


class Database:
    """`Database` keeps one table for each row class. Repeated calls to `table()` with
    the same class return the same table.

    ```python
    db = Database()
    users = db.table(User)
    ```
    """

    def __init__(self) -> None:
        self._tables: dict[type, Table[Any]] = {}

    def table[T: Row](self, cls: type[T]) -> Table[T]:
        if cls not in self._tables:
            self._tables[cls] = Table(cls)
        return cast("Table[T]", self._tables[cls])
