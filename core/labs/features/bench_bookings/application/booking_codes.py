"""Generation of opaque, hash-derived public booking codes."""

import hashlib
import secrets
from datetime import datetime


def generate_booking_code(*, bench_id: int, starts_at: datetime, ends_at: datetime) -> str:
    """Return a compact SHA-256-derived code with cryptographic collision entropy."""
    material = "|".join(
        (
            str(bench_id),
            starts_at.isoformat(),
            ends_at.isoformat(),
            secrets.token_urlsafe(18),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest().lower()
    return f"BOOKING-{digest[:8]}{digest[-6:]}"
