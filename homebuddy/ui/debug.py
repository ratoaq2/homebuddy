"""The text of the debug data of a detector."""

from __future__ import annotations

from datetime import datetime, tzinfo
from itertools import zip_longest

from homebuddy.model import Table, Value

TIME_FORMAT = '%H:%M:%S'


def value_text(value: Value, tz: tzinfo) -> str:
    """The text of a value of the debug data. A time is in the time zone of the page."""
    return value.astimezone(tz).strftime(TIME_FORMAT) if isinstance(value, datetime) else str(value)


def table_lines(table: Table, tz: tzinfo) -> list[str]:
    """One line for the titles of the columns, then one line for each row. Each column has one width."""
    rows = [table.columns, *(tuple(value_text(value, tz) for value in row) for row in table.rows)]
    widths = [max(map(len, column)) for column in zip_longest(*rows, fillvalue='')]
    return ['  '.join(text.ljust(width) for text, width in zip(row, widths, strict=False)).rstrip() for row in rows]
