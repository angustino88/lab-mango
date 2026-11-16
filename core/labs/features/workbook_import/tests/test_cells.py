"""Cell parsing and the formula guard of the spreadsheet writer."""

from datetime import date
from decimal import Decimal

import pytest

from core.infrastructure.spreadsheets import safe_cell_value
from core.labs.features.workbook_import.application.cells import CellError, parse
from core.labs.features.workbook_import.queries.sheets import BOOL, CHOICE, DATE, DECIMAL, INT, TEXT, UTILITIES, Column


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        (TEXT, 12345.0, "12345"),
        (TEXT, "  HC-C-005QJ ", "HC-C-005QJ"),
        (INT, 3.0, 3),
        (INT, "4", 4),
        (DECIMAL, "96,49", Decimal("96.49")),
        (BOOL, "yes", True),
        (BOOL, "No", False),
        (DATE, "2026-Q2", date(2026, 4, 1)),
        (DATE, "2026-10-29", date(2026, 10, 29)),
        (UTILITIES, "230V, ethernet=2, gas=N2", {"230V": True, "ethernet": 2, "gas": "N2"}),
        (TEXT, None, None),
        (TEXT, "   ", None),
    ],
)
def test_parse(kind, value, expected):
    assert parse(value, Column("x", "X", kind)) == expected


def test_choice_accepts_labels_case_and_separators():
    column = Column("condition", "Condition", CHOICE, choice_list="condition")
    assert parse("In-Maintenance", column) == "in_maintenance"
    with pytest.raises(CellError, match="Pick one of"):
        parse("Broken", column)


@pytest.mark.parametrize(("kind", "value"), [(INT, 2.5), (INT, "two"), (DATE, "29/10/2026"), (BOOL, "maybe")])
def test_parse_rejects(kind, value):
    with pytest.raises(CellError):
        parse(value, Column("x", "X", kind))


def test_text_longer_than_the_field_is_rejected():
    with pytest.raises(CellError, match="at most 3"):
        parse("abcd", Column("x", "X", TEXT, max_length=3))


@pytest.mark.parametrize("value", ["=HYPERLINK(1)", "+1", "-1", "@SUM(A1)"])
def test_written_text_never_becomes_a_formula(value):
    assert safe_cell_value(value) == "'" + value
