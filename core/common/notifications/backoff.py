"""Exponential backoff calculation with jitter for asynchronous retries."""

from datetime import timedelta


def calculate_backoff_delay(
    *,
    attempt: int,
    base_seconds: float = 30.0,
    max_seconds: float = 900.0,
    jitter: float = 0.0,
) -> timedelta:
    """Calculate bounded exponential retry delay with multiplicative jitter.

    Delay formula:
        delay = min(max_seconds, base_seconds * 2 ** max(0, attempt - 1)) * (1 + clamped_jitter)
    Where jitter is clamped to [0.0, 1.0].
    """
    clamped_jitter = min(max(jitter, 0.0), 1.0)
    exponent = max(0, attempt - 1)
    base = min(max_seconds, base_seconds * (2**exponent))
    return timedelta(seconds=base * (1.0 + clamped_jitter))
