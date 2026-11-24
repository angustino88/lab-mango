"""``validate_for_write`` raises what ``full_clean`` raises, with fewer queries."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.common.models import validate_for_write
from core.labs.models import ComputingProfile, Equipment, EquipmentCategory, EquipmentKind, ResourceDowntime
from core.labs.models.resource.base.generic_links import resource_content_type
from tests.factories import TechnicalUserFactory, UserFactory

pytestmark = pytest.mark.django_db


def _errors(validate) -> dict[str, list[str]] | None:
    try:
        validate()
    except ValidationError as error:
        return error.message_dict
    return None


def _same_as_full_clean(instance, **options) -> dict[str, list[str]] | None:
    expected = _errors(instance.full_clean)
    actual = _errors(lambda: validate_for_write(instance, **options))
    assert actual == expected
    return actual


@pytest.fixture()
def kind() -> EquipmentKind:
    category = EquipmentCategory.objects.create(name="Computing", definition="Computing equipment")
    return EquipmentKind.objects.create(category=category, name="Computer")


def _unit(kind: EquipmentKind, **values) -> Equipment:
    user: Any = UserFactory()
    return Equipment(kind=kind, creator=user, last_modified_by=user, owner=user, **{"name": "Unit", **values})


def test_a_valid_unit_passes_with_fewer_queries(kind):
    unit = _unit(kind, sku="VAL-1")
    with CaptureQueriesContext(connection) as full:
        unit.full_clean()
    with CaptureQueriesContext(connection) as fast:
        validate_for_write(unit, skip_unique=("uid",))

    # full_clean: one query per loaded foreign key, uid uniqueness, and savepoint-wrapped constraint checks.
    assert len(full) >= 10
    # validate_for_write: only the active-SKU duplicate lookup.
    assert len(fast) == 1


def test_a_duplicate_active_sku_is_refused_with_the_same_message(kind):
    Equipment.objects.create(kind=kind, sku="DUP-1", name="First")

    errors = _same_as_full_clean(_unit(kind, sku="DUP-1"))

    assert errors is not None and list(errors) == ["__all__"]


def test_a_soft_deleted_sku_may_be_reused(kind):
    Equipment.objects.create(kind=kind, sku="DEL-1", name="Gone", deleted_at=timezone.now())

    assert _same_as_full_clean(_unit(kind, sku="DEL-1")) is None


def test_a_deleted_unit_is_outside_the_active_sku_condition(kind):
    Equipment.objects.create(kind=kind, sku="DEL-2", name="Active")

    assert _same_as_full_clean(_unit(kind, sku="DEL-2", deleted_at=timezone.now())) is None


def test_an_existing_unit_does_not_conflict_with_itself(kind):
    unit = Equipment.objects.create(kind=kind, sku="SELF-1", name="Self")

    assert _same_as_full_clean(unit) is None


def test_an_invalid_choice_is_refused_with_the_same_message(kind):
    errors = _same_as_full_clean(_unit(kind, sku="CH-1", lifecycle_state="melted"))

    assert errors is not None and "lifecycle_state" in errors


def test_a_foreign_key_given_by_id_is_still_checked(kind):
    unit = Equipment(kind_id=kind.pk + 1000, sku="FK-1", name="Missing kind")

    errors = _same_as_full_clean(unit)

    assert errors is not None and "kind" in errors


def test_a_foreign_key_id_changed_after_loading_is_still_checked(kind):
    unit = _unit(kind, sku="FK-2")
    unit.kind_id = kind.pk + 1000  # the loaded instance no longer matches the id

    errors = _same_as_full_clean(unit)

    assert errors is not None and "kind" in errors


def test_a_one_to_one_primary_key_can_skip_its_uniqueness_check(kind):
    unit = Equipment.objects.create(kind=kind, sku="PRO-1", name="Profiled")
    technical_user: Any = TechnicalUserFactory()
    profile = ComputingProfile(equipment=unit, technical_user=technical_user)

    with CaptureQueriesContext(connection) as fast:
        validate_for_write(profile, skip_unique=("equipment",))

    assert len(fast) == 0
    assert _errors(profile.full_clean) is None


def _window(unit: Equipment, **values) -> ResourceDowntime:
    return ResourceDowntime(
        resource_content_type=resource_content_type(unit),
        resource_object_id=str(unit.pk),
        **{"condition": "out_of_service", "starts_at": timezone.now(), **values},
    )


def test_a_downtime_window_ending_before_it_starts_is_refused_like_full_clean(kind):
    unit = Equipment.objects.create(kind=kind, sku="DT-1", name="Down")
    now = timezone.now()

    errors = _same_as_full_clean(_window(unit, starts_at=now, ends_at=now - timedelta(hours=1)))

    assert errors == {"ends_at": ["The end must be after the start."]}


def test_downtime_choices_are_refused_like_full_clean(kind):
    unit = Equipment.objects.create(kind=kind, sku="DT-2", name="Down")

    errors = _same_as_full_clean(_window(unit, condition="broken", reason="weather"))

    assert errors is not None and {"condition", "reason"} <= set(errors)


def test_an_overlapping_window_is_refused_unless_the_caller_skips_the_check(kind):
    unit = Equipment.objects.create(kind=kind, sku="DT-3", name="Down")
    _window(unit).save()
    overlapping = _window(unit, starts_at=timezone.now() + timedelta(minutes=1))

    errors = _same_as_full_clean(overlapping)

    assert errors is not None
    assert _errors(lambda: validate_for_write(overlapping, skip_constraints=("downtime_no_overlap",))) is None


def test_a_valid_downtime_window_needs_no_query(kind):
    unit = Equipment.objects.create(kind=kind, sku="DT-4", name="Down")
    window = _window(unit)

    with CaptureQueriesContext(connection) as fast:
        validate_for_write(window, skip_constraints=("downtime_no_overlap",))

    assert len(fast) == 0
    assert _errors(window.full_clean) is None
