from unittest.mock import Mock

import pytest
from django.db import models

from core.labs.models import Bench, LabSessionLog, License, MonitoringEvent


def _capture_save_validation(monkeypatch, instance):
    validations = []
    monkeypatch.setattr(
        type(instance),
        "full_clean",
        lambda self, **kwargs: validations.append(kwargs),
    )
    monkeypatch.setattr(models.Model, "save", Mock())

    instance.save()

    assert len(validations) == 1
    return validations[0]


@pytest.mark.parametrize(
    ("instance", "relation"),
    [
        (Bench(sku="BN-01"), "setup_location"),
        (License(sku="LIC-01"), "product"),
        (
            MonitoringEvent(
                agent_id="agent-01",
                event_id="c9a4b022-73a7-4ad9-83ae-f44ca6fd5b91",
                reported_at="2026-10-14T00:00:00Z",
                computer_id=1,
                occurred_at="2026-10-14T00:00:00Z",
                action="heartbeat",
            ),
            "computer",
        ),
        (
            LabSessionLog(
                agent_id="agent-01",
                event_id="83a03fc0-7efa-46b8-bfed-2671420fe073",
                reported_at="2026-10-14T00:00:00Z",
                computing_equipment_id=1,
            ),
            "computing_equipment",
        ),
    ],
)
def test_model_save_validates_once_without_database_preflight_checks(
    monkeypatch, instance, relation
):
    validation = _capture_save_validation(monkeypatch, instance)

    assert relation in validation["exclude"]
    assert set(validation["exclude"]) == {
        field.name for field in instance._meta.concrete_fields if field.is_relation
    }
    assert validation["validate_unique"] is False
    assert validation["validate_constraints"] is False


def test_license_has_active_sku_uniqueness_constraint():
    constraints = [
        constraint
        for constraint in License._meta.constraints
        if isinstance(constraint, models.UniqueConstraint)
        and constraint.fields == ("sku",)
        and constraint.name == "labs_license_active_sku_uniq"
    ]

    assert len(constraints) == 1
    assert constraints[0].condition == models.Q(deleted_at__isnull=True)
