"""Document and image attachments accepted by the default allow-list, with content signature checks."""

import pytest

from core.support_desk.exceptions import AttachmentTypeNotAllowedError
from core.support_desk.features.tickets.application import (
    AddAttachmentInput,
    CreateTicketInput,
    add_attachment,
    create_ticket,
)
from core.support_desk.models.settings import DEFAULT_ALLOWED_EXTENSIONS

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
ZIP = b"PK\x03\x04" + b"\x00" * 16

VALID = {
    "report.docx": ZIP,
    "data.xlsx": ZIP,
    "slides.pptx": ZIP,
    "notes.odt": ZIP,
    "legacy.doc": OLE,
    "legacy.xls": OLE,
    "legacy.ppt": OLE,
    "letter.rtf": b"{\\rtf1\\ansi hello}",
    "photo.webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
    "scan.bmp": b"BM" + b"\x00" * 16,
    "readme.md": b"# Steps to reproduce",
    "logs.zip": ZIP,
}

MISMATCHED = {
    "report.docx": b"%PDF-1.7 not a zip",
    "legacy.doc": ZIP,
    "photo.webp": b"RIFF\x24\x00\x00\x00AVI LIST",
    "letter.rtf": b"plain text",
}


@pytest.fixture
def ticket(support_setup, requester_user):
    settings = support_setup["settings"]
    settings.allowed_attachment_extensions = DEFAULT_ALLOWED_EXTENSIONS
    settings.max_attachments_per_ticket = 50
    settings.save()
    return create_ticket(
        CreateTicketInput(
            subject="Attachment formats",
            description="Desc",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
        ),
        actor=requester_user,
    )


def _attach(ticket, user, filename: str, content: bytes):
    return add_attachment(
        AddAttachmentInput(
            ticket_key=ticket.key,
            filename=filename,
            content_type="application/octet-stream",
            size=len(content),
            content=content,
        ),
        actor=user,
    )


@pytest.mark.parametrize("filename", sorted(VALID))
def test_default_list_accepts_documents_and_images(ticket, requester_user, filename):
    attachment = _attach(ticket, requester_user, filename, VALID[filename])
    assert attachment.filename == filename


@pytest.mark.parametrize("filename", sorted(MISMATCHED))
def test_content_must_match_the_extension(ticket, requester_user, filename):
    with pytest.raises(AttachmentTypeNotAllowedError, match="does not match"):
        _attach(ticket, requester_user, filename, MISMATCHED[filename])


def test_executables_stay_blocked(ticket, requester_user):
    with pytest.raises(AttachmentTypeNotAllowedError):
        _attach(ticket, requester_user, "tool.exe", b"MZ\x90\x00")
