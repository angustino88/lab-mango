"""KPI assessment of one user or one bench: scorecard against targets, rating, strengths, development areas.

Read-only and derived from the leaderboard KPIs (``selectors``), so the assessment always agrees with the
figures in the rankings. The previous period is the equal-length window just before the requested one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db import models

from core.labs.models import Bench

from ..exceptions import ResourceNotFoundError
from .selectors import compute_leaderboard_lab, compute_leaderboard_persona

# Fewer sessions plus bookings than this is not enough evidence for a rating.
MIN_EVIDENCE = 3


class AssessmentRating(models.TextChoices):
    EXCEEDS = "exceeds", "Exceeds expectations"
    MEETS = "meets", "Meets expectations"
    PARTIALLY_MEETS = "partially_meets", "Partially meets expectations"
    BELOW = "below", "Below expectations"
    INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"


class KpiStatus(models.TextChoices):
    MET = "met", "On target"
    NEAR = "near", "Near target"
    BELOW = "below", "Below target"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class AssessmentKpi(models.TextChoices):
    BOOKING_ATTENDANCE = "booking_attendance", "Booking attendance"
    BOOKED_TIME_USED = "booked_time_used", "Booked time used"
    SLOT_ADHERENCE = "slot_adherence", "Slot adherence"
    ACTIVE_RATE = "active_rate", "Active time in sessions"
    ADVANCE_BOOKING = "advance_booking", "Sessions without a booking"
    AFTER_HOURS = "after_hours", "After-hours share"
    LAB_PRESENCE = "lab_presence", "Lab presence"
    UTILIZATION = "utilization", "Bench utilization"
    BOOKING_FILL = "booking_fill", "Booking fill"


@dataclass(frozen=True)
class KpiDefinition:
    kpi: AssessmentKpi
    source: str  # key in the leaderboard row
    target: float
    near: float  # still "near target" up to here
    weight: int
    is_higher_better: bool = True

    def status(self, value: float | None) -> str:
        if value is None:
            return KpiStatus.NOT_APPLICABLE
        if self.is_higher_better:
            return KpiStatus.MET if value >= self.target else KpiStatus.NEAR if value >= self.near else KpiStatus.BELOW
        return KpiStatus.MET if value <= self.target else KpiStatus.NEAR if value <= self.near else KpiStatus.BELOW

    def attainment(self, value: float) -> float:
        """0..1: how far the value goes towards the target (capped at the target)."""
        if self.is_higher_better:
            return min(1.0, value / self.target) if self.target else 1.0
        if value <= self.target:
            return 1.0
        return max(0.0, 1.0 - (value - self.target) / (1.0 - self.target))


K = AssessmentKpi
PERSONA_KPIS = (
    KpiDefinition(K.BOOKING_ATTENDANCE, "booking_compliance", target=0.90, near=0.75, weight=3),
    KpiDefinition(K.BOOKED_TIME_USED, "booking_utilization", target=0.75, near=0.50, weight=2),
    KpiDefinition(K.ACTIVE_RATE, "active_rate", target=0.80, near=0.60, weight=2),
    KpiDefinition(K.SLOT_ADHERENCE, "slot_adherence", target=0.95, near=0.80, weight=1),
    KpiDefinition(K.ADVANCE_BOOKING, "ad_hoc_rate", target=0.20, near=0.40, weight=1, is_higher_better=False),
    KpiDefinition(K.AFTER_HOURS, "late_rate", target=0.10, near=0.25, weight=1, is_higher_better=False),
    KpiDefinition(K.LAB_PRESENCE, "usage_efficiency", target=0.50, near=0.25, weight=1),
)
BENCH_KPIS = (
    KpiDefinition(K.UTILIZATION, "utilization_rate", target=0.60, near=0.30, weight=3),
    KpiDefinition(K.BOOKING_ATTENDANCE, "booking_compliance", target=0.90, near=0.75, weight=2),
    KpiDefinition(K.BOOKED_TIME_USED, "booking_utilization", target=0.75, near=0.50, weight=2),
    KpiDefinition(K.BOOKING_FILL, "booking_fill", target=0.50, near=0.25, weight=1),
)


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _hours_per_weekday(efficiency: float) -> str:
    return f"{round(efficiency * 8, 1):g} h"


# What a met KPI says about the subject, and what a missed one says plus the recommended action.
def _strength(kpi: str, v: float, row: dict[str, Any]) -> str:
    attended = row.get("total_bookings", 0) - row.get("no_show_bookings", 0)
    return {
        K.BOOKING_ATTENDANCE: f"Reliable attendance: {attended} of {row.get('total_bookings', 0)} bookings used ({_pct(v)}).",
        K.BOOKED_TIME_USED: f"Efficient use of reserved time: {_pct(v)} of booked hours were used.",
        K.SLOT_ADHERENCE: f"Keeps to the reserved slot: {_pct(v)} of booked-session time was inside the slot.",
        K.ACTIVE_RATE: f"Focused sessions: {_pct(v)} of session time was active.",
        K.ADVANCE_BOOKING: f"Plans ahead: {_pct(1 - v)} of sessions ran under a booking.",
        K.AFTER_HOURS: f"Works within regular hours: {_pct(v)} of lab time after 20:00.",
        K.LAB_PRESENCE: f"Consistent lab presence: {_hours_per_weekday(v)} of active work per weekday.",
        K.UTILIZATION: f"Well utilised: active {_pct(v)} of working hours.",
        K.BOOKING_FILL: f"In demand: {_pct(v)} of working hours are booked.",
    }[kpi]


def _development(kpi: str, v: float, row: dict[str, Any]) -> tuple[str, str]:
    return {
        K.BOOKING_ATTENDANCE: (
            f"Booking attendance is {_pct(v)}: {row.get('no_show_bookings', 0)} of "
            f"{row.get('total_bookings', 0)} bookings had no session.",
            "Cancel or shorten bookings that will not be used, so the bench is released for others.",
        ),
        K.BOOKED_TIME_USED: (
            f"Only {_pct(v)} of booked time was used.",
            "Book slots that match the planned test duration.",
        ),
        K.SLOT_ADHERENCE: (
            f"{_pct(1 - v)} of booked-session time fell outside the reserved slot.",
            "Start and finish within the reserved slot, or extend the booking in advance.",
        ),
        K.ACTIVE_RATE: (
            f"Sessions were active {_pct(v)} of the time.",
            "Log off when not working, so the computer is free for others.",
        ),
        K.ADVANCE_BOOKING: (
            f"{_pct(v)} of sessions ran without a booking.",
            "Reserve the bench before use, so availability stays predictable for the team.",
        ),
        K.AFTER_HOURS: (
            f"{_pct(v)} of lab time was after hours (20:00-06:00).",
            "Plan long runs within working hours where possible, or agree after-hours work with the lab coordinator.",
        ),
        K.LAB_PRESENCE: (
            f"Low lab presence: {_hours_per_weekday(v)} of active work per weekday.",
            "Review whether the current bench reservations are still needed.",
        ),
        K.UTILIZATION: (
            f"Low utilisation: active {_pct(v)} of working hours.",
            "Promote the bench to teams waiting for capacity, or review whether it is still needed in this setup.",
        ),
        K.BOOKING_FILL: (
            f"Only {_pct(v)} of working hours are booked.",
            "Make the bench visible to more teams, or consolidate its workload with a similar bench.",
        ),
    }[kpi]


def _score(definitions: tuple[KpiDefinition, ...], row: dict[str, Any] | None) -> int | None:
    if not row:
        return None
    total = weight = 0.0
    for definition in definitions:
        value = row.get(definition.source)
        if value is None:
            continue
        total += definition.attainment(float(value)) * definition.weight
        weight += definition.weight
    return round(total / weight * 100) if weight else None


def _rating(score: int | None, enough: bool) -> str:
    if not enough or score is None:
        return AssessmentRating.INSUFFICIENT_DATA
    if score >= 85:
        return AssessmentRating.EXCEEDS
    if score >= 70:
        return AssessmentRating.MEETS
    if score >= 50:
        return AssessmentRating.PARTIALLY_MEETS
    return AssessmentRating.BELOW


def _summary(rating: str, score: int | None, previous: int | None, row: dict[str, Any], strengths, areas) -> str:
    evidence = f"{row.get('total_sessions', 0)} sessions and {row.get('total_bookings', 0)} bookings"
    if rating == AssessmentRating.INSUFFICIENT_DATA:
        return f"Not enough activity for a rating ({evidence} in the period)."
    # Rating, score and evidence are fields of their own; the summary is the narrative around them.
    parts = []
    if previous is None:
        parts.append("No previous period to compare.")
    else:
        delta = score - previous
        parts.append(
            "Unchanged from the previous period."
            if delta == 0
            else f"{'Up' if delta > 0 else 'Down'} {abs(delta)} points on the previous period ({previous}/100)."
        )
    if strengths:
        parts.append(f"Key strength: {AssessmentKpi(strengths[0]['kpi']).label.lower()}.")
    if areas:
        parts.append(f"Main focus: {AssessmentKpi(areas[0]['kpi']).label.lower()}.")
    return " ".join(parts)


def _assess(
    definitions: tuple[KpiDefinition, ...],
    row: dict[str, Any],
    previous_row: dict[str, Any] | None,
    start_date: datetime,
    end_date: datetime,
    previous_start: datetime,
) -> dict[str, Any]:
    kpis, strengths, areas = [], [], []
    for definition in definitions:
        value = row.get(definition.source)
        previous = previous_row.get(definition.source) if previous_row else None
        status = definition.status(value)
        kpis.append(
            {
                "kpi": definition.kpi.value,
                "value": value,
                "previous_value": previous,
                "target": definition.target,
                "is_higher_better": definition.is_higher_better,
                "weight": definition.weight,
                "status": status,
            }
        )
        if status == KpiStatus.MET:
            strengths.append({"kpi": definition.kpi.value, "text": _strength(definition.kpi, value, row)})
        elif status in (KpiStatus.NEAR, KpiStatus.BELOW):
            finding, recommendation = _development(definition.kpi, value, row)
            areas.append(
                {
                    "kpi": definition.kpi.value,
                    "severity": status,
                    "text": finding,
                    "recommendation": recommendation,
                }
            )
    # Most serious first: below target before near target, heavier KPIs first (stable for equal weight).
    areas.sort(key=lambda area: area["severity"] != KpiStatus.BELOW)

    enough = row.get("total_sessions", 0) + row.get("total_bookings", 0) >= MIN_EVIDENCE
    score = _score(definitions, row)
    rating = _rating(score, enough)
    previous_score = None
    if previous_row and previous_row.get("total_sessions", 0) + previous_row.get("total_bookings", 0) >= MIN_EVIDENCE:
        previous_score = _score(definitions, previous_row)
    if rating == AssessmentRating.INSUFFICIENT_DATA:
        score = None
    return {
        "period": {"starts_at": start_date, "ends_at": end_date},
        "previous_period": {"starts_at": previous_start, "ends_at": start_date},
        "rating": rating,
        "score": score,
        "previous_score": previous_score,
        "summary": _summary(rating, score, previous_score, row, strengths, areas),
        "total_sessions": row.get("total_sessions", 0),
        "total_bookings": row.get("total_bookings", 0),
        "kpis": kpis,
        "strengths": strengths,
        "development_areas": areas,
    }


def _previous_window(start_date: datetime, end_date: datetime) -> datetime:
    return start_date - (end_date - start_date)


def get_user_assessment(pk: int, start_date: datetime, end_date: datetime) -> dict[str, Any]:
    """KPI assessment of one active user for the window, with the previous window for the trend."""
    if not get_user_model().objects.filter(pk=pk, is_active=True).exists():
        raise ResourceNotFoundError(f"User {pk} not found")
    previous_start = _previous_window(start_date, end_date)
    current = next(iter(compute_leaderboard_persona(start_date, end_date, user_id=pk)), None)
    previous = next(iter(compute_leaderboard_persona(previous_start, start_date, user_id=pk)), None)
    row = current or {"total_sessions": 0, "total_bookings": 0}
    return _assess(PERSONA_KPIS, row, previous, start_date, end_date, previous_start)


def get_bench_assessment(pk: int, start_date: datetime, end_date: datetime) -> dict[str, Any]:
    """KPI assessment of one bench for the window, with the previous window for the trend."""
    if not Bench.objects.filter(pk=pk, deleted_at__isnull=True).exists():
        raise ResourceNotFoundError(f"Bench {pk} not found")
    previous_start = _previous_window(start_date, end_date)
    current = next(iter(compute_leaderboard_lab(start_date, end_date, bench_id=pk)), None)
    previous = next(iter(compute_leaderboard_lab(previous_start, start_date, bench_id=pk)), None)
    row = current or {"total_sessions": 0, "total_bookings": 0}
    return _assess(BENCH_KPIS, row, previous, start_date, end_date, previous_start)


__all__ = [
    "AssessmentKpi",
    "AssessmentRating",
    "KpiStatus",
    "get_bench_assessment",
    "get_user_assessment",
]
