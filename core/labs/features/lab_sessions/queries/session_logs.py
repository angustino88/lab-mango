"""Session log list (work package A6, flat view of proposal §5.4)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from core.labs.models.session.lab_session import LabSessionLog

# Accepted ``ordering`` values. Every ordering ends with the row id, so pages are stable.
SESSION_LOG_ORDERINGS: dict[str, tuple[str, ...]] = {
    "-login_time": ("-login_time", "-id"),
    "login_time": ("login_time", "id"),
    "-logout_time": ("-logout_time", "-id"),
    "logout_time": ("logout_time", "id"),
    "-active_duration_seconds": ("-active_duration_seconds", "-id"),
    "active_duration_seconds": ("active_duration_seconds", "id"),
}
DEFAULT_ORDERING = "-login_time"


def _start_of(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def list_session_logs(
    *,
    start_date: date,
    end_date: date,
    bench_id: int | None = None,
    computer_id: int | None = None,
    user_id: int | None = None,
    access_type: str | None = None,
    q: str | None = None,
    ordering: str | None = None,
) -> QuerySet[LabSessionLog]:
    """Sessions whose login falls on ``start_date``..``end_date`` (inclusive, server time zone).

    Bounded read: the date range is required (the caller caps its length) and the result is paged by
    the view. Related rows are joined in the same query, so a page costs one query plus the count.
    """
    queryset = LabSessionLog.objects.select_related("computing_equipment", "bench", "user", "booking").filter(
        login_time__gte=_start_of(start_date),
        login_time__lt=_start_of(end_date + timedelta(days=1)),
    )
    if bench_id is not None:
        queryset = queryset.filter(bench_id=bench_id)
    if computer_id is not None:
        queryset = queryset.filter(computing_equipment_id=computer_id)
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    if access_type:
        queryset = queryset.filter(access_type=access_type)
    if q:
        queryset = queryset.filter(
            Q(remote_user__icontains=q)
            | Q(remote_user_display_name__icontains=q)
            | Q(host_name__icontains=q)
            | Q(booking_code__icontains=q)
            | Q(computing_equipment__sku__icontains=q)
            | Q(computing_equipment__name__icontains=q)
            | Q(bench__sku__icontains=q)
            | Q(bench__name__icontains=q)
        )
    return queryset.order_by(*SESSION_LOG_ORDERINGS[ordering or DEFAULT_ORDERING])


__all__ = ["DEFAULT_ORDERING", "SESSION_LOG_ORDERINGS", "list_session_logs"]
