"""Unit tests for Catalog in-memory indexing and concurrency lock in workbook_import."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.labs.features.workbook_import.application.context import ImportRun, Row
from core.labs.features.workbook_import.application.import_workbook import (
    ImportWorkbookInput,
    _acquire_apply_lock,
    import_workbook,
)
from core.labs.features.workbook_import.application.references import Catalog
from core.labs.features.workbook_import.contracts import ImportReport, SheetRows
from core.labs.features.workbook_import.queries.sheets import SHEETS_BY_KEY
from core.labs.models.resource.base.resource import Department, Group


def _make_run(*, dry_run: bool = True) -> ImportRun:
    report = ImportReport(dry_run=dry_run, template_version="2.0")
    return ImportRun(actor=MagicMock(pk=1), report=report, file_digest="digest", dry_run=dry_run)


def test_catalog_loads_table_index_once_and_registers_new_rows_in_memory():
    run = _make_run()
    catalog = Catalog(run)
    row = Row(sheet=SHEETS_BY_KEY["groups"], number=4, values={"department": "Dept A"})

    with patch.object(Department._default_manager, "values") as mock_values:
        mock_values.return_value = [{"pk": 10, "name": "Dept A"}]

        assert catalog.one(row, "department", Department, "name", "dept a") == 10
        assert catalog.one(row, "department", Department, "name", "DEPT A") == 10
        assert catalog.exists(Department, "name", "Dept A") is True
        assert catalog.exists(Department, "name", "Dept B") is False
        # The underlying table was queried only once for all lookups of the same scope.
        assert mock_values.call_count == 1

        # Registering a newly created department updates the in-memory index without another DB query.
        catalog.register(Department, 11, name="Dept B")
        assert catalog.exists(Department, "name", "dept b") is True
        assert catalog.one(row, "department", Department, "name", "DEPT B") == 11
        assert mock_values.call_count == 1


def test_catalog_scoped_lookup_disambiguates_by_parent_and_caches():
    run = _make_run()
    catalog = Catalog(run)
    row = Row(sheet=SHEETS_BY_KEY["groups"], number=4, values={})

    with patch.object(Group._default_manager, "values") as mock_values:
        mock_values.return_value = [
            {"pk": 101, "name": "Core", "department_id": 1},
            {"pk": 102, "name": "Core", "department_id": 2},
        ]

        assert catalog.one(row, "group", Group, "name", "core", department_id=1) == 101
        assert catalog.one(row, "group", Group, "name", "CORE", department_id=2) == 102
        assert mock_values.call_count == 1


def test_apply_acquires_advisory_lock_while_dry_run_check_does_not():
    actor = MagicMock(pk=1)
    sheets = (
        SheetRows(
            name="Departments",
            headers=("Name *", "Description", "Active"),
            rows=((4, ("Dept A", "", "Yes")),),
        ),
    )

    with (
        patch("core.labs.features.workbook_import.application.import_workbook.can_import_workbook", return_value=True),
        patch("core.labs.features.workbook_import.application.import_workbook.transaction.atomic"),
        patch("core.labs.features.workbook_import.application.import_workbook._acquire_apply_lock") as mock_lock,
        patch("core.labs.features.workbook_import.application.import_workbook.import_references"),
        patch("core.labs.features.workbook_import.application.import_workbook.import_spaces"),
        patch("core.labs.features.workbook_import.application.import_workbook.import_equipment"),
    ):
        import_workbook(ImportWorkbookInput(sheets=sheets, file_digest="d1", dry_run=True), actor=actor)
        assert mock_lock.call_count == 0

        import_workbook(ImportWorkbookInput(sheets=sheets, file_digest="d1", dry_run=False), actor=actor)
        assert mock_lock.call_count == 1


def test_acquire_apply_lock_executes_pg_advisory_xact_lock_on_postgresql():
    cursor_cm = MagicMock()
    cursor = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    with patch("core.labs.features.workbook_import.application.import_workbook.connection") as mock_conn:
        mock_conn.vendor = "postgresql"
        mock_conn.cursor.return_value = cursor_cm
        _acquire_apply_lock()
        assert cursor.execute.call_count == 1
        sql, params = cursor.execute.call_args[0]
        assert sql == "SELECT pg_advisory_xact_lock(%s)"
        assert len(params) == 1 and isinstance(params[0], int)
