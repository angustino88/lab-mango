"""Deterministic deduplication key generation for outbox events."""

import hashlib
from typing import Any


def compute_dedupe_key(*components: Any) -> str:
    """Generate a SHA-256 deduplication key from logical event components."""
    serialized = ":".join(str(c) for c in components)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
