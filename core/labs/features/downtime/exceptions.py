"""Stable business errors of the downtime feature."""

from core.common.domain.errors import Conflict


class DowntimeBookingConflict(Conflict):
    """Reserving bookings overlap the window. ``details``: one entry per booking, field
    ``bench_bookings.<id>`` or ``equipment_bookings.<id>``, code ``booking_overlaps_downtime``.

    Resend with ``cancel_conflicting_bookings: true`` to cancel them in the same transaction (RS4).
    """

    code = "downtime_booking_conflict"
    default_message = "Bookings overlap this downtime window. Cancel them or choose another period."


class DowntimeOverlap(Conflict):
    """Another downtime window of the same resource overlaps (constraint ``downtime_no_overlap``)."""

    code = "downtime_overlap"
    default_message = "Another downtime window of this resource overlaps this period."


class DowntimeNotAllowed(Conflict):
    """The resource or the window is in a state that does not allow this action."""

    code = "downtime_not_allowed"
    default_message = "This downtime action is not allowed in the current state."


__all__ = ["DowntimeBookingConflict", "DowntimeNotAllowed", "DowntimeOverlap"]
