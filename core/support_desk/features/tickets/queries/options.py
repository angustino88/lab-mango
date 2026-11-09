"""Options selectors strictly conforming to the system /options standard (ADR 002)."""

from typing import Any

from django.db.models import CharField, F, Q, Value
from django.db.models.functions import NullIf

from core.support_desk.models.category import SupportCategory
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam


def get_category_options(*, actor: Any = None, q: str | None = None, search: str | None = None, include_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Return active categories formatted as {id, sku, name}."""
    search_term = q or search
    cond = Q(is_active=True)
    if search_term:
        cond &= Q(name__icontains=search_term)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return list(
        SupportCategory.objects.filter(cond)
        .annotate(sku=F("code"))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def get_priority_options(*, actor: Any = None, q: str | None = None, search: str | None = None, include_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Return active priorities formatted as {id, sku, name} with sku=NULLIF(code, '')."""
    search_term = q or search
    cond = Q(is_active=True)
    if search_term:
        cond &= Q(name__icontains=search_term)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return list(
        SupportPriority.objects.filter(cond)
        .annotate(sku=NullIf(F("code"), Value("")))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def get_status_options(
    *,
    actor: Any = None,
    q: str | None = None,
    search: str | None = None,
    system_state: str | None = None,
    include_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return active statuses formatted as {id, sku, name} with sku=null."""
    search_term = q or search
    cond = Q(is_active=True)
    if system_state:
        cond &= Q(system_state=system_state)
    if search_term:
        cond &= Q(name__icontains=search_term)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return list(
        SupportStatus.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def get_team_options(*, actor: Any = None, q: str | None = None, search: str | None = None, include_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Return active teams formatted as {id, sku, name}."""
    search_term = q or search
    cond = Q(is_active=True)
    if search_term:
        cond &= Q(name__icontains=search_term)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return list(
        SupportTeam.objects.filter(cond)
        .annotate(sku=F("code"))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )


def get_label_options(*, actor: Any = None, q: str | None = None, search: str | None = None, include_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Return labels formatted as {id, sku, name} with sku=null."""
    search_term = q or search
    cond = Q()
    if search_term:
        cond &= Q(name__icontains=search_term)
    if include_ids:
        cond |= Q(pk__in=include_ids)
    return list(
        SupportLabel.objects.filter(cond)
        .annotate(sku=Value(None, output_field=CharField()))
        .values("id", "sku", "name")
        .order_by("name", "id")
    )
