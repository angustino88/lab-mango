"""Stable bench business errors."""


from core.common.domain.errors import Conflict


class BenchConflict(Conflict):
    """Raised when a bench command conflicts with current domain state."""

    code = "bench_conflict"


__all__ = ["BenchConflict"]
