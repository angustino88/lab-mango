"""Stable location business errors."""


from core.common.domain.errors import Conflict


class LocationConflict(Conflict):
    """Raised when a location command conflicts with current domain state."""

    code = "location_conflict"


class RoomConflict(LocationConflict):
    """Raised when a room layout or room lifecycle command conflicts."""

    code = "room_conflict"


class LocationBookingConflict(LocationConflict):
    """Downtime from the deprecated ``change-status`` would overlap bookings. ``details``: ``bench_bookings.<id>``.

    Same code as the downtime API; use ``POST /api/labs/downtimes`` with ``cancel_conflicting_bookings``.
    """

    code = "downtime_booking_conflict"
    default_message = (
        "Bookings overlap this downtime. Cancel them, or use /api/labs/downtimes with cancel_conflicting_bookings."
    )


__all__ = ["LocationBookingConflict", "LocationConflict", "RoomConflict"]
