"""Computing columns of an equipment unit (``ComputingProfile``) and its .rdp file.

A unit has a profile exactly when its category is ``monitored``. The equipment create and
update commands call these helpers inside their transaction, after locking the ``Equipment``
row, so the profile needs no lock of its own.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from core.common.models import validate_for_write
from core.labs.models import ComputingProfile, Equipment, TechnicalUser

# The hostname names the RDP host and is entered at registration. ip_address, os_name,
# disk_usage and system_info are agent-reported and never written through the API.
PROFILE_CREATE_FIELDS = frozenset({"hostname", "technical_user"})
PROFILE_UPDATE_FIELDS = frozenset({"technical_user"})
# A change to one of these regenerates the .rdp file.
RDP_SOURCE_FIELDS = frozenset({"hostname", "technical_user"})


def _clean_values(values: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    unexpected = values.keys() - allowed
    if unexpected:
        raise ValidationError({f"computing.{name}": "Unknown or read-only field." for name in sorted(unexpected)})
    cleaned = dict(values)
    technical_user = cleaned.get("technical_user")
    if technical_user is not None and not isinstance(technical_user, TechnicalUser):
        found = TechnicalUser.objects.filter(pk=technical_user).first()
        if found is None:
            raise ValidationError({"computing.technical_user": "Select a valid reference."})
        cleaned["technical_user"] = found
    return cleaned


def create_profile(equipment: Equipment, values: dict[str, Any]) -> ComputingProfile:
    """Create the profile of a unit created in this transaction, with its .rdp file, in one INSERT.

    The unit is new, so it has no profile yet: the primary-key uniqueness check is skipped and the row is
    inserted directly (``save()`` would first try an UPDATE because the primary key is the unit's id).
    """
    profile = ComputingProfile(equipment=equipment, **_clean_values(values, PROFILE_CREATE_FIELDS))
    validate_for_write(profile, skip_unique=("equipment",))
    _write_rdp_file(profile)
    profile.save(force_insert=True)
    return profile


def update_profile(equipment: Equipment, values: dict[str, Any], *, sku_changed: bool) -> ComputingProfile:
    """Apply profile changes of a monitored unit; create the profile if the unit just became monitored."""
    profile = ComputingProfile.objects.filter(equipment=equipment).first()
    if profile is None:
        profile = ComputingProfile(equipment=equipment)
    cleaned = _clean_values(values, PROFILE_UPDATE_FIELDS)
    for name, value in cleaned.items():
        setattr(profile, name, value)
    profile.full_clean(exclude=("equipment",))
    regenerate = profile._state.adding or sku_changed or bool(RDP_SOURCE_FIELDS & cleaned.keys())
    profile.save()
    if regenerate:
        sync_rdp_file(profile)
    return profile


def sync_rdp_file(profile: ComputingProfile) -> None:
    """Write the .rdp file for the profile's host (hostname, else the SKU); no-op without a host."""
    if _write_rdp_file(profile):
        profile.save(update_fields=("rdp_file", "modified"))


def _write_rdp_file(profile: ComputingProfile) -> bool:
    """Store a new .rdp file on ``profile.rdp_file`` without saving the row; ``False`` without a host."""
    host = profile.rdp_host
    if not host:
        return False
    from core.infrastructure.remote_access.rdp_file import create_rdp_file

    if profile.rdp_file and profile.rdp_file.name:
        try:
            profile.rdp_file.delete(save=False)
        except Exception:  # noqa: BLE001 - a missing old file must not block the write.
            pass
    content = create_rdp_file(host, profile.technical_user)
    profile.rdp_file.save(f"{profile.equipment.sku or profile.pk}.rdp", ContentFile(content.getvalue()), save=False)
    return True


__all__ = (
    "PROFILE_CREATE_FIELDS",
    "PROFILE_UPDATE_FIELDS",
    "create_profile",
    "sync_rdp_file",
    "update_profile",
)
