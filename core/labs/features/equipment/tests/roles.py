"""Test helper: give a user a Labs role through a synthetic URS group mapping."""

import itertools

from django.contrib.auth.models import Group

from core.users.models import URSGroup

_URS_IDS = itertools.count(940000)


def grant_labs_role(user, role: str):
    """Map ``user`` to ``role`` (``admin``, ``coord`` or ``user``) and return it."""
    urs_id = next(_URS_IDS)
    group = Group.objects.create(name=f"equipment-test-{role}-{urs_id}")
    URSGroup.objects.create(group=group, urs_group_id=urs_id, labs_role=role)
    user.groups.add(group)
    return user
