from decimal import Decimal
from types import SimpleNamespace

from core.labs.features.licenses.api.serializers import (
    LicenseAgreementSerializer,
    LicenseSerializer,
    LicenseStatusRecordSerializer,
)
from core.labs.features.licenses.api.views import LicenseListAPIView
from core.labs.models import LicenseStatus


def test_license_serializer_groups_acquisition_price_as_nullable_money_object():
    license_obj = SimpleNamespace(
        acquisition_price=Decimal("249.50"),
        acquisition_currency="USD",
    )

    assert LicenseSerializer().get_acquisition_price(license_obj) == {
        "amount": "249.50",
        "currency": "USD",
    }
    assert LicenseSerializer().get_acquisition_price(
        SimpleNamespace(acquisition_price=None, acquisition_currency=None)
    ) is None


def test_license_serializer_no_sibling_fields_and_standard_timestamps():
    fields = LicenseSerializer.Meta.fields
    # Verify no legacy sibling relation fields
    for field in ("product_name", "vendor_name", "type_name", "category_name", "restriction_name"):
        assert field not in fields

    # Verify standard timestamp fields and status
    assert "created_at" in fields
    assert "updated_at" in fields
    assert "created" not in fields
    assert "modified" not in fields
    assert "deleted_at" not in fields
    assert "current_status" not in fields
    assert "status" in fields
    assert "acquisition_price" in fields
    assert "acquisition" not in fields


def test_license_serializer_status_formats_as_choice_reference():
    serializer = LicenseSerializer()
    obj = SimpleNamespace(current_status=LicenseStatus.AVAILABLE)
    ref = serializer.get_status(obj)
    assert ref == {"value": "available", "label": "Available"}


def test_license_agreement_serializer_structures_price_and_created_at():
    fields = LicenseAgreementSerializer.Meta.fields
    assert "price" in fields
    assert "created_at" in fields
    assert "created" not in fields

    agreement = SimpleNamespace(price=Decimal("150.00"), currency="EUR")
    assert LicenseAgreementSerializer().get_price(agreement) == {
        "amount": "150.00",
        "currency": "EUR",
    }


def test_license_status_record_serializer_formats_status_and_created_at():
    fields = LicenseStatusRecordSerializer.Meta.fields
    assert "created_at" in fields
    assert "created" not in fields

    record = SimpleNamespace(status=LicenseStatus.ASSIGNED)
    assert LicenseStatusRecordSerializer().get_status(record) == {
        "value": "assigned",
        "label": "Assigned",
    }


def test_license_list_applies_declared_search_filter():
    from unittest.mock import patch

    request = type("Request", (), {})()
    view = LicenseListAPIView()
    filters = {"search": "office"}
    with patch.object(view, "validate_query", return_value=(filters, None)), patch(
        "core.labs.features.licenses.api.views.public.list_licenses",
        return_value=object(),
    ) as list_licenses, patch.object(view, "list_response_sync", return_value="response"):
        response = view.handle_get(request)

    assert response == "response"
    list_licenses.assert_called_once_with(search="office")
