"""Admin index sections, section pages, changelist smoke tests and admin user stamping."""

from collections import Counter

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.urls import reverse

from config.admin_site import ADMIN_SECTIONS
from core.labs.models import (
    BenchBooking,
    Building,
    City,
    Country,
    EquipmentCategory,
    EquipmentKind,
    EquipmentType,
    Room,
)
from core.users.models import User
from tests.factories import BenchBookingFactory


def _key(model):
    return f"{model._meta.app_label}.{model.__name__}"


def _superuser_client(client):
    user = User.objects.create_superuser(username="admin_root", email="root@example.test", password="unused")
    client.force_login(user)
    return client, user


def test_every_registered_model_is_in_exactly_one_section():
    section_keys = [key for section in ADMIN_SECTIONS for key in section.models]
    registered = {_key(model) for model in admin.site._registry}

    assert [key for key, count in Counter(section_keys).items() if count > 1] == []
    assert sorted(registered - set(section_keys)) == [], "Add newly registered models to ADMIN_SECTIONS"
    assert sorted(set(section_keys) - registered) == [], "ADMIN_SECTIONS names an unregistered model"


@pytest.mark.django_db
def test_index_groups_models_into_sections_and_keeps_model_urls(client):
    client, _ = _superuser_client(client)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    names = [app["name"] for app in response.context["app_list"]]
    assert names == [section.name for section in ADMIN_SECTIONS]
    locations = response.context["app_list"][1]
    assert [m["object_name"] for m in locations["models"]] == ["Country", "City", "Building", "StationType"]
    assert locations["models"][0]["admin_url"] == "/admin/labs/country/"


