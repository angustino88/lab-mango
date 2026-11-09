"""Pluggable attachment scanning.

By default every upload is verified against the SHA-256 computed at upload time (detects truncated / tampered
storage). To plug in a real malware engine, set ``SUPPORT_DESK_ATTACHMENT_SCANNER`` to the dotted path of a callable::

    def scan(attachment: TicketAttachment) -> AttachmentScanStatus: ...

When such a scanner is configured new uploads start as ``pending`` and cannot be downloaded until the
``support_desk.scan_pending_attachments`` task marks them ``clean``.
"""

import hashlib
import logging
from collections.abc import Callable

from django.conf import settings
from django.utils.module_loading import import_string

from core.support_desk.contracts import AttachmentScanStatus
from core.support_desk.models.attachment import TicketAttachment

logger = logging.getLogger(__name__)

Scanner = Callable[[TicketAttachment], AttachmentScanStatus]


def _custom_scanner_path() -> str:
    return getattr(settings, "SUPPORT_DESK_ATTACHMENT_SCANNER", "") or ""


def integrity_scanner(attachment: TicketAttachment) -> AttachmentScanStatus:
    """Default scanner: the stored binary must exist and match the recorded SHA-256."""
    if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        return AttachmentScanStatus.INFECTED
    digest = hashlib.sha256()
    with attachment.file.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if attachment.sha256 and digest.hexdigest() != attachment.sha256:
        return AttachmentScanStatus.INFECTED
    return AttachmentScanStatus.CLEAN


def get_scanner() -> Scanner:
    path = _custom_scanner_path()
    if path:
        return import_string(path)
    return integrity_scanner


def initial_scan_status() -> str:
    """New uploads are quarantined only if an external scanner has to look at them."""
    return AttachmentScanStatus.PENDING.value if _custom_scanner_path() else AttachmentScanStatus.CLEAN.value
