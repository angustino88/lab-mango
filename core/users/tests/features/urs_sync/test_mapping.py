"""A URS group's Django group is created and named automatically."""

import pytest
from django.contrib.auth.models import Group

from core.users.features.urs_sync.mapping import ensure_linked_group
from core.users.models import URSGroup

pytestmark = pytest.mark.django_db


def test_creates_named_group_once():
    urs_group = URSGroup.objects.create(urs_group_id=55001, urs_group_name="Lab Coordinators")

    first = ensure_linked_group(urs_group.pk)
    second = ensure_linked_group(urs_group.pk)

    urs_group.refresh_from_db()
    assert first.pk == second.pk == urs_group.group_id
    assert first.name == "Lab Coordinators"
    assert Group.objects.filter(name="Lab Coordinators").count() == 1


def test_unnamed_group_uses_urs_id():
    urs_group = URSGroup.objects.create(urs_group_id=55002)

    assert ensure_linked_group(urs_group.pk).name == "URS 55002"


def test_rename_follows_urs_name():
    urs_group = URSGroup.objects.create(urs_group_id=55003, urs_group_name="Old name")
    group = ensure_linked_group(urs_group.pk)

    URSGroup.objects.filter(pk=urs_group.pk).update(urs_group_name="New name")
    ensure_linked_group(urs_group.pk)

    group.refresh_from_db()
    assert group.name == "New name"


def test_name_already_used_by_another_group_gets_urs_id_suffix():
    Group.objects.create(name="Shared name")
    urs_group = URSGroup.objects.create(urs_group_id=55004, urs_group_name="Shared name")

    group = ensure_linked_group(urs_group.pk)

    assert group.name == "Shared name (URS 55004)"
    assert Group.objects.filter(name="Shared name").count() == 1