@pytest.mark.django_db
def test_staff_only_sees_sections_they_have_permissions_for(client):
    staff = User.objects.create_user(username="catalog_editor", password="unused", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_country"))
    client.force_login(staff)

    index = client.get(reverse("admin:index"))
    allowed = client.get(reverse("admin:section", kwargs={"slug": "reference-locations"}))
    denied = client.get(reverse("admin:section", kwargs={"slug": "bookings"}))

    assert [app["name"] for app in index.context["app_list"]] == ["Reference data · Locations"]
    assert allowed.status_code == 200
    assert [m["object_name"] for m in allowed.context["app_list"][0]["models"]] == ["Country"]
    assert denied.status_code == 404


@pytest.mark.django_db
def test_unknown_section_is_404_and_app_index_keeps_django_grouping(client):
    client, _ = _superuser_client(client)

    assert client.get(reverse("admin:section", kwargs={"slug": "nope"})).status_code == 404
    app_index = client.get(reverse("admin:app_list", kwargs={"app_label": "labs"}))
    assert app_index.status_code == 200
    assert [app["app_label"] for app in app_index.context["app_list"]] == ["labs"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model", [m for m in admin.site._registry if m._meta.app_label == "labs"], ids=lambda m: m.__name__
)
def test_labs_changelist_and_add_form_render(client, model):
    client, _ = _superuser_client(client)
    opts = model._meta

    changelist = client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist"))
    add = client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_add"))

    assert changelist.status_code == 200
    assert add.status_code in (200, 403)  # 403: the model admin forbids adding.


@pytest.mark.django_db
def test_room_changelist_query_count_does_not_grow_with_rows(client, django_assert_max_num_queries):
    client, _ = _superuser_client(client)
    url = reverse("admin:labs_room_changelist")

    def add_room(index):
        country = Country.objects.create(code=f"C{index}", name=f"Country {index}")
        city = City.objects.create(name=f"City {index}", country=country)
        building = Building.objects.create(name=f"B{index}", city=city)
        Room.objects.create(name=f"Room {index}", sku=f"R-{index}", country=country, city=city, building=building)

    add_room(0)
    with django_assert_max_num_queries(50) as one_row:
        client.get(url)
    for index in range(1, 4):
        add_room(index)
    with django_assert_max_num_queries(len(one_row.captured_queries)):
        response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_bench_booking_changelist_query_count_does_not_grow_with_rows(client, django_assert_max_num_queries):
    client, _ = _superuser_client(client)
    url = reverse("admin:labs_benchbooking_changelist")
    BenchBookingFactory()

    with django_assert_max_num_queries(50) as one_row:
        client.get(url)
    for _ in range(3):
        BenchBookingFactory()
    with django_assert_max_num_queries(len(one_row.captured_queries)):
        response = client.get(url)
    assert BenchBooking.objects.count() == 4
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_add_stamps_creator_and_last_modified_by(client):
    client, user = _superuser_client(client)

    response = client.post(reverse("admin:labs_country_add"), {"code": "VN", "name": "Vietnam"})

    assert response.status_code == 302
    country = Country.objects.get(code="VN")
    assert country.creator == user
    assert country.last_modified_by == user


@pytest.mark.django_db
def test_admin_inline_rows_are_stamped_and_deleted(client):
    client, user = _superuser_client(client)
    category = EquipmentCategory.objects.create(name="Computing", definition="Computers")
    kind = EquipmentKind.objects.create(category=category, name="Computer")
    doomed = EquipmentType.objects.create(kind=kind, name="Old type")
    prefix = "types"

    response = client.post(
        reverse("admin:labs_equipmentkind_change", args=[kind.pk]),
        {
            "category": kind.category_id,
            "name": kind.name,
            "active": "on",
            f"{prefix}-TOTAL_FORMS": "2",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-0-id": doomed.pk,
            f"{prefix}-0-kind": kind.pk,
            f"{prefix}-0-name": doomed.name,
            f"{prefix}-0-active": "on",
            f"{prefix}-0-DELETE": "on",
            f"{prefix}-1-kind": kind.pk,
            f"{prefix}-1-name": "Workstation",
            f"{prefix}-1-active": "on",
        },
    )

    assert response.status_code == 302, response.context and response.context["errors"]
    assert not EquipmentType.objects.filter(pk=doomed.pk).exists()
    created = EquipmentType.objects.get(kind=kind, name="Workstation")
    assert created.creator == user
    assert EquipmentKind.objects.get(pk=kind.pk).last_modified_by == user


@pytest.mark.django_db
def test_equipment_categories_are_view_only_even_for_superusers(client):
    client, _ = _superuser_client(client)
    category = EquipmentCategory.objects.create(name="Computing", definition="Computers")
    EquipmentKind.objects.create(category=category, name="Laptop")
    change_url = reverse("admin:labs_equipmentcategory_change", args=[category.pk])

    add = client.get(reverse("admin:labs_equipmentcategory_add"))
    view = client.get(change_url)
    post = client.post(change_url, {"name": "Renamed", "definition": "x"})

    assert add.status_code == 403
    assert view.status_code == 200
    assert view.context["has_change_permission"] is False
    assert view.context["has_add_permission"] is False
    kinds_inline = view.context["inline_admin_formsets"][0]
    assert not (kinds_inline.has_add_permission or kinds_inline.has_change_permission)
    assert post.status_code == 403
    category.refresh_from_db()
    assert category.name == "Computing"


@pytest.mark.django_db
def test_kinds_can_still_be_added_under_a_provisioned_category(client):
    client, user = _superuser_client(client)
    category = EquipmentCategory.objects.create(name="Computing", definition="Computers")

    response = client.post(
        reverse("admin:labs_equipmentkind_add"),
        {
            "category": category.pk,
            "name": "Laptop",
            "active": "on",
            "types-TOTAL_FORMS": "0",
            "types-INITIAL_FORMS": "0",
        },
    )

    assert response.status_code == 302
    assert EquipmentKind.objects.get(category=category, name="Laptop").creator == user


@pytest.mark.parametrize(
    ("model_name", "plural"),
    [
        ("Bench", "benches"),
        ("Equipment", "equipment"),
        ("EquipmentCategory", "equipment categories"),
        ("ComputingActivity", "computing activities"),
        ("PurchasePriority", "purchase priorities"),
    ],
)
def test_admin_list_names_use_correct_plurals(model_name, plural):
    from django.apps import apps

    assert str(apps.get_model("labs", model_name)._meta.verbose_name_plural) == plural


_VIEW_ONLY_LABS_MODELS = (
    # Status history and audit: appended by feature commands.
    "RoomStatusRecord",
    "StationStatusRecord",
    "EquipmentEvent",
    "ResourceAudit",
    "ResourceChangeLog",
    # Agent-reported activity and ingested telemetry.
    "ComputingActivity",
    "LabSessionLog",
    "MonitoringEvent",
    "LaboratoryVisitEvent",
    "StorageQuotaMeasurement",
    # Analytics observations: derived snapshots written by analytics tasks.
    "ActiveUserObservation",
    "ActiveLaboratoryObservation",
    "BookingVolumeObservation",
    "BookingOutcomeObservation",
    "VisitorVolumeObservation",
    "ResourceUtilizationObservation",
    "LaboratoryAvailabilityObservation",
    "ProjectUsageObservation",
)


@pytest.mark.parametrize("model_name", _VIEW_ONLY_LABS_MODELS)
def test_logs_telemetry_and_observations_are_view_only_even_for_superusers(rf, model_name):
    from django.apps import apps

    model_admin = admin.site._registry[apps.get_model("labs", model_name)]
    request = rf.get("/admin/")
    request.user = User(is_superuser=True, is_staff=True, is_active=True)

    assert model_admin.has_view_permission(request)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    assert model_admin.get_actions(request) == {}
