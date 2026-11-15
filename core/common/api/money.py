"""Money on the wire: one ``{amount, currency}`` object, read and written (response standard FMT-2, FMT-7; TYP-4).

Technical helper: works on any object or mapping and imports no business app.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

DECIMAL_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
_DECIMAL = re.compile(DECIMAL_PATTERN)
_CURRENCY = re.compile(CURRENCY_PATTERN)


class MoneySerializer(serializers.Serializer):
    """FMT-2 money: ``amount`` is a decimal string, ``currency`` is ISO 4217 uppercase."""

    amount = serializers.RegexField(DECIMAL_PATTERN, help_text="Decimal string; never a float.")
    currency = serializers.RegexField(CURRENCY_PATTERN, help_text="ISO 4217 code, uppercase.")

    class Meta:
        ref_name = "Money"


def _resolve(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, Mapping) else getattr(obj, part, None)
    return obj


@extend_schema_field(MoneySerializer)
class MoneyField(serializers.Field):
    """One money field named by its role (FMT-7), mapped onto separate stored amount and currency values.

    ``amount`` and ``currency`` are the attribute paths read for the response. ``currency`` may also be a
    callable ``(obj, field) -> str`` for rows whose currency belongs to the document (a report's currency).
    On write the field yields ``{amount_key: Decimal, currency_key: str}`` for the serializer's validated data;
    ``currency_key`` defaults to ``currency`` when that is a plain attribute name, else to ``"currency"``. A
    command whose currency is fixed by a parent (an expense, a purchase) compares the submitted currency with it.
    """

    default_error_messages = {
        "invalid": "Enter money as an object with `amount` (decimal string) and `currency` (ISO 4217).",
        "unknown_field": "Unknown field in a money object: {fields}.",
        "invalid_amount": 'Enter the amount as a decimal string, for example "12.50".',
        "invalid_precision": "Use at most {places} decimal places.",
        "max_digits": "Use at most {digits} digits.",
        "min_value": "Ensure the amount is at least {minimum}.",
        "invalid_currency": 'Enter an ISO 4217 currency code in uppercase, for example "EUR".',
    }

    def __init__(
        self,
        *,
        amount: str = "amount",
        currency: str | Callable[[Any, MoneyField], Any] = "currency",
        amount_key: str | None = None,
        currency_key: str | None = None,
        max_digits: int = 14,
        decimal_places: int = 2,
        min_value: Decimal | int | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("source", "*")
        super().__init__(**kwargs)
        self.amount_path = amount
        self.currency_path = currency
        self.amount_key = amount_key or amount
        self.currency_key = currency_key or (
            currency if isinstance(currency, str) and "." not in currency else "currency"
        )
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self.min_value = None if min_value is None else Decimal(min_value)

    def to_representation(self, obj: Any) -> dict[str, str] | None:
        amount = _resolve(obj, self.amount_path)
        if amount is None:
            return None
        currency = self.currency_path(obj, self) if callable(self.currency_path) else _resolve(obj, self.currency_path)
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        return {"amount": f"{value:.{self.decimal_places}f}", "currency": str(currency)}

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            self.fail("invalid")
        unknown = set(data) - {"amount", "currency"}
        if unknown:
            self.fail("unknown_field", fields=", ".join(sorted(unknown)))
        raw_amount, currency = data.get("amount"), data.get("currency")
        # TYP-3: the amount is a decimal string; numbers are rejected, never coerced.
        if not isinstance(raw_amount, str) or not _DECIMAL.match(raw_amount):
            self.fail("invalid_amount")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            self.fail("invalid_amount")
        exponent = amount.as_tuple().exponent
        places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        if places > self.decimal_places:
            self.fail("invalid_precision", places=self.decimal_places)
        if len(amount.as_tuple().digits) - places > self.max_digits - self.decimal_places:
            self.fail("max_digits", digits=self.max_digits)
        if self.min_value is not None and amount < self.min_value:
            self.fail("min_value", minimum=self.min_value)
        if not isinstance(currency, str) or not _CURRENCY.match(currency):
            self.fail("invalid_currency")
        return {self.amount_key: amount, self.currency_key: currency}


__all__ = ["MoneyField", "MoneySerializer"]
