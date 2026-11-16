"""Fixtures: a Labs admin client, provisioned categories and an in-memory workbook builder."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from openpyxl import Workbook
from rest_framework.test import APIClient

from tests.factories import UserFactory, grant_labs_role

CHECK_URL = "/api/labs/workbook-imports/actions/check"
APPLY_URL = "/api/labs/workbook-imports/actions/apply"
TEMPLATE_URL = "/api/labs/workbook-imports/template"

Sheets = dict[str, tuple[list[str], list[list[Any]]]]


def build_xlsx(sheets: Sheets) -> bytes:
    """Row 1 title, row 2 headers, row 3 hints, data from row 4: the template layout."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, (headers, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append([name])
        sheet.append(headers)
        sheet.append(["hint"] * len(headers))
        for row in rows:
            sheet.append(row)
    if not workbook.worksheets:
        workbook.create_sheet("Blank")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload(data: bytes, name: str = "data.xlsx") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name, data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@pytest.fixture()
def categories(db):
    call_command("provision_reference_data")


@pytest.fixture()
def admin_user(db):
    user: Any = UserFactory(username="labadmin", first_name="Lab", last_name="Admin")
    return grant_labs_role(user, "admin")


@pytest.fixture()
def admin_client(admin_user, categories) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture()
def post_workbook(admin_client) -> Callable[..., Any]:
    def post(sheets: Sheets, *, apply: bool = False, client: APIClient | None = None):
        return (client or admin_client).post(
            APPLY_URL if apply else CHECK_URL, {"file": upload(build_xlsx(sheets))}, format="multipart"
        )

    return post
