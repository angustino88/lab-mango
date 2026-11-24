"""Turn raw cell values into Python values for one declared column. Pure: no database access."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from ..queries.sheets import (
    BOOL,
    CHOICE,
    CHOICE_VALUES,
    DATE,
    DECIMAL,
    INT,
    TEXT,
    URL,
    UTILITIES,
    Column,
)

_TRUE = {"yes", "y", "true", "1", "x", "✓"}
_FALSE = {"no", "n", "false", "0"}
_QUARTER = re.compile(r"^(\d{4})-?Q([1-4])$", re.IGNORECASE)


class CellError(ValueError):
    """The cell value does not fit the column; the message is shown to the user."""


def text(value: Any) -> str:
    """Cell value as trimmed text; whole numbers lose the ``.0`` Excel gives them."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise CellError("Enter a whole number.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise CellError("Enter a whole number.")
    try:
        return int(text(value).replace(" ", ""))
    except ValueError as error:
        raise CellError("Enter a whole number.") from error


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CellError("Enter a number.")
    raw = text(value).replace(" ", "")
    if isinstance(value, str) and raw.count(",") == 1 and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        number = Decimal(str(value) if isinstance(value, (int, float)) else raw)
    except InvalidOperation as error:
        raise CellError("Enter a number.") from error
    if not number.is_finite():
        raise CellError("Enter a number.")
    return number


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = text(value).lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise CellError("Enter Yes or No.")


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    quarter = _QUARTER.match(raw)
    if quarter:
        return date(int(quarter.group(1)), (int(quarter.group(2)) - 1) * 3 + 1, 1)
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as error:
        raise CellError("Enter a date as YYYY-MM-DD.") from error


def _url(value: Any) -> str:
    raw = text(value)
    try:
        URLValidator()(raw)
    except ValidationError as error:
        raise CellError("Enter a full web link (https://...).") from error
    return raw


def _utilities(value: Any) -> dict[str, Any]:
    """``"230V, ethernet=2, gas=N2"`` → ``{"230V": True, "ethernet": 2, "gas": "N2"}``."""
    result: dict[str, Any] = {}
    for part in text(value).split(","):
        item = part.strip()
        if not item:
            continue
        name, _, amount = (piece.strip() for piece in item.partition("="))
        if not name:
            raise CellError("Write utilities as name or name=value, separated by commas.")
        if not amount:
            result[name] = True
            continue
        try:
            result[name] = int(amount)
        except ValueError:
            try:
                result[name] = float(amount)
            except ValueError:
                result[name] = amount
    return result


def _choice(value: Any, column: Column) -> str:
    values = CHOICE_VALUES[column.choice_list or ""]
    raw = " ".join(text(value).lower().replace("_", " ").replace("-", " ").split())
    if raw in values:
        return values[raw]
    labels = ", ".join(label.capitalize() for label in values)
    raise CellError(f"Pick one of: {labels}.")


def parse(value: Any, column: Column) -> Any:
    """Return the parsed value, or ``None`` for an empty cell. Raises ``CellError``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    kind = column.kind
    if kind == TEXT:
        parsed: Any = text(value)
        if column.max_length is not None and len(parsed) > column.max_length:
            raise CellError(f"Use at most {column.max_length} characters.")
        return parsed
    if kind == INT:
        return _integer(value)
    if kind == DECIMAL:
        return _decimal(value)
    if kind == BOOL:
        return _boolean(value)
    if kind == DATE:
        return _date(value)
    if kind == URL:
        return _url(value)
    if kind == UTILITIES:
        return _utilities(value)
    if kind == CHOICE:
        return _choice(value, column)
    raise CellError("Unsupported column type.")


__all__ = ["CellError", "parse", "text"]
