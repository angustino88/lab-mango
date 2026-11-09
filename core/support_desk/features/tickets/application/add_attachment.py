"""Add attachment to support ticket command use case."""

import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    AttachmentCountLimitExceededError,
    AttachmentSizeLimitExceededError,
    AttachmentTypeNotAllowedError,
    PermissionDeniedError,
)
from core.support_desk.features.tickets.application.attachment_scanner import initial_scan_status
from core.support_desk.features.tickets.application.policies import is_support_agent
from core.support_desk.features.tickets.application.shared import get_ticket_for_actor
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.settings import SupportSettings


@dataclass(frozen=True, slots=True)
class AddAttachmentInput:
    ticket_key: str
    filename: str
    content_type: str
    size: int
    content: bytes | None = None
    file: Any = None
    comment_id: int | None = None
    is_restricted: bool = False


def _validate_real_bytes(content_bytes: bytes, filename: str) -> None:
    """Inspect leading bytes to detect executable binaries or mismatches with allowed file extensions."""
    if not content_bytes:
        return
    # Reject Windows executable and Unix ELF binaries
    if content_bytes.startswith(b"MZ") or content_bytes.startswith(b"\x7fELF"):
        raise AttachmentTypeNotAllowedError("Executable binaries are not permitted as attachments.")

    ext = os.path.splitext(filename)[1].lower()
    if ext == ".png" and not content_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AttachmentTypeNotAllowedError("File content does not match PNG format.")
    if ext in (".jpg", ".jpeg") and not content_bytes.startswith(b"\xff\xd8\xff"):
        raise AttachmentTypeNotAllowedError("File content does not match JPEG format.")
    if ext == ".gif" and not (content_bytes.startswith(b"GIF87a") or content_bytes.startswith(b"GIF89a")):
        raise AttachmentTypeNotAllowedError("File content does not match GIF format.")
    if ext == ".pdf" and not content_bytes.startswith(b"%PDF-"):
        raise AttachmentTypeNotAllowedError("File content does not match PDF format.")


def add_attachment(command: AddAttachmentInput, *, actor: Any) -> TicketAttachment:
    """Validate, store, and record a file attachment on a ticket."""
    ticket = get_ticket_for_actor(command.ticket_key, actor)

    if command.is_restricted and not is_support_agent(actor):
        raise PermissionDeniedError("Only support agents and administrators can mark attachments as restricted.")

    settings = SupportSettings.get_solo()

    # Size limit
    if command.size > settings.max_attachment_size_bytes:
        raise AttachmentSizeLimitExceededError(
            f"File size exceeds limit of {settings.max_attachment_size_bytes // (1024 * 1024)} MB."
        )

    # Allowed extensions
    ext = os.path.splitext(command.filename)[1].lower()
    allowed_exts = [e.lower() for e in settings.allowed_attachment_extensions or []]
    if allowed_exts and ext not in allowed_exts:
        raise AttachmentTypeNotAllowedError(f"File extension '{ext}' is not permitted.")

    # Max attachments count
    current_count = TicketAttachment.objects.filter(ticket=ticket, deleted_at__isnull=True).count()
    if current_count >= settings.max_attachments_per_ticket:
        raise AttachmentCountLimitExceededError(
            f"Ticket has reached the limit of {settings.max_attachments_per_ticket} attachments."
        )

    # Calculate SHA256 and prepare file content
    content_bytes = command.content
    if content_bytes is None and command.file is not None:
        if hasattr(command.file, "read"):
            content_bytes = command.file.read()
            if hasattr(command.file, "seek"):
                command.file.seek(0)
        else:
            content_bytes = bytes(command.file)

    if content_bytes is None:
        content_bytes = b""

    # Validate file's real bytes against malicious binaries and declared format
    _validate_real_bytes(content_bytes, command.filename)

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    storage_key = f"{uuid.uuid4().hex}_{command.filename}"

    comment = None
    if command.comment_id:
        comment = TicketComment.objects.filter(pk=command.comment_id, ticket=ticket).first()

    with transaction.atomic():
        attachment = TicketAttachment(
            ticket=ticket,
            comment=comment,
            uploaded_by=actor,
            storage_key=storage_key,
            filename=command.filename,
            content_type=command.content_type,
            size=command.size or len(content_bytes),
            sha256=sha256,
            scan_status=initial_scan_status(),
            is_restricted=command.is_restricted,
        )
        attachment.file.save(storage_key, ContentFile(content_bytes), save=False)
        attachment.save()

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=ticket,
            event_type=ActivityEventType.ATTACHMENT_ADDED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "attachment_id": attachment.pk,
                "filename": attachment.filename,
                "size": attachment.size,
                "is_restricted": attachment.is_restricted,
            },
        )

    return attachment
