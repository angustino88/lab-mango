"""``create_equipment`` with a starting condition and storage room equals create, then change and place."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from core.labs.features.equipment.application.change_state import ChangeConditionInput, change_condition
from core.labs.features.equipment.application.create_equipment import CreateEquipmentInput, create_equipment
from core.labs.features.equipment.application.place_equipment import PlaceEquipmentInput, place_equipment
from core.labs.features.equipment.exceptions import InvalidEquipmentStatus
from core.labs.models import ComputingProfile, Equipment, EquipmentCategory, EquipmentKind, ResourceDowntime, Room
from core.labs.models.activity.computing_activity import ComputingActivity
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture()
def kind() -> EquipmentKind:
    category = EquipmentCategory.objects.create(name="Display", definition="Displays", monitored=False)
    return EquipmentKind.objects.create(category=category, name="Monitor")


@pytest.fixture()
def room() -> Room:
    return Room.objects.create(sku="STORE-1", name="Store")


def _state(unit: Equipment) -> tuple:
    window = ResourceDowntime.objects.for_resource(unit).get()
    placement = EquipmentAssignment.all_placements.get(equipment=unit)
    return (
        window.condition,
        window.kind,
        window.reason,
        window.notes,
        window.ends_at,
        placement.room_id,
        placement.bench_id,
        placement.station_id,
        placement.unassigned_at,
        ResourceDowntime.objects.condition_of(unit),
    )


def test_starting_state_matches_the_separate_commands(kind, room):
    fields = (("kind", kind), ("name", "Monitor"))
    combined = create_equipment(
        CreateEquipmentInput(
            fields=(*fields, ("sku", "MON-A")),
            condition="out_of_service",
            condition_reason="Imported.",
            room_id=room.pk,
        ),
        actor=None,
    )
    separate = create_equipment(CreateEquipmentInput(fields=(*fields, ("sku", "MON-B"))), actor=None)
    change_condition(
        ChangeConditionInput(equipment_id=separate.pk, condition="out_of_service", reason="Imported."), actor=None
    )
    place_equipment(PlaceEquipmentInput(equipment_id=separate.pk, room_id=room.pk), actor=None)

    assert _state(combined) == _state(separate)
    assert _state(combined)[0] == "out_of_service"
    assert _state(combined)[5] == room.pk


def test_operational_or_no_condition_opens_no_window(kind):
    for sku, condition in (("MON-C", "operational"), ("MON-D", None)):
        unit = create_equipment(
            CreateEquipmentInput(fields=(("kind", kind), ("sku", sku), ("name", "Monitor")), condition=condition),
            actor=None,
        )
        assert not ResourceDowntime.objects.for_resource(unit).exists()


def test_an_invalid_condition_creates_nothing(kind):
    with pytest.raises(ValidationError) as error:
        create_equipment(
            CreateEquipmentInput(fields=(("kind", kind), ("sku", "MON-E"), ("name", "Monitor")), condition="melted"),
            actor=None,
        )

    assert error.value.message_dict == {"condition": ["Select a valid condition."]}
    assert not Equipment.objects.filter(sku="MON-E").exists()


def test_a_planned_unit_cannot_start_with_a_condition(kind):
    with pytest.raises(InvalidEquipmentStatus):
        create_equipment(
            CreateEquipmentInput(
                fields=(("kind", kind), ("sku", "MON-F"), ("name", "Monitor"), ("lifecycle_state", "planned")),
                condition="in_maintenance",
            ),
            actor=None,
        )

    assert not Equipment.objects.filter(sku="MON-F").exists()


def test_an_unknown_room_creates_nothing(kind, room):
    with pytest.raises(ValidationError) as error:
        create_equipment(
            CreateEquipmentInput(
                fields=(("kind", kind), ("sku", "MON-G"), ("name", "Monitor")), room_id=room.pk + 1000
            ),
            actor=None,
        )

    assert error.value.message_dict == {"room_id": ["Select a valid room."]}
    assert not Equipment.objects.filter(sku="MON-G").exists()


def test_a_monitored_unit_gets_its_profile_file_and_activity_in_one_insert_each(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    category = EquipmentCategory.objects.create(name="Computing", definition="Computers", monitored=True)
    kind = EquipmentKind.objects.create(category=category, name="Desktop")

    unit = create_equipment(
        CreateEquipmentInput(
            fields=(("kind", kind), ("sku", "PC-A"), ("name", "Desktop"), ("computing", {"hostname": "pc-a.lab"}))
        ),
        actor=None,
    )

    profile = ComputingProfile.objects.get(equipment=unit)
    assert profile.hostname == "pc-a.lab"
    name = profile.rdp_file.name
    assert name is not None and name.startswith("rdp_file/PC-A")
    assert profile.rdp_file.storage.exists(name)
    assert ComputingActivity.objects.filter(computing=unit, status="offline", offline_at__isnull=False).exists()
