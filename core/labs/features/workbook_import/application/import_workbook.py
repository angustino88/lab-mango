"""Check or apply one data workbook: every sheet in one transaction, all or nothing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from ..contracts import MODE_CREATE, MODES, ImportReport, SheetRows
from ..exceptions import WorkbookImportNotAllowed, WorkbookRejected
from ..queries.sheets import SHEETS
from .context import ImportRun
from .equipment import import_equipment
from .policies import can_import_workbook
from .references import import_references
from .spaces import import_spaces


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

    Race guard: every write goes through the owning feature's command (row locks and the active-SKU,
    slot and placement constraints); the single transaction makes a concurrent duplicate fail the whole
    import instead of half of it.
    """
    if not can_import_workbook(actor):
        raise WorkbookImportNotAllowed("Only Labs administrators can import workbooks.")
    if command.mode not in MODES:
        raise ValueError(f"Unknown import mode {command.mode!r}.")
    report = ImportReport(dry_run=command.dry_run, template_version=command.template_version, mode=command.mode)
    run = ImportRun(actor=actor, report=report, file_digest=command.file_digest, mode=command.mode)
    try:
        with transaction.atomic():
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
