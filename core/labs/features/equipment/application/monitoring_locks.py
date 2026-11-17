"""Equipment-owned workflow locks for monitoring commands."""

from django.db import transaction

from core.common.domain.errors import Conflict
from core.labs.models import Equipment


@transaction.atomic
def lock_monitoring_computer(computer_id: int) -> None:
    """Parent lock, taken before agent identity and monitoring rows; no relation locks."""
    if (
        not Equipment.objects.select_for_update(of=("self",))
        .filter(pk=computer_id, computing_profile__isnull=False)
        .exists()
    ):
        raise Conflict("The reporting computer is unavailable.", code="equipment_unavailable")
