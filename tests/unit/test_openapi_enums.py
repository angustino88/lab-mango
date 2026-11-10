"""Regression coverage for the settings-level OpenAPI enum registry."""

from django.conf import settings
from drf_spectacular.plumbing import load_enum_name_overrides

from config.openapi import ENUM_NAME_OVERRIDES


def test_settings_use_the_shared_enum_registry() -> None:
    assert settings.SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"] is ENUM_NAME_OVERRIDES


def test_enum_registry_preserves_existing_names_and_choice_hashes() -> None:
    # These hashes capture the pre-extraction choice values and labels. A broken
    # import path, duplicate choice set, or renamed enum must fail this test.
    assert load_enum_name_overrides() == {
        "082749b0f1f9e6a6": "AuditResultInputEnum",
        "39d29be5c7b9d988": "BookingStatusEnum",
        "b0a8218aeff7f4b7": "ComputingActivityStatusEnum",
        "55b911fb471f796c": "EquipmentStatusEnum",
        "c23a21501f38221e": "LicenseStatusEnum",
        "c6340131decdfe99": "PurchaseStatusEnum",
        "0ca2b20fe2f28609": "ResourceAuditResultEnum",
        "241789807f273812": "ResourceTypeEnum",
        "1f24ce8d87dafc9f": "RoomStatusEnum",
        "36424dd3c434b095": "SourceEnum",
        "39104e86c6dc3857": "StationSlotStatusEnum",
        "1800d01ae51a5646": "SystemStateEnum",
        "604305f882ced4b6": "TicketTypeEnum",
        "70d6cee90699d25a": "UrgencyEnum",
    }


def test_audit_input_preserves_legacy_aliases() -> None:
    assert ENUM_NAME_OVERRIDES["AuditResultInputEnum"] == ["PASS", "FAIL", "NOT_ASSESSED", "OK", "NOK"]
