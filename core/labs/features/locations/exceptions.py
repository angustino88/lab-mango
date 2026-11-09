"""Stable location business errors."""


from core.common.domain.errors import Conflict


class LocationConflict(Conflict):
    """Raised when a location command conflicts with current domain state."""

    code = "location_conflict"


class RoomConflict(LocationConflict):
    """Raised when a room layout or room lifecycle command conflicts."""

    code = "room_conflict"


__all__ = ["LocationConflict", "RoomConflict"]
