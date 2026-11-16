"""Stable business errors of the workbook import (no HTTP concepts)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import ImportReport


class WorkbookRejected(Exception):
    """The workbook has errors; nothing was saved. ``report`` lists every problem found."""

    def __init__(self, report: ImportReport) -> None:
        super().__init__(f"The workbook has {report.error_count} error(s); nothing was imported.")
        self.report = report


class WorkbookImportNotAllowed(Exception):
    """Only Labs administrators may import workbooks."""


__all__ = ["WorkbookImportNotAllowed", "WorkbookRejected"]
