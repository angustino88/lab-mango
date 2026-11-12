"""Shared admin bases for Labs catalogs."""

from core.common.admin import LabMangoModelAdmin


class NamedLookupAdmin(LabMangoModelAdmin):
    """Simple ``name``-only reference list (materials, interfaces, license types, ...)."""

    list_display = ("name", "modified")
    search_fields = ("name",)
    ordering = ("name",)


class ActiveNamedLookupAdmin(LabMangoModelAdmin):
    """``name`` + ``description`` + ``active`` reference list."""

    list_display = ("name", "active", "modified")
    list_filter = ("active",)
    search_fields = ("name", "description")
    ordering = ("name",)


# Room.__str__ reads country, city and building; select them wherever a room is displayed.
ROOM_LABEL_RELATED = ("country", "city", "building")


def room_label_related(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}__{name}" for name in ROOM_LABEL_RELATED)
