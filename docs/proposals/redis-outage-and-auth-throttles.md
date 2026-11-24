# Redis outage resilience and auth throttle integrity

> Status: implemented on branch `fix/redis-outage-and-auth-throttles`. Tier **T2** (authn, infra/config):
> needs security + QA review and human approval before merge. Production deploy needs `DJANGO_NUM_PROXIES`.

## 1. Problems

### A. A Redis outage takes down every authenticated API

- Every request runs the default `UserRateThrottle`/`AnonRateThrottle`, which call the cache directly.
  Production sets `IGNORE_EXCEPTIONS=False` (`config/settings/production.py`), so the Redis error escapes and
  `api_exception_handler` answers **500 `internal_error`**. This happens even though the read cache was designed
  to fall back to PostgreSQL.
- Before the throttle runs, JWT auth and role lookups call `safe_cache_get`. That call swallows the error, but
  it first waits for the socket timeout (3 s default). With two or three lookups per request, each request
  holds a semaphore slot for 6–9 s before it fails.
- Other cache users that must fail closed (agent request nonces, import progress, routing selectors) also
  surface the outage as 500 instead of a retryable 503.

### B. Auth throttles can be passed by a burst, keyed on a spoofable header, and shared across an office

Production signs in only through Entra SSO (`aad-login` + refresh cookie). Brute force is not feasible
against signed tokens. The real risks are:

- **Race:** DRF `SimpleRateThrottle` reads the timestamp list, then writes it back, with no atomicity. A
  concurrent burst reads the same history, so the whole burst passes.
- **Spoofing:** `NUM_PROXIES` was unset, so DRF keyed on the raw client-supplied `X-Forwarded-For` value.
  Each new header value got a fresh budget.
- **Shared IP:** `aad-login` (10/min) and `refresh` (30/min) were keyed per IP. Colleagues behind one NAT or
  proxy address consume one budget, and the SPA refreshes every 10 minutes per tab.

## 2. Changes

| Area | Change | Files |
|---|---|---|
| Cache circuit | After one outage error, fail-open readers skip Redis for `API_CACHE_CIRCUIT_OPEN_SECONDS` (default 10 s, per process). Writes and invalidation bumps always try. Only Redis/timeout errors trip it. | `core/common/cache.py` |
| Default throttles | `FailOpenAnonRateThrottle` / `FailOpenUserRateThrottle`: same sliding-log semantics and rates. On a cache outage they allow the request, log, and trip the circuit. | `core/common/api/throttling.py`, `config/settings/base.py` |
| Error mapping | Any cache outage error that reaches a view is `503 service_unavailable` + `Retry-After: 30`, not 500. | `core/common/api/exceptions.py`, `core/users/features/auth/api.py` |
| Atomic auth throttle | `AtomicRateThrottle`: fixed window with cache `add` + `incr` (atomic in Redis via django-redis Lua, and in LocMem). Fails closed. | `core/common/api/throttling.py` |
| Auth identities | aad-login: per IP `auth_sso_login` 60/min. refresh: per **verified** user `auth_refresh` 30/min plus per-IP `auth_ip` 300/min. Password login (non-SSO): per username plus `auth_ip`. OTP (non-SSO): per caller. | `core/users/features/auth/throttles.py`, auth views |
| Trusted client IP | `REST_FRAMEWORK["NUM_PROXIES"]` from `DJANGO_NUM_PROXIES`. Default 0 (ignore `X-Forwarded-For`); **required** in production. | `config/settings/base.py`, `production.py`, `.env.example` |

Alternatives considered:
- A token bucket / GCRA in Lua for every endpoint: not needed for this fix. The general API budget (300/min)
  tolerates the race. Only the small auth budgets need atomic counts.
- Keying aad-login on the unverified `oid` claim: rejected. A forged token with a victim's `oid` could lock
  that victim out.
- No new dependency (AGENTS.md rule 7).

## 3. Evidence: same tests before and after

Tests: `core/common/tests/test_redis_outage_resilience.py` and
`core/users/tests/features/auth/test_auth_throttle_integrity.py`. Both are database-free.

| Test | Before (main) | After |
|---|---|---|
| Authenticated GET while Redis is down | 500 `internal_error` | 200 |
| 20 cache reads while Redis is down | 20 backend calls (20 × timeout) | 1 backend call |
| 5 requests, Redis answers after 0.2 s then fails | `[500]*5`, each waits | `[200]*5`, only the first waits |
| Cache-dependent handler during outage | 500 | 503 + `Retry-After: 30` |
| 20 parallel logins against a 5/min limit | **20 of 20** reached the credential check | exactly 5 (15 × 429) |
| aad-login with a new `X-Forwarded-For` each time, 2/min | `[401, 401, 401]` (never limited) | `[401, 401, 429]` |
| 6 colleagues refresh from one IP, 3/min | users 4–6 got 429 | none throttled |
| Login during outage stays fail-closed (503, no credential check) | pass | pass |
| One user refreshing 4× at 3/min still gets 429 | pass | pass |

## 4. Deployment and residual risks

- **Deploy blocker by design:** production settings fail to load without `DJANGO_NUM_PROXIES`. Set it to the
  number of proxies that append to `X-Forwarded-For` (`labmango-router` owns that tier; record it in the
  router contract). With a wrong value that is too low, every user shares the router's address: the
  `auth_sso_login` and `auth_ip` budgets become company-wide.
- **Behavior changes:** aad-login moves from `THROTTLE_AUTH_LOGIN` (10/min per IP) to
  `THROTTLE_AUTH_SSO_LOGIN` (60/min per IP). Refresh moves from per IP to per user plus a per-IP backstop.
  Cache outages return 503 instead of 500.
- **Fail-open window:** while Redis is down, general API throttling is off (only per-worker semaphores bound
  load). Auth throttles still fail closed, so SSO sign-in and token refresh return 503 during an outage.
  This is the existing owner decision, kept as is.
- Fixed windows can admit up to twice the rate across a window boundary.
- Not changed here: Celery and WebSocket pub/sub still depend on Redis. Direct `cache.*` users (agent nonce,
  import progress, routing selectors, WS task ownership) still fail closed; behind views that use the shared
  exception handler they now return 503 (not verified for each view).
- Not run locally: the database-backed suites, including `test_auth_throttling.py` and
  `test_entra_security.py::test_entra_login_is_throttled`. Both were updated for the new classes.
