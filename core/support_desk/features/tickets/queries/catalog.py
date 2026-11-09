"""Catalog reads for Support Desk configuration entities (ADR 002 catalogs).

Everyone who may read a catalog sees its active rows; inactive rows are configuration history and are
visible only to support administrators (ADR 002, Phase 0 decision 0.4).
"""

from typing import Any

from django.db.models import QuerySet

from core.support_desk.features.tickets.application.policies import is_support_admin
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam


def _only_active_unless_admin(queryset: QuerySet, viewer: Any) -> QuerySet:
    if is_support_admin(viewer):
        return queryset
    return queryset.filter(is_active=True)


def list_categories(*, viewer: Any) -> QuerySet[SupportCategory]:
    return _only_active_unless_admin(SupportCategory.objects.select_related("default_team"), viewer).order_by(
        "sort_order", "id"
    )


def list_priorities(*, viewer: Any) -> QuerySet[SupportPriority]:
    return _only_active_unless_admin(SupportPriority.objects.all(), viewer).order_by("rank", "id")


def list_statuses(*, viewer: Any) -> QuerySet[SupportStatus]:
    return _only_active_unless_admin(SupportStatus.objects.all(), viewer).order_by("sort_order", "id")


def list_teams(*, viewer: Any) -> QuerySet[SupportTeam]:
    return _only_active_unless_admin(
        SupportTeam.objects.select_related("lead").prefetch_related("members"), viewer
    ).order_by("name", "id")


def list_labels(*, viewer: Any) -> QuerySet[SupportLabel]:
    """Labels have no active flag; every label is readable."""
    return SupportLabel.objects.order_by("name", "id")
