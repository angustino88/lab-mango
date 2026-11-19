"""HTTP contract of /api/labs/equipment/{id}/hardware-ids."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from core.labs.features.equipment.public import match_hardware_ids
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Equipment, EquipmentCategory, EquipmentKind
from core.labs.models.resource.equipment.hardware_id import EquipmentHardwareId
from tests.factories import create_computing_equipment

ROOT = "/api/labs/equipment/"
User = get_user_model()
CANCASE_PNP = r"USB\VID_1248&PID_1073\007113-585343"
PORT_PNP = r"USB\VID_046D&PID_C52B\5&2A3C0F1&0&2"


@pytest.fixture
def units(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    pc_kind = EquipmentKind.objects.create(category=category, name="HW PC")
    tools = EquipmentCategory.objects.create(name="HW tools", definition="Tools")
    tool_kind = EquipmentKind.objects.create(category=tools, name="CAN interface")
    return {
        "pc": create_computing_equipment(sku="HW-PC-1", name="Bench PC", kind=pc_kind),
        "other_pc": create_computing_equipment(sku="HW-PC-2", name="Other PC", kind=pc_kind),
        "cancase": Equipment.objects.create(sku="HW-CAN-1", name="CANcase 3", kind=tool_kind),
        "other": Equipment.objects.create(sku="HW-CAN-2", name="CANcase 7", kind=tool_kind),
    }


@pytest.fixture
def client(db):
    result = APIClient()
    result.force_authenticate(grant_labs_role(User.objects.create_user(username="hw-coord"), "coord"))
    return result


def url(unit):
    return f"{ROOT}{unit.pk}/hardware-ids"


@pytest.mark.django_db
def test_register_list_and_delete_a_pnp_id(client, units):
    created = client.post(
        url(units["cancase"]), {"kind": "pnp_id", "value": " usb/vid_1248&pid_1073/007113-585343 "}, format="json"
    )
    assert created.status_code == 201, created.data
    body = created.data["data"]
    assert body["value"] == CANCASE_PNP and body["kind"]["value"] == "pnp_id"
    assert body["computing"] is None and body["is_port_bound"] is False

    again = client.post(url(units["cancase"]), {"kind": "pnp_id", "value": CANCASE_PNP}, format="json")
    assert again.status_code == 201 and again.data["data"]["id"] == body["id"]  # idempotent

    listed = client.get(url(units["cancase"])).data["data"]["items"]
    assert [item["id"] for item in listed] == [body["id"]]

    assert client.delete(f"{url(units['cancase'])}/{body['id']}").status_code == 204
    assert client.delete(f"{url(units['cancase'])}/{body['id']}").status_code == 404


@pytest.mark.django_db
def test_an_id_belongs_to_one_unit(client, units):
    assert (
        client.post(url(units["cancase"]), {"kind": "pnp_id", "value": CANCASE_PNP}, format="json").status_code == 201
    )
    taken = client.post(url(units["other"]), {"kind": "pnp_id", "value": CANCASE_PNP.lower()}, format="json")
    assert taken.status_code == 409


@pytest.mark.django_db
def test_port_bound_id_needs_a_computer_and_is_scoped_to_it(client, units):
    missing = client.post(url(units["cancase"]), {"kind": "pnp_id", "value": PORT_PNP}, format="json")
    assert missing.status_code == 422
    scoped = client.post(
        url(units["cancase"]), {"kind": "pnp_id", "value": PORT_PNP, "computing_id": units["pc"].pk}, format="json"
    )
    assert scoped.status_code == 201, scoped.data
    assert scoped.data["data"]["computing"]["id"] == units["pc"].pk and scoped.data["data"]["is_port_bound"]
    # The same port ID on another computer is another device.
    other = client.post(
        url(units["other"]), {"kind": "pnp_id", "value": PORT_PNP, "computing_id": units["other_pc"].pk}, format="json"
    )
    assert other.status_code == 201
    not_computing = client.post(
        url(units["other"]), {"kind": "pnp_id", "value": PORT_PNP, "computing_id": units["cancase"].pk}, format="json"
    )
    assert not_computing.status_code == 422


@pytest.mark.django_db
def test_database_refuses_an_unscoped_port_bound_id(units):
    with pytest.raises(IntegrityError), transaction.atomic():
        EquipmentHardwareId.objects.create(equipment=units["cancase"], kind="pnp_id", value=PORT_PNP)


@pytest.mark.django_db
def test_vector_device_name_and_bad_values(client, units):
    ok = client.post(url(units["cancase"]), {"kind": "vector_device", "value": "007113-585343"}, format="json")
    assert ok.status_code == 201
    assert (
        client.post(url(units["cancase"]), {"kind": "pnp_id", "value": "not a pnp id"}, format="json").status_code
        == 422
    )
    assert client.post(url(units["cancase"]), {"kind": "serial", "value": "x"}, format="json").status_code == 422


@pytest.mark.django_db
def test_matching_by_registered_ids(client, units):
    client.post(url(units["cancase"]), {"kind": "pnp_id", "value": CANCASE_PNP}, format="json")
    client.post(
        url(units["cancase"]), {"kind": "pnp_id", "value": PORT_PNP, "computing_id": units["pc"].pk}, format="json"
    )
    client.post(url(units["other"]), {"kind": "vector_device", "value": "007113-585343"}, format="json")
    known = ((("pnp_id", CANCASE_PNP),), "USB")
    port = ((("pnp_id", PORT_PNP),), "USB")
    both = ((("pnp_id", CANCASE_PNP), ("vector_device", "007113-585343")), "USB")
    unknown = ((("pnp_id", r"USB\VID_0000&PID_0000\X"),), "USB")

    on_pc = match_hardware_ids(computing_id=units["pc"].pk, evidence=[known, port, both, unknown])
    assert on_pc[known].equipment_id == units["cancase"].pk and on_pc[known].status == "matched"
    assert on_pc[port].equipment_id == units["cancase"].pk
    assert on_pc[both].status == "ambiguous"
    assert on_pc[unknown].status == "unmatched"
    elsewhere = match_hardware_ids(computing_id=units["other_pc"].pk, evidence=[port])
    assert elsewhere[port].status == "unmatched"  # port-bound IDs only count on their computer
