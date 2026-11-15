"""The single equipment collection (redesign step 6): one table, one route set, category rules as data."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.application import (
    AssignEquipmentInput,
    HandOverEquipmentInput,
    UpdateEquipmentInput,
    assign_equipment,
    hand_over_equipment,
    update_equipment,
)
from core.labs.features.equipment.exceptions import EquipmentNotAvailable, InvalidEquipmentStatus
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import (
    Bench,
    ComputingActivity,
    ComputingProfile,
    Equipment,
    EquipmentCategory,
    EquipmentKind,
    TechnicalUser,
)
from core.labs.models.resource.equipment import DisplaySize, EquipmentInterface
from core.users.public import effective_labs_roles

ROOT = "/api/labs/equipment"
User = get_user_model()


def _kind(key, **flags):
    category, _ = EquipmentCategory.objects.get_or_create(
        key=key, defaults={"name": key.title(), "definition": key, **flags}
    )
    return EquipmentKind.objects.create(category=category, name=f"{key} kind {EquipmentKind.objects.count()}")


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="collection-coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


@pytest.mark.django_db
def test_display_unit_round_trip_with_typed_fields(client):
    kind = _kind("display")
    size = DisplaySize.objects.create(size='27"')
    hdmi = EquipmentInterface.objects.create(name="HDMI")
    created = client.post(
        ROOT,
        {"kind_id": kind.pk, "sku": "COL-DSP-1", "name": "Monitor", "size_id": size.pk, "interfaces_ids": [hdmi.pk]},
        format="json",
    )
    assert created.status_code == 201, created.data
    body = created.data["data"]
    assert body["size"] == {"id": size.pk, "name": '27"'}
    assert body["interfaces"] == [{"id": hdmi.pk, "name": "HDMI"}]
    assert body["computing"] is None and body["activity"] is None
    assert body["category"]["name"] == "Display"
    by_sku = client.get(f"{ROOT}/sku/COL-DSP-1")
    assert by_sku.status_code == 200 and by_sku.data["data"]["id"] == body["id"]
    listed = client.get(ROOT, {"category": kind.category_id, "size_id": size.pk})
    assert [row["id"] for row in listed.data["data"]] == [body["id"]]


@pytest.mark.django_db
def test_typed_field_the_category_does_not_use_is_refused(client):
    kind = _kind("laboratory")
    size = DisplaySize.objects.create(size='24"')
    response = client.post(
        ROOT, {"kind_id": kind.pk, "sku": "COL-LAB-1", "name": "Scope", "size_id": size.pk}, format="json"
    )
    assert response.status_code == 422, response.data
    assert not Equipment.objects.filter(sku="COL-LAB-1").exists()


@pytest.mark.django_db
def test_moving_to_a_category_that_does_not_use_a_stored_value_is_refused():
    unit = Equipment.objects.create(
        sku="COL-MOVE-1", name="Monitor", kind=_kind("display"), size=DisplaySize.objects.create(size='32"')
    )
    other = _kind("laboratory")
    with pytest.raises(ValidationError) as error:
        update_equipment(UpdateEquipmentInput(equipment_id=unit.pk, fields=(("kind", other),)), actor=None)
    assert "size" in error.value.message_dict
    moved = update_equipment(
        UpdateEquipmentInput(equipment_id=unit.pk, fields=(("kind", other), ("size", None))), actor=None
    )
    assert moved.kind_id == other.pk and moved.size_id is None


@pytest.mark.django_db
def test_computing_unit_gets_profile_rdp_file_and_activity(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    kind = _kind("computing", monitored=True)
    created = client.post(
        ROOT,
        {"kind_id": kind.pk, "sku": "COL-PC-1", "name": "Workstation", "computing": {"hostname": "pc-1.lab"}},
        format="json",
    )
    assert created.status_code == 201, created.data
    body = created.data["data"]
    profile = ComputingProfile.objects.get(equipment_id=body["id"])
    assert profile.hostname == "pc-1.lab" and profile.rdp_file.name.endswith(".rdp")
    assert ComputingActivity.objects.filter(computing_id=body["id"]).exists()
    assert body["computing"]["hostname"] == "pc-1.lab"
    assert body["activity"]["status"]["value"] == "offline"
    technical_user = TechnicalUser.objects.create(username="svc-lab")
    changed = client.patch(
        f"{ROOT}/{body['id']}", {"computing": {"technical_user_id": technical_user.pk}}, format="json"
    )
    assert changed.status_code == 200, changed.data
    assert changed.data["data"]["computing"]["technical_user"] == {"id": technical_user.pk, "name": "svc-lab"}
    activity = client.get(f"{ROOT}/{body['id']}/activity")
    assert activity.status_code == 200 and activity.data["data"]["status"]["value"] == "offline"


@pytest.mark.django_db
def test_computing_fields_are_refused_outside_monitored_categories(client):
    kind = _kind("networking")
    response = client.post(
        ROOT, {"kind_id": kind.pk, "sku": "COL-NET-1", "name": "Switch", "computing": {"hostname": "x"}}, format="json"
    )
    assert response.status_code == 422, response.data
    unit = Equipment.objects.create(sku="COL-NET-2", name="Switch", kind=kind)
    assert client.get(f"{ROOT}/{unit.pk}/activity").status_code == 404


@pytest.mark.django_db
def test_a_computing_unit_cannot_leave_a_monitored_category():
    kind = _kind("computing", monitored=True)
    unit = Equipment.objects.create(sku="COL-PC-2", name="PC", kind=kind)
    ComputingProfile.objects.create(equipment=unit)
    with pytest.raises(ValidationError) as error:
        update_equipment(UpdateEquipmentInput(equipment_id=unit.pk, fields=(("kind", _kind("other")),)), actor=None)
    assert "kind" in error.value.message_dict


@pytest.mark.django_db
def test_category_flags_gate_bench_placement_loans_and_calibration(coordinator):
    kind = _kind("furniture", placeable_on_bench=False, bookable=False, calibratable=False)
    unit = Equipment.objects.create(sku="COL-FUR-1", name="Cabinet", kind=kind)
    bench = Bench.objects.create(sku="COL-BENCH-1", name="Bench")
    with pytest.raises(InvalidEquipmentStatus):
        assign_equipment(AssignEquipmentInput(equipment_id=unit.pk, bench_id=bench.pk), actor=None)
    with pytest.raises(EquipmentNotAvailable) as error:
        hand_over_equipment(
            HandOverEquipmentInput(
                equipment_id=unit.pk, borrower_id=coordinator.pk, due_at=timezone.now() + timedelta(days=1)
            ),
            actor=coordinator,
        )
    assert "category is not bookable" in str(error.value.details)
    with pytest.raises(ValidationError) as calibration:
        update_equipment(
            UpdateEquipmentInput(equipment_id=unit.pk, fields=(("calibration_required", True),)), actor=None
        )
    assert "calibration_required" in calibration.value.message_dict


@pytest.mark.django_db
def test_category_reports_its_capabilities(client):
    kind = _kind("display", bookable=False)
    response = client.get(f"{ROOT}/reference-data", {"category": kind.category_id})
    assert response.status_code == 200
    (category,) = response.data["data"]["categories"]
    assert {"value": "bookable", "label": "Bookable"} not in category["capabilities"] and {
        "value": "assignable",
        "label": "Assignable",
    } in category["capabilities"]


@pytest.mark.django_db
def test_status_summary_for_one_category(client):
    display = _kind("display")
    Equipment.objects.create(sku="COL-SUM-1", name="A", kind=display)
    Equipment.objects.create(sku="COL-SUM-2", name="B", kind=_kind("other"))
    response = client.get(f"{ROOT}/status-summary", {"category": display.category_id})
    assert response.status_code == 200, response.data
    assert response.data["data"]["total_count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["computing", "display/1", "computing/sku/X/activity"])
def test_category_route_sets_are_gone(client, path):
    assert client.get(f"{ROOT}/{path}").status_code == 404


@pytest.mark.django_db
def test_list_query_count_does_not_grow_with_rows(client, coordinator, django_assert_max_num_queries):
    effective_labs_roles(coordinator)
    kind = _kind("sample")
    interface = EquipmentInterface.objects.create(name="USB")
    for index in range(5):
        unit = Equipment.objects.create(sku=f"COL-Q-{index}", name=f"Sample {index}", kind=kind)
        unit.interfaces.add(interface)
        ComputingProfile.objects.create(equipment=unit) if index == 0 else None
    client.get(ROOT)  # warm content types and permissions
    with django_assert_max_num_queries(8) as few:
        assert client.get(ROOT).status_code == 200
    for index in range(5, 15):
        unit = Equipment.objects.create(sku=f"COL-Q-{index}", name=f"Sample {index}", kind=kind)
        unit.interfaces.add(interface)
    with django_assert_max_num_queries(len(few.captured_queries)):
        assert client.get(ROOT).status_code == 200


@pytest.mark.django_db
def test_list_pages_with_page_and_page_size(client):
    kind = _kind("sample")
    for index in range(5):
        Equipment.objects.create(sku=f"COL-P-{index}", name=f"Page {index}", kind=kind)
    response = client.get(ROOT, {"ordering": "name", "page": 2, "page_size": 2})
    assert response.status_code == 200, response.data
    assert [row["sku"] for row in response.data["data"]] == ["COL-P-2", "COL-P-3"]
    pagination = response.data["meta"]["pagination"]
    assert (pagination["count"], pagination["page"], pagination["page_size"]) == (5, 2, 2)
    assert "page=3" in pagination["next"] and "page_size=2" in pagination["next"]
    assert "page_size=2" in pagination["previous"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "code"),
    [
        ({"page": 0}, "invalid_query"),
        ({"page": "abc"}, "invalid_query"),
        ({"page_size": 0}, "invalid_query"),
        ({"page_size": 101}, "max_value"),
    ],
)
def test_list_rejects_invalid_paging(client, query, code):
    response = client.get(ROOT, query)
    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid_query"
    [detail] = response.data["error"]["details"]
    assert (detail["field"], detail["code"]) == (next(iter(query)), code)


def test_list_documents_page_and_page_size():
    from drf_spectacular.generators import SchemaGenerator

    from core.labs.features.equipment.api.urls import urlpatterns

    schema = SchemaGenerator(patterns=urlpatterns).get_schema(public=True)
    parameters = {item["name"]: item for item in schema["paths"]["/equipment"]["get"]["parameters"]}
    for name in ("page", "page_size"):
        assert parameters[name]["in"] == "query"
        assert not parameters[name].get("required", False)
        assert parameters[name]["schema"]["type"] == "integer"
        assert parameters[name]["schema"]["minimum"] == 1
    assert parameters["page_size"]["schema"]["maximum"] == 100
