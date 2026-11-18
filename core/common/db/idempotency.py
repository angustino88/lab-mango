"""Transaction-scoped, nonblocking PostgreSQL idempotency claims."""

import hashlib

from django.db import connection


def try_claim_operation(scope: bytes) -> bool:
    """Acquire before resource locks; release automatically with the transaction.

    SHA-256's signed 64-bit prefix scopes the PostgreSQL advisory lock. A hash
    collision conservatively returns busy; it cannot grant duplicate execution.
    """
    key = int.from_bytes(hashlib.sha256(scope).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [key])
        return bool(cursor.fetchone()[0])
