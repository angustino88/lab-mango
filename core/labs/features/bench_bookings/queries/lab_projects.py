"""Read-only selectors for the lab projects that bookings are charged to."""

from django.db.models import F, Q, QuerySet

from core.labs.features.bench_bookings.exceptions import LabProjectNotFound
from core.labs.models import LabProject

_COLUMNS = ("id", "project_name", "code", "active", "starts_on", "ends_on")


def list_lab_projects(*, search: str | None = None, active: bool | None = None) -> QuerySet[LabProject]:
    """Return projects ordered by name then id, optionally filtered by name/code text and active flag."""
    queryset = LabProject.objects.only(*_COLUMNS).order_by("project_name", "pk")
    if search:
        queryset = queryset.filter(Q(project_name__icontains=search) | Q(code__icontains=search))
    if active is not None:
        queryset = queryset.filter(active=active)
    return queryset


def list_lab_project_options(
    *,
    actor=None,
    q=None,
    active_on=None,
    include_ids=None,
):
    """Return lab project selector options (ADR 002)."""
    cond = Q(active=True)
    if active_on:
        cond &= (
            (Q(starts_on__isnull=True) | Q(starts_on__lte=active_on))
            & (Q(ends_on__isnull=True) | Q(ends_on__gte=active_on))
        )
    if q:
        cond &= (Q(project_name__icontains=q) | Q(code__icontains=q))

    if include_ids:
        query_filter = cond | Q(pk__in=include_ids)
    else:
        query_filter = cond

    return (
        LabProject.objects.filter(query_filter)
        .annotate(sku=F("code"), name=F("project_name"))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def get_lab_project(*, project_id: int) -> LabProject:
    """Return one project or raise ``LabProjectNotFound``."""
    project = LabProject.objects.only(*_COLUMNS).filter(pk=project_id).first()
    if project is None:
        raise LabProjectNotFound()
    return project
