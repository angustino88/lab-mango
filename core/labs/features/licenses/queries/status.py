"""The status a license reads as: its latest status record, else what its seats say."""

from django.db.models import Case, CharField, Exists, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce

from core.labs.models import LicenseStatus, LicenseStatusRecord
from core.labs.models.resource.license.assignment import LicenseAssignment


def license_status_expression() -> Coalesce:
    """Annotation for a License queryset (one correlated subquery each, no per-row queries).

    The latest status record wins. A license with no record yet (created before initial records
    were written) reads as ``assigned`` when a seat is held and ``available`` otherwise, which is
    what its first record would have been (spec §2.1: default ``available``).
    """
    latest = LicenseStatusRecord.objects.filter(license_id=OuterRef("pk")).order_by("-created", "-id")
    seat_held = LicenseAssignment.objects.filter(
        license_id=OuterRef("pk"), unassigned_at__isnull=True, equipment__deleted_at__isnull=True
    )
    default = Case(
        When(Exists(seat_held), then=Value(LicenseStatus.ASSIGNED.value)),
        default=Value(LicenseStatus.AVAILABLE.value),
        output_field=CharField(),
    )
    return Coalesce(Subquery(latest.values("status")[:1]), default, output_field=CharField())


__all__ = ["license_status_expression"]
