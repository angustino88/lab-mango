"""Computing columns of an equipment unit (``ComputingProfile``) and its .rdp file.

A unit has a profile exactly when its category is ``monitored``. The equipment create and
update commands call these helpers inside their transaction, after locking the ``Equipment``
row, so the profile needs no lock of its own.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from core.labs.models import ComputingProfile, Equipment, TechnicalUser

# The hostname names the RDP host and is entered at registration. ip_address, os_name,
# disk_usage and system_info are agent-reported and never written through the API.
PROFILE_CREATE_FIELDS = frozenset({"hostname"})
PROFILE_UPDATE_FIELDS = frozenset({"monitored_devices", "technical_user"})
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
    """Create the profile of a new monitored unit and its .rdp file."""
    profile = ComputingProfile(equipment=equipment, **_clean_values(values, PROFILE_CREATE_FIELDS))
    profile.full_clean(exclude=("equipment",))
    profile.save()
    sync_rdp_file(profile)
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
    host = profile.rdp_host
    if not host:
        return
    from core.infrastructure.remote_access.rdp_file import create_rdp_file

    if profile.rdp_file and profile.rdp_file.name:
        try:
            profile.rdp_file.delete(save=False)
        except Exception:  # noqa: BLE001 - a missing old file must not block the write.
            pass
    content = create_rdp_file(host, profile.technical_user)
    profile.rdp_file.save(f"{profile.equipment.sku or profile.pk}.rdp", ContentFile(content.getvalue()), save=False)
    profile.save(update_fields=("rdp_file", "modified"))


__all__ = (
    "PROFILE_CREATE_FIELDS",
    "PROFILE_UPDATE_FIELDS",
    "create_profile",
    "sync_rdp_file",
    "update_profile",
)
