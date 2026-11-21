"""Check or apply one data workbook: every sheet in one transaction, all or nothing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.db import connection, transaction

from ..contracts import MODE_CREATE, MODES, ImportReport, SheetRows
from ..exceptions import WorkbookImportNotAllowed, WorkbookRejected
from ..queries.sheets import SHEETS
from .context import ImportRun
from .equipment import import_equipment
from .policies import can_import_workbook
from .references import import_references
from .spaces import import_spaces

_IMPORT_LOCK_KEY = "labs.workbook_import.apply"


def _acquire_apply_lock() -> None:
    """Serialize concurrent multi-sheet workbook applies on one advisory lock to prevent cross-sheet deadlocks."""
    if connection.vendor != "postgresql":
        return
    number = int.from_bytes(hashlib.sha256(_IMPORT_LOCK_KEY.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [number])


@dataclass(frozen=True, slots=True)
class ImportWorkbookInput:
    sheets: tuple[SheetRows, ...]
    # SHA-256 of the uploaded file; makes the reference writes of one file replay-safe.
    file_digest: str
    dry_run: bool = True
    template_version: str | None = None
    # ``create`` (default): every asset tag must be new. ``upsert``: an existing asset tag updates its record.
    mode: str = MODE_CREATE


class _Rollback(Exception):
    pass


def import_workbook(command: ImportWorkbookInput, *, actor: Any) -> ImportReport:
    """Create every row of the workbook in sheet order, or nothing.

    ``dry_run`` runs the same writes and rolls them back, so the check sees exactly what applying would do
    (references created earlier in the file are visible to later sheets). Applying a workbook with any error
    raises ``WorkbookRejected`` with the full report and saves nothing.

    Race guard: a transaction-scoped advisory lock serializes concurrent multi-sheet ``apply`` runs so two
    administrators importing overlapping workbooks never deadlock across sheets, backed by every owning
    feature's row locks and active-SKU, slot and placement constraints.
    """
    if not can_import_workbook(actor):
        raise WorkbookImportNotAllowed("Only Labs administrators can import workbooks.")
    if command.mode not in MODES:
        raise ValueError(f"Unknown import mode {command.mode!r}.")
    report = ImportReport(dry_run=command.dry_run, template_version=command.template_version, mode=command.mode)
    run = ImportRun(
        actor=actor,
        report=report,
        file_digest=command.file_digest,
        mode=command.mode,
        dry_run=command.dry_run,
    )
    try:
        with transaction.atomic():
            if not command.dry_run:
                _acquire_apply_lock()
            run.bind(command.sheets, SHEETS)
            if not run.bound:
                run.problem("Workbook", "No sheet of the data template was found in the file.", code="no_sheets")
            import_references(run)
            import_spaces(run)
            import_equipment(run)
            if command.dry_run or not report.valid:
                raise _Rollback
    except _Rollback:
        run.discard_written_files()
    if not command.dry_run and not report.valid:
        raise WorkbookRejected(report)
    return report


__all__ = ["ImportWorkbookInput", "import_workbook"]
