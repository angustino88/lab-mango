"""Workbook import HTTP mapping: read the upload, call the one command, render the report."""

from __future__ import annotations

import hashlib
from typing import Any

from django.http import HttpResponse
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.types import OpenApiTypes
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from core.infrastructure.spreadsheets import (
    XLSX_CONTENT_TYPE,
    ColumnLayout,
    SheetLayout,
    SpreadsheetUnreadable,
    build_workbook,
    read_workbook,
)
from core.labs.features.base import FeatureAPIView
from core.users.public import IsLabAdminReadWrite

from ..application import ImportWorkbookInput, import_workbook
from ..contracts import ERROR, SheetRows
from ..exceptions import WorkbookImportNotAllowed, WorkbookRejected
from ..queries import readme_rows, template_sheets
from ..queries.sheets import (
    CHOICE_LISTS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    LISTS_SHEET,
    MAX_DATA_ROWS,
    NOT_YET_IMPORTED,
    SHEETS,
    TEMPLATE_VERSION,
)
from .serializers import ImportReportSerializer, WorkbookUploadSerializer

MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
META_SHEET = "_Meta"
_ZIP_MAGIC = b"PK\x03\x04"
_READ_SHEETS = (
    tuple(name for sheet in SHEETS for name in (sheet.name, *sheet.aliases)) + NOT_YET_IMPORTED + (META_SHEET,)
)


def _upload_contract(name: str) -> OperationContract:
    return OperationContract(
        request=WorkbookUploadSerializer,
        success=ResponseContract.success(name, ImportReportSerializer),
        forbidden=ResponseContract.forbidden(),
        payload_too_large=ResponseContract.problem(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE),
        unsupported_media_type=ResponseContract.problem(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
    )


def _field_error(message: str, code: str) -> dict[str, list[ErrorDetail]]:
    return {"file": [ErrorDetail(message, code=code)]}


class WorkbookImportAPIView(FeatureAPIView):
    """Labs administrators only (owner decision 2026-11-16); API keys cannot import."""

    permission_classes: Any = [IsLabAdminReadWrite]
    schema_tags = ("Workbook import",)


class _WorkbookUploadAPIView(WorkbookImportAPIView):
    parser_classes = [MultiPartParser]
    dry_run = True

    def _read_upload(self) -> tuple[ImportWorkbookInput | None, Response | None]:
        if len(self.request.FILES.getlist("file")) > 1:
            return None, self.respond_problem(
                "validation_error",
                code="validation_failed",
                errors=_field_error("Send exactly one file part.", "duplicate_values"),
            )
        serializer, error = self.validate_request(serializer_class=WorkbookUploadSerializer)
        if error is not None:
            return None, error
        assert serializer is not None
        upload = serializer.validated_data["file"]
        if upload.size > MAX_WORKBOOK_BYTES:
            return None, self.respond_problem(
                "payload_too_large",
                code="payload_too_large",
                errors=_field_error("The workbook must not exceed 10 MB.", "max_size"),
            )
        data = upload.read()
        if not data.startswith(_ZIP_MAGIC):
            return None, self.respond_problem(
                "unsupported_media_type",
                code="unsupported_media_type",
                errors=_field_error("Upload an Excel workbook (.xlsx).", "invalid_file"),
            )
        try:
            raw = read_workbook(
                data,
                sheet_names=_READ_SHEETS,
                header_row=HEADER_ROW,
                first_data_row=FIRST_DATA_ROW,
                max_data_rows=MAX_DATA_ROWS,
            )
        except SpreadsheetUnreadable as exc:
            return None, self.respond_problem(
                "validation_error",
                code="validation_failed",
                errors=_field_error(str(exc), "invalid_file"),
            )
        version = None
        sheets: list[SheetRows] = []
        for sheet in raw:
            if sheet.name == META_SHEET:
                # _Meta row 2 is ("template_version", "<version>").
                version = sheet.headers[1] if len(sheet.headers) > 1 else None
                continue
            sheets.append(
                SheetRows(name=sheet.name, headers=sheet.headers, rows=sheet.rows, truncated=sheet.truncated)
            )
        command = ImportWorkbookInput(
            sheets=tuple(sheets),
            file_digest=hashlib.sha256(data).hexdigest(),
            dry_run=self.dry_run,
            template_version=version,
        )
        return command, None

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        command, error = self._read_upload()
        if error is not None:
            return error
        assert command is not None
        try:
            report = import_workbook(command, actor=self.acting_user)
        except WorkbookImportNotAllowed:
            return self.respond_problem("forbidden")
        except WorkbookRejected as rejected:
            errors: dict[str, list[ErrorDetail]] = {}
            for problem in rejected.report.problems:
                if problem.severity != ERROR:
                    continue
                path = problem.sheet if problem.row is None else f"{problem.sheet}[{problem.row}]"
                if problem.column:
                    path = f"{path}.{problem.column}"
                errors.setdefault(path, []).append(ErrorDetail(problem.message, code=problem.code))
            return self.respond_problem("validation_error", code="validation_failed", errors=errors)
        return self.respond(report)


class WorkbookImportCheckAPIView(_WorkbookUploadAPIView):
    """Check a data workbook: run every row and roll back. Always 200 with the full report; saves nothing."""

    post_contract = _upload_contract("WorkbookImportCheck")
    dry_run = True


class WorkbookImportApplyAPIView(_WorkbookUploadAPIView):
    """Import a data workbook: every row is created, or nothing when any row has an error (422 lists them)."""

    post_contract = _upload_contract("WorkbookImportApply")
    dry_run = False


def _template_layouts() -> list[SheetLayout]:
    layouts = [
        SheetLayout(
            name="README",
            title="",
            plain=True,
            columns=(ColumnLayout("", width=22), ColumnLayout("", width=110)),
            rows=tuple(readme_rows()),
        )
    ]
    for sheet, columns, rows in template_sheets():
        layouts.append(
            SheetLayout(
                name=sheet.name,
                title=f"{sheet.name} - {sheet.description}",
                columns=tuple(
                    ColumnLayout(
                        header=column.header,
                        hint=column.hint,
                        required=column.required,
                        width=column.width,
                        choices=column.choices,
                        read_only=sheet.read_only,
                    )
                    for column in columns
                ),
                rows=tuple(rows),
            )
        )
    lists = list(CHOICE_LISTS.values())
    height = max(len(values) for values in lists)
    layouts.append(
        SheetLayout(
            name=LISTS_SHEET,
            title="",
            plain=True,
            hidden=True,
            columns=tuple(ColumnLayout(key) for key in CHOICE_LISTS),
            rows=(
                tuple(CHOICE_LISTS),
                *(tuple(values[i] if i < len(values) else None for values in lists) for i in range(height)),
            ),
        )
    )
    layouts.append(
        SheetLayout(
            name=META_SHEET,
            title="",
            plain=True,
            hidden=True,
            columns=(),
            rows=(("Lab Mango data workbook", ""), ("template_version", TEMPLATE_VERSION)),
        )
    )
    return layouts


class WorkbookImportTemplateAPIView(WorkbookImportAPIView):
    """Download the data workbook template (.xlsx), with the current reference data filled in."""

    get_contract = OperationContract(
        success=ResponseContract.documented(status.HTTP_200_OK, OpenApiTypes.BINARY),
        forbidden=ResponseContract.forbidden(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        content = build_workbook(_template_layouts())
        response = HttpResponse(content, content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="labmango-data-template-v{TEMPLATE_VERSION}.xlsx"'
        return response


__all__ = ["WorkbookImportApplyAPIView", "WorkbookImportCheckAPIView", "WorkbookImportTemplateAPIView"]
