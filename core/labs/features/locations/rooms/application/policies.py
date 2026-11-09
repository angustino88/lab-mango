"""Room layout checks: pure, no ORM queries, writes, or transport dependencies."""

from core.labs.features.locations.exceptions import RoomConflict


def grid_positions(rows: int, columns: int):
    """Yield zero-based (row, column) indexes with their one-based slot codes, row-major."""
    for row in range(rows):
        for column in range(columns):
            yield row, column, f"R{row + 1}C{column + 1}"


__all__ = ["RoomConflict", "grid_positions"]
