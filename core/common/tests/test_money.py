"""Money on the wire (response standard FMT-2, FMT-7; request standard TYP-3, TYP-4)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.common.api.money import MoneyField
from core.common.domain.money import check_currency


class _Priced(serializers.Serializer):
    price = MoneyField(amount="price", currency="currency", min_value=0)


class _ParentCurrency(serializers.Serializer):
    total = MoneyField(currency="parent.currency")


def test_reads_one_object_named_by_its_role():
    obj = SimpleNamespace(price=Decimal("12.5"), currency="EUR")
    assert _Priced(obj).data == {"price": {"amount": "12.50", "currency": "EUR"}}


def test_currency_can_come_from_a_parent():
    obj = SimpleNamespace(amount=Decimal("3"), parent=SimpleNamespace(currency="USD"))
    assert _ParentCurrency(obj).data == {"total": {"amount": "3.00", "currency": "USD"}}


def test_writes_map_onto_the_stored_amount_and_currency():
    serializer = _Priced(data={"price": {"amount": "12.50", "currency": "EUR"}})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"price": Decimal("12.50"), "currency": "EUR"}


@pytest.mark.parametrize(
    "value",
    [
        "12.50",  # not an object
        {"amount": 12.5, "currency": "EUR"},  # TYP-3: a number, not a decimal string
        {"amount": "12.505", "currency": "EUR"},  # too many decimal places
        {"amount": "1e3", "currency": "EUR"},  # exponent
        {"amount": "-1.00", "currency": "EUR"},  # below the minimum
        {"amount": "12.50", "currency": "eur"},  # TYP-11: lowercase is rejected, not corrected
        {"amount": "12.50"},  # currency missing
        {"amount": "12.50", "currency": "EUR", "note": "x"},  # unknown key
    ],
)
def test_invalid_money_is_rejected(value):
    serializer = _Priced(data={"price": value})
    assert not serializer.is_valid()
    assert "price" in serializer.errors


def test_child_money_must_use_the_parent_currency():
    check_currency("EUR", "EUR", field="total")
    check_currency(None, "EUR", field="total")
    with pytest.raises(DjangoValidationError) as error:
        check_currency("USD", "EUR", field="total")
    assert "total" in error.value.message_dict
