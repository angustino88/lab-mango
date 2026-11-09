from typing import cast

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection

from core.labs.features.equipment.defaults import REFERENCE_LISTS
from core.labs.models.resource.equipment.reference_data import EquipmentCategory
from core.reference_data.declarations import ReferenceList, ReferenceMode
from core.reference_data.provisioning import provision_reference_lists
from core.reference_data.registry import get_registered_reference_lists


@pytest.mark.django_db
def test_equipment_categories_are_recreated_without_overwriting_existing_rows():
    provision_reference_lists(REFERENCE_LISTS, using="default")
    category = cast(EquipmentCategory, EquipmentCategory.objects.get(name="Computing"))
    category.definition = "User-edited definition"
    category.save()

    with connection.cursor() as cursor:
        cursor.execute(
            f'DELETE FROM "{EquipmentCategory._meta.db_table}" WHERE "name" = %s',
            ["Debugging"],
        )

    provision_reference_lists(REFERENCE_LISTS, using="default")

    category.refresh_from_db()
    restored = cast(EquipmentCategory, EquipmentCategory.objects.get(name="Debugging"))
    assert category.definition == "User-edited definition"
    assert restored.name == "Debugging"


@pytest.mark.django_db
def test_ensure_present_category_cannot_be_deleted_through_model_or_queryset():
    provision_reference_lists(REFERENCE_LISTS, using="default")
    category = cast(EquipmentCategory, EquipmentCategory.objects.get(name="Computing"))

    with pytest.raises(ValidationError, match="cannot be deleted"):
        category.delete()

    with pytest.raises(ValidationError, match="cannot be deleted"):
        category.hard_delete()

    with pytest.raises(ValidationError, match="cannot be deleted"):
        EquipmentCategory.objects.filter(name="Computing").delete()

    with pytest.raises(ValidationError, match="cannot be deleted"):
        EquipmentCategory._base_manager.filter(name="Computing").delete()

    with pytest.raises(ValidationError, match="cannot be deleted"):
        EquipmentCategory.objects.filter(name="Computing").hard_delete()


@pytest.mark.django_db
def test_cascade_delete_cannot_remove_protected_reference_category():
    provision_reference_lists(REFERENCE_LISTS, using="default")

    with pytest.raises(ValidationError, match="cannot be deleted"):
        EquipmentCategory.objects.all().delete()


@pytest.mark.django_db
def test_seed_once_list_is_not_repaired_after_its_first_successful_run():
    reference_list = ReferenceList(
        key="tests.equipment.category-seed-once",
        model=EquipmentCategory,
        identity="name",
        mode=ReferenceMode.SEED_ONCE,
        rows=({"name": "Seed Once", "definition": "Initial row."},),
    )

    provision_reference_lists((reference_list,), using="default")
    assert EquipmentCategory.objects.filter(name="Seed Once").exists()

    with connection.cursor() as cursor:
        cursor.execute(
            f'DELETE FROM "{EquipmentCategory._meta.db_table}" WHERE "name" = %s',
            ["Seed Once"],
        )

    provision_reference_lists((reference_list,), using="default")

    assert not EquipmentCategory.objects.filter(name="Seed Once").exists()


@pytest.mark.django_db
def test_provision_reference_data_command_runs_registered_declarations():
    call_command("provision_reference_data", database="default")

    assert EquipmentCategory.objects.filter(name="Computing").exists()


def test_registered_reference_list_keys_are_unique():
    registered = get_registered_reference_lists()
    keys = [reference_list.key for reference_list in registered]

    assert len(keys) == len(set(keys))
