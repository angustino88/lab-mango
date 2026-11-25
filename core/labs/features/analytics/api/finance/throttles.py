"""Shared bounded finance budget, using caller IDs or IP, never API-key material."""

from hashlib import sha256

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

from core.common.api.throttling import OutageAwareThrottleMixin, OutagePolicy


class FinanceCallerThrottle(OutageAwareThrottleMixin, SimpleRateThrottle):
    scope = "finance_analytics"
    rate = "30/min"
    # The budget bounds expensive finance queries; without its counters, refuse (503 + Retry-After)
    # rather than run them unbounded.
    outage_policy: OutagePolicy = "deny"

    def get_cache_key(self, request: Request, view: object) -> str:
        if request.user.is_authenticated:
            identity = f"user:{request.user.pk}"
        else:
            # API-key callers share their IP budget, even if they rotate keys.
            # Do not accept client-controlled forwarding headers as identity.
            identity = f"ip:{request.META.get('REMOTE_ADDR', '')}"
        return self.cache_format % {"scope": self.scope, "ident": sha256(identity.encode()).hexdigest()}
