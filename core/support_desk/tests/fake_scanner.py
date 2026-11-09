"""Test double for ``SUPPORT_DESK_ATTACHMENT_SCANNER``."""

from core.support_desk.contracts import AttachmentScanStatus


def always_clean(attachment):
    return AttachmentScanStatus.CLEAN
