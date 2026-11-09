import pytest
from django.core.exceptions import ValidationError

from core.labs.features.equipment.application.create_equipment import (
    CreateEquipmentInput,
    create_equipment,
)
from core.labs.features.equipment.application.delete_equipment import (
    DeleteEquipmentInput,
    delete_equipment,
)
from core.labs.features.equipment.application.update_equipment import (
    UpdateEquipmentInput,
    update_equipment,
)
from core.labs.models import Equipment
from core.labs.models.resource.base.resource import Department, ResourceGroup


def test_many_to_many_fields_are_extracted_before_model_construction():
    from core.labs.features.equipment.application.update_equipment import _pop_many_to_many
    from core.labs.models.resource.equipment.display import DisplayEquipment

    values = {"interfaces": [1, 2], "size": 1}

    result = _pop_many_to_many(DisplayEquipment, values)

    assert result == {"interfaces": [1, 2]}
    assert values == {"size": 1}


@pytest.mark.django_db
def test_create_equipment_rejects_invalid_model_data(equipment):
    with pytest.raises(ValidationError):
        create_equipment(
            CreateEquipmentInput(
                fields=(("kind", equipment.kind), ("sku", "EQ-01"), ("name", "Duplicate")),
            ),
            actor=None,
            model=Equipment,
        )


@pytest.mark.django_db
def test_create_equipment_resolves_group_and_infers_its_department(equipment):
    department = Department.objects.create(name="Equipment Department")
    group = ResourceGroup.objects.create(name="Equipment Group", department=department)

    created = create_equipment(
        CreateEquipmentInput(
            fields=(("kind", equipment.kind), ("sku", "EQ-GROUP-01"), ("name", "Grouped"), ("group", group.pk)),
        ),
        actor=None,
        model=Equipment,
    )

    assert created.group_id == group.pk
    assert created.department_id == department.pk


@pytest.mark.django_db
def test_create_equipment_rejects_inactive_or_cross_department_group(equipment):
    department = Department.objects.create(name="Equipment Department")
    other_department = Department.objects.create(name="Other Equipment Department")
    group = ResourceGroup.objects.create(name="Inactive Group", department=department, active=False)
    with pytest.raises(ValidationError, match="active"):
        create_equipment(
            CreateEquipmentInput(
                fields=(("kind", equipment.kind), ("sku", "EQ-GROUP-INACTIVE"), ("group", group.pk)),
            ),
            actor=None,
        )

    active_group = ResourceGroup.objects.create(name="Active Group", department=department)
    with pytest.raises(ValidationError, match="different department"):
        create_equipment(
            CreateEquipmentInput(
                fields=(
                    ("kind", equipment.kind),
                    ("sku", "EQ-GROUP-MISMATCH"),
                    ("department", other_department),
                    ("group", active_group.pk),
                ),
            ),
            actor=None,
        )


@pytest.mark.django_db
def test_update_and_delete_equipment_use_application_commands(equipment):
    from core.labs.models.resource.equipment.computing import ComputingEquipment

    comp = ComputingEquipment.objects.create(sku="COMP-WRITE-01", kind=equipment.kind, name="Base Name")
    updated = update_equipment(
        UpdateEquipmentInput(
            equipment_id=comp.pk,
            model=ComputingEquipment,
            fields=(("name", "Updated asset"),),
        ),
        actor=None,
    )
    assert updated.name == "Updated asset"

    delete_equipment(
        DeleteEquipmentInput(equipment_id=comp.pk, model=ComputingEquipment),
        actor=None,
    )
    assert ComputingEquipment.objects.filter(pk=comp.pk, deleted_at__isnull=True).count() == 0
