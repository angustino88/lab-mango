"""Add document and image formats to installations still on the original default attachment list.

A list an administrator has customised is left untouched. Reversing restores the original list only
where the row still holds exactly the widened default.
"""

from django.db import migrations

ORIGINAL_DEFAULT = [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt", ".log", ".csv", ".json", ".zip", ".xml"]
WIDENED_DEFAULT = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".md",
    ".txt",
    ".log",
    ".csv",
    ".json",
    ".xml",
    ".zip",
]


def _replace(apps, old: list[str], new: list[str]) -> None:
    SupportSettings = apps.get_model("support_desk", "SupportSettings")
    for row in SupportSettings.objects.all():
        if sorted(row.allowed_attachment_extensions or []) == sorted(old):
            row.allowed_attachment_extensions = list(new)
            row.save(update_fields=["allowed_attachment_extensions"])


def widen(apps, schema_editor) -> None:
    _replace(apps, ORIGINAL_DEFAULT, WIDENED_DEFAULT)


def narrow(apps, schema_editor) -> None:
    _replace(apps, WIDENED_DEFAULT, ORIGINAL_DEFAULT)


class Migration(migrations.Migration):
    dependencies = [("support_desk", "0001_initial")]

    operations = [migrations.RunPython(widen, narrow)]
