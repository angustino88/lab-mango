"""Cache-backed live progress tracking for long workbook checks and applies.

Progress lives in Django's default cache (outside PostgreSQL transactions) so polling
requests can observe sheet-by-sheet progress even while ``check`` or ``apply`` executes
inside a single database transaction. Reads are owner-scoped (deny by default).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from ..contracts import (
    PROGRESS_PHASE_COMPLETED,
    PROGRESS_PHASE_FAILED,
    PROGRESS_PHASE_FINALIZING,
    PROGRESS_PHASE_PROCESSING,
    PROGRESS_PHASE_READING,
    PROGRESS_PHASE_WAITING_LOCK,
    PROGRESS_STATUS_COMPLETED,
    PROGRESS_STATUS_FAILED,
    PROGRESS_STATUS_RUNNING,
    ImportProgress,
)

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "labs:workbook_import:progress:"
_CACHE_TTL_SECONDS = 600
_ROW_FLUSH_INTERVAL = 25
_TIME_FLUSH_SECONDS = 0.25


def _cache_key(progress_key: str) -> str:
    return f"{_CACHE_PREFIX}{progress_key}"


def _owner_id(actor: Any) -> int | None:
    pk = getattr(actor, "pk", None)
    return int(pk) if pk is not None else None


def record_progress(
    progress_key: str,
    *,
    actor: Any,
    status: str,
    phase: str,
    percent: int,
    current_sheet: str | None = None,
    processed_rows: int = 0,
    total_rows: int = 0,
    completed_sheets: int = 0,
    total_sheets: int = 0,
    message: str = "",
) -> None:
    """Persist a progress snapshot in cache; never raise if the cache backend fails."""
    owner = _owner_id(actor)
    if owner is None:
        return
    clamped = max(0, min(100, int(percent)))
    payload = {
        "owner_id": owner,
        "progress_key": progress_key,
        "status": status,
        "phase": phase,
        "percent": clamped,
        "current_sheet": current_sheet,
        "processed_rows": max(0, int(processed_rows)),
        "total_rows": max(0, int(total_rows)),
        "completed_sheets": max(0, int(completed_sheets)),
        "total_sheets": max(0, int(total_sheets)),
        "message": message,
        "updated_at": timezone.now().isoformat(),
    }
    try:
        cache.set(_cache_key(progress_key), payload, timeout=_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - progress reporting must never break the import itself.
        logger.warning("Failed to write workbook import progress for %s", progress_key, exc_info=True)


def get_progress(progress_key: str, *, actor: Any) -> ImportProgress | None:
    """Return the progress snapshot if it exists and belongs to ``actor``; otherwise ``None``."""
    owner = _owner_id(actor)
    if owner is None:
        return None
    try:
        raw = cache.get(_cache_key(progress_key))
    except Exception:  # noqa: BLE001 - treat cache read failure as unavailable progress.
        logger.warning("Failed to read workbook import progress for %s", progress_key, exc_info=True)
        return None
    if not isinstance(raw, dict) or raw.get("owner_id") != owner:
        return None
    updated_raw = raw.get("updated_at")
    updated_at = datetime.fromisoformat(updated_raw) if isinstance(updated_raw, str) else timezone.now()
    return ImportProgress(
        progress_key=str(raw["progress_key"]),
        status=str(raw["status"]),
        phase=str(raw["phase"]),
        percent=int(raw["percent"]),
        current_sheet=raw.get("current_sheet"),
        processed_rows=int(raw.get("processed_rows", 0)),
        total_rows=int(raw.get("total_rows", 0)),
        completed_sheets=int(raw.get("completed_sheets", 0)),
        total_sheets=int(raw.get("total_sheets", 0)),
        message=str(raw.get("message", "")),
        updated_at=updated_at,
    )


class ProgressTracker:
    """Throttled progress writer attached to one ``ImportRun``."""

    def __init__(self, progress_key: str, *, actor: Any, dry_run: bool) -> None:
        self.progress_key = progress_key
        self.actor = actor
        self.dry_run = dry_run
        self.total_rows = 0
        self.processed_rows = 0
        self.total_sheets = 0
        self.completed_sheets = 0
        self.current_sheet: str | None = None
        self._since_flush = 0
        self._last_flush = 0.0

    def _write(self, *, status: str, phase: str, percent: int, message: str) -> None:
        self._since_flush = 0
        self._last_flush = time.monotonic()
        record_progress(
            self.progress_key,
            actor=self.actor,
            status=status,
            phase=phase,
            percent=percent,
            current_sheet=self.current_sheet,
            processed_rows=self.processed_rows,
            total_rows=self.total_rows,
            completed_sheets=self.completed_sheets,
            total_sheets=self.total_sheets,
            message=message,
        )

    def _processing_percent(self) -> int:
        if self.total_rows <= 0:
            return 50
        return min(95, 5 + int(90 * self.processed_rows / self.total_rows))

    def reading(self) -> None:
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_READING,
            percent=2,
            message="Reading workbook...",
        )

    def waiting_lock(self) -> None:
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_WAITING_LOCK,
            percent=4,
            message="Waiting for another import to finish...",
        )

    def start(self, *, total_rows: int, total_sheets: int) -> None:
        self.total_rows = max(0, total_rows)
        self.total_sheets = max(0, total_sheets)
        self.processed_rows = 0
        self.completed_sheets = 0
        verb = "Checking" if self.dry_run else "Importing"
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_PROCESSING,
            percent=5,
            message=f"{verb} {self.total_rows:,} rows across {self.total_sheets} sheets...",
        )

    def begin_sheet(self, sheet_name: str, row_count: int) -> None:
        if row_count <= 0:
            return
        self.current_sheet = sheet_name
        verb = "Checking" if self.dry_run else "Importing"
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_PROCESSING,
            percent=self._processing_percent(),
            message=f"{verb} {sheet_name}...",
        )

    def advance_row(self) -> None:
        self.processed_rows += 1
        self._since_flush += 1
        if self._since_flush >= _ROW_FLUSH_INTERVAL or (time.monotonic() - self._last_flush) >= _TIME_FLUSH_SECONDS:
            verb = "Checking" if self.dry_run else "Importing"
            label = self.current_sheet or "workbook"
            self._write(
                status=PROGRESS_STATUS_RUNNING,
                phase=PROGRESS_PHASE_PROCESSING,
                percent=self._processing_percent(),
                message=f"{verb} {label} ({self.processed_rows:,} / {self.total_rows:,} rows)...",
            )

    def finish_sheet(self, row_count: int) -> None:
        if row_count <= 0:
            return
        self.completed_sheets += 1
        verb = "Checking" if self.dry_run else "Importing"
        label = self.current_sheet or "workbook"
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_PROCESSING,
            percent=self._processing_percent(),
            message=f"{verb} {label} ({self.processed_rows:,} / {self.total_rows:,} rows)...",
        )

    def finalizing(self) -> None:
        self.current_sheet = None
        self._write(
            status=PROGRESS_STATUS_RUNNING,
            phase=PROGRESS_PHASE_FINALIZING,
            percent=97,
            message="Finalizing check..." if self.dry_run else "Saving changes...",
        )

    def complete(self) -> None:
        self.current_sheet = None
        self.processed_rows = max(self.processed_rows, self.total_rows)
        self.completed_sheets = max(self.completed_sheets, self.total_sheets)
        self._write(
            status=PROGRESS_STATUS_COMPLETED,
            phase=PROGRESS_PHASE_COMPLETED,
            percent=100,
            message="Check complete." if self.dry_run else "Import complete.",
        )

    def fail(self, message: str | None = None) -> None:
        self.current_sheet = None
        self._write(
            status=PROGRESS_STATUS_FAILED,
            phase=PROGRESS_PHASE_FAILED,
            percent=100,
            message=message or ("Check failed." if self.dry_run else "Import failed."),
        )


__all__ = ["ProgressTracker", "get_progress", "record_progress"]
