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
