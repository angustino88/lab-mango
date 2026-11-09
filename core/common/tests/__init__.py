"""
Tests for excel, rdp_file, and upload_local_service utilities.
"""
import io
from unittest.mock import MagicMock, patch

from django.http import HttpResponse

from core.infrastructure.exports.excel import export_excel_file, return_data_row
from core.infrastructure.remote_access.rdp_file import create_rdp_file

# ---------------------------------------------------------------------------
# return_data_row
# ---------------------------------------------------------------------------

class TestReturnDataRow:
    def test_plain_field(self):
        data = {"sku": "ABC-001", "name": "Test"}
        assert return_data_row(data, ["sku"]) == ["ABC-001"]

    def test_nested_field(self):
        data = {"computer": {"sku": "COMP-001"}}
        assert return_data_row(data, ["computer__sku"]) == ["COMP-001"]

    def test_deeply_nested_field_missing(self):
        data = {"computer": None}
        result = return_data_row(data, ["computer__sku"])
        assert result == [None]

    def test_created_field_formatted(self):
        data = {"created": "2026-04-16T10:30:00"}
        result = return_data_row(data, ["created"])
        assert result == ["2026-04-16 10:30:00"]

    def test_created_field_none(self):
        data = {"created": None}
        result = return_data_row(data, ["created"])
        assert result == [""]

    def test_missing_field_returns_none(self):
        data = {"sku": "X"}
        result = return_data_row(data, ["nonexistent"])
        assert result == [None]

    def test_multiple_fields(self):
        data = {"sku": "A", "name": "B"}
        result = return_data_row(data, ["sku", "name"])
        assert result == ["A", "B"]


# ---------------------------------------------------------------------------
# export_excel_file
# ---------------------------------------------------------------------------

class TestExportExcelFile:
    def _make_sheets_and_data(self):
        sheets = {
            "computer": {
                "sheet": "Computer",
                "cols": [
                    {"title": "SKU", "field": "sku"},
                    {"title": "Name", "field": "name"},
                ],
            }
        }
        data = {
            "computer": {
                "data": [
                    {"sku": "C001", "name": "Lab PC 1"},
                    {"sku": "C002", "name": "Lab PC 2"},
                ]
            }
        }
        return sheets, data

    def test_returns_http_response(self):
        sheets, data = self._make_sheets_and_data()
        response = export_excel_file(sheets, data)
        assert isinstance(response, HttpResponse)

    def test_content_type_is_xlsx(self):
        sheets, data = self._make_sheets_and_data()
        response = export_excel_file(sheets, data)
        assert "spreadsheetml" in response["Content-Type"]

    def test_file_is_non_empty(self):
        sheets, data = self._make_sheets_and_data()
        response = export_excel_file(sheets, data)
        content = b"".join(response.streaming_content) if hasattr(response, 'streaming_content') else response.content
        assert len(content) > 0

    def test_empty_data_does_not_raise(self):
        sheets = {
            "computer": {
                "sheet": "Computer",
                "cols": [{"title": "SKU", "field": "sku"}],
            }
        }
        data: dict[str, dict] = {"computer": {"data": []}}
        response = export_excel_file(sheets, data)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# create_rdp_file
# ---------------------------------------------------------------------------

class TestCreateRdpFile:
    def test_returns_bytes_io(self):
        result = create_rdp_file("PC-001", None)
        assert isinstance(result, io.BytesIO)

    def test_content_contains_full_address(self):
        buf = create_rdp_file("MY-COMPUTER", None)
        content = buf.read()
        assert b"full address:s:MY-COMPUTER" in content

    def test_content_contains_username(self):
        user = MagicMock()
        user.username = "techuser"
        buf = create_rdp_file("PC-001", user)
        content = buf.read()
        assert b"username:s:techuser" in content

    def test_none_computer_name_uses_empty_string(self):
        buf = create_rdp_file(None, None)
        content = buf.read()
        assert b"full address:s:" in content

    def test_none_technical_user_uses_empty_username(self):
        buf = create_rdp_file("PC-001", None)
        content = buf.read()
        assert b"username:s:" in content

    def test_buffer_seeked_to_zero(self):
        buf = create_rdp_file("PC-001", None)
        assert buf.tell() == 0

    def test_newline_injection_in_computer_name_is_stripped(self):
        """Newlines in computer_name must not inject extra RDP directives (OWASP A03)."""
        buf = create_rdp_file("evil\nscreen mode id:i:99", None)
        content = buf.read().decode("utf-8")
        # Newline stripped so the address value has no line break:
        lines = content.splitlines()
        address_lines = [line for line in lines if line.startswith("full address:s:")]
        assert len(address_lines) == 1           # exactly one address directive
        assert "\n" not in address_lines[0]      # no embedded newline

    def test_newline_injection_in_username_is_stripped(self):
        user = MagicMock()
        user.username = "techuser\nmalicious:directive"
        buf = create_rdp_file("PC-001", user)
        content = buf.read().decode("utf-8")
        # After newline stripping, exactly one username line must exist
        lines = content.splitlines()
        username_lines = [line for line in lines if line.startswith("username:s:")]
        assert len(username_lines) == 1
        assert "\n" not in username_lines[0]


# ---------------------------------------------------------------------------
# UploadLocalService
# ---------------------------------------------------------------------------

from core.infrastructure.storage.upload_service import UploadLocalService  # noqa: E402


class TestUploadLocalService:
    def _make_service(self, file_name: str = "test.jpg") -> UploadLocalService:
        data = MagicMock()
        return UploadLocalService(data=data, file_name=file_name, location="avatars")

    def test_upload_returns_url(self):
        svc = self._make_service()
        with patch.object(svc._fs, "save", return_value="test_abc123.jpg") as mock_save, \
             patch.object(svc._fs, "url", return_value="/media/avatars/test_abc123.jpg"):
            url = svc.upload_local()
        assert url == "/media/avatars/test_abc123.jpg"
        mock_save.assert_called_once()

    def test_delete_uses_saved_name_not_original(self):
        """delete_local() must delete the actual saved name (which may differ from file_name on collision)."""
        svc = self._make_service(file_name="photo.jpg")
        with patch.object(svc._fs, "save", return_value="photo_abc.jpg"), \
             patch.object(svc._fs, "url", return_value="/media/avatars/photo_abc.jpg"):
            svc.upload_local()

        with patch.object(svc._fs, "delete") as mock_delete:
            svc.delete_local()

        mock_delete.assert_called_once_with("photo_abc.jpg")

    def test_delete_returns_false_on_error(self):
        svc = self._make_service()
        with patch.object(svc._fs, "delete", side_effect=OSError("not found")):
            result = svc.delete_local()
        assert result is False

