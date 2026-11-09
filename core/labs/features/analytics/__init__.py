"""Analytics feature domain package."""
from .queries.calculations import (
    SLOT_LABELS,
    aggregate_observation_buckets,
    calculate_official_working_hours,
    calculate_period_trend,
    calculate_timeslot_distribution,
    calculate_working_hours,
    get_nearest_monday,
    get_nearest_tuesday,
)

__all__ = [
    "SLOT_LABELS",
    "aggregate_observation_buckets",
    "calculate_official_working_hours",
    "calculate_period_trend",
    "calculate_timeslot_distribution",
    "calculate_working_hours",
    "get_nearest_monday",
    "get_nearest_tuesday",
]
