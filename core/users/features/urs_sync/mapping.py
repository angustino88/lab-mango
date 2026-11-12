"""Keep each URS group's Django group created and named for it.

The URS group is the only place roles are configured. Its Django group only stores membership (written by
URS sync) and is created and renamed here; nobody maintains it by hand.

Race guard: the caller saves the URS group inside a transaction and this function locks that row before
creating the Django group, so two saves of the same URS group cannot create two groups. Django group names
are unique in the database; a name already used by another group gets the URS id appended.
"""

from django.contrib.auth.models import Group
from django.db import transaction

from core.users.models import URSGroup

_NAME_MAX_LENGTH: int = Group._meta.get_field("name").max_length or 150


def ensure_linked_group(urs_group_pk: int) -> Group:
    """Create the URS group's Django group if missing, and keep its name in step. Safe to run twice."""
    with transaction.atomic():
        urs_group = URSGroup.objects.select_for_update().get(pk=urs_group_pk)
        wanted = _name_for(urs_group)
        group = urs_group.group
        if group is None:
            group = Group.objects.create(name=_free_name(wanted, urs_group))
            urs_group.group = group
            urs_group.save(update_fields=["group"])
        elif group.name != wanted:
            name = _free_name(wanted, urs_group, current=group)
            if name != group.name:
                group.name = name
                group.save(update_fields=["name"])
        return group


def _name_for(urs_group: URSGroup) -> str:
    base = (urs_group.urs_group_name or "").strip() or f"URS {urs_group.urs_group_id}"
    return base[:_NAME_MAX_LENGTH]


def _free_name(wanted: str, urs_group: URSGroup, *, current: Group | None = None) -> str:
    taken = Group.objects.filter(name=wanted)
    if current is not None:
        taken = taken.exclude(pk=current.pk)
    if not taken.exists():
        return wanted
    suffix = f" (URS {urs_group.urs_group_id})"
    return wanted[: _NAME_MAX_LENGTH - len(suffix)] + suffix
