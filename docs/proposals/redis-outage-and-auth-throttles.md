# Redis outage resilience and auth throttle integrity

> Status: implemented, awaiting review. Tier **T2** (authn, infra/config):
> needs security + QA review and human approval before merge. No new required setting.

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
| Cache circuit | Uses the process-local breaker from `main` (`CACHE_CIRCUIT_BREAKER_SECONDS`, default 5 s): after a cache failure, optional cache calls skip Redis; invalidation bumps always try. This branch adds `is_cache_outage()` and `record_cache_failure()` so throttles share the same breaker. | `core/common/cache.py` |
| Default throttles | `FailOpenAnonRateThrottle` / `FailOpenUserRateThrottle`: same sliding-log semantics and rates. On a cache outage they allow the request, log, and trip the circuit. | `core/common/api/throttling.py`, `config/settings/base.py` |
| Error mapping | Any cache outage error that reaches a view is `503 service_unavailable` + `Retry-After: 30`, not 500. A cache outage is any `RedisError`, or a built-in `TimeoutError` raised inside the redis client; timeouts from other code (`asyncio.wait_for`, futures) stay 500. Other unhandled errors are now logged before the 500 envelope. | `core/common/api/exceptions.py`, `core/users/features/auth/api.py` |
| Atomic auth throttle | `AtomicRateThrottle`: fixed window with cache `add` + `incr` (atomic in Redis via django-redis Lua, and in LocMem). Fails closed by default; subclasses with `local_fallback_on_outage = True` count in a process-local fixed window (`LocalWindowCounter`, bounded to 10 000 keys) while the cache is down. | `core/common/api/throttling.py` |
| Auth outage policy | SSO sign-in (`SSOLoginIPThrottle`) and refresh (`RefreshUserThrottle`, `RefreshIPThrottle`) use the local fallback, so users can still sign in and refresh while Redis is down. Password login and OTP (non-SSO) still fail closed (503). | `core/users/features/auth/throttles.py`, `core/users/features/auth/refresh_token/api.py` |
| Auth identities | aad-login: per IP `auth_sso_login` 10/min (same rate as before, own env variable). refresh: per **verified** user `auth_refresh` 30/min plus per-IP `auth_ip` 300/min. Password login (non-SSO): per username plus `auth_ip`. OTP (non-SSO): per caller. | `core/users/features/auth/throttles.py`, auth views |
| Local dev cache | `LOCAL_USE_REDIS_CACHE=True` with Redis unreachable at startup warns and falls back to `LocMemCache` (local settings only; production unchanged). | `config/settings/local.py` |
| Trusted client IP | Optional `DJANGO_NUM_PROXIES` → `REST_FRAMEWORK["NUM_PROXIES"]`. Unset keeps DRF's current behavior (no deploy change); setting it makes per-IP budgets spoof-proof. | `config/settings/base.py`, `.env.example` |

Alternatives considered:
- A token bucket / GCRA in Lua for every endpoint: not needed for this fix. The general API budget (300/min)
  tolerates the race. Only the small auth budgets need atomic counts.
- Keying aad-login on the unverified `oid` claim: rejected. A forged token with a victim's `oid` could lock
  that victim out.
- No new dependency (AGENTS.md rule 7).

## 3. Evidence: same tests before and after

Tests: `core/common/tests/test_redis_outage_resilience.py`,
`core/users/tests/features/auth/test_auth_throttle_integrity.py` and
`core/users/tests/features/auth/test_auth_throttle_outage_fallback.py`. All are database-free.

| Test | Before (main) | After |
|---|---|---|
| Authenticated GET while Redis is down | 500 `internal_error` | 200 |
| 20 cache reads while Redis is down | 20 backend calls (20 × timeout) | 1 backend call |
| 5 requests, Redis answers after 0.2 s then fails | `[500]*5`, each waits | `[200]*5`, only the first waits |
| Cache-dependent handler during outage | 500 | 503 + `Retry-After: 30` |
| 20 parallel logins against a 5/min limit | **20 of 20** reached the credential check | exactly 5 (15 × 429) |
| aad-login with a new spoofed `X-Forwarded-For` each time, 2/min | `[401, 401, 401]` (never limited) | `[401, 401, 429]` **only with `NUM_PROXIES` configured**; unset behaves as before |
| 6 colleagues refresh from one IP, 3/min | users 4–6 got 429 | none throttled |
| `TimeoutError` from application code (not the cache) | 500 | 500 `internal_error` (not reported as a cache outage) |
| Password login during outage stays fail-closed (503, no credential check) | pass | pass |
| aad-login while Redis is down | 500 (503 with the earlier fail-closed throttle) | reaches the Entra check (401 with a synthetic token) |
| aad-login while Redis is down, 2/min, 3 requests | `[500, 500, 500]` | `[401, 401, 429]` (per worker) |
| One user refreshing 4× at 3/min while Redis is down; another user once | all 500 | `[401, 401, 401, 429]`; other user 401 |
| One user refreshing 4× at 3/min still gets 429 | pass | pass |

## 4. Deployment and residual risks

- **Spoofing is fixed only by configuration:** `DJANGO_NUM_PROXIES` is optional so deploys are not blocked.
  While unset, a client can still vary `X-Forwarded-For` to get fresh per-IP budgets (`auth_sso_login`,
  `auth_ip`). With SSO-only production this buys an attacker request volume, not access (tokens are signed).
  Setting it too low would put every user behind the router into one bucket, so confirm the hop count with
  `labmango-router` first.
- **Behavior changes:** aad-login keeps 10/min per IP but reads `THROTTLE_AUTH_SSO_LOGIN` instead of
  `THROTTLE_AUTH_LOGIN` (deployments that override `THROTTLE_AUTH_LOGIN` must set both). Its per-IP budget can
  still be shared by an office behind one address; raise it from access logs if needed. Refresh moves from per IP to per user plus a per-IP backstop.
  Cache outages return 503 instead of 500.
- **Fail-open window:** while Redis is down, general API throttling is off (only per-worker semaphores bound
  load).
- **Auth during an outage (owner decision changed):** the frontend calls `/api/aad-login` on every page load,
  so failing closed would lock out everyone who reloads while Redis is down. SSO sign-in and refresh now
  count in a process-local window instead. Each worker counts on its own, so with `N` workers a client can
  reach up to `N` times the rate, and the atomic burst guarantee holds only per worker. Guessing is not a
  risk on these paths (aad-login needs an Entra-signed ID token, refresh a refresh token signed by this
  service). Password login and OTP keep failing closed.
- Fixed windows can admit up to twice the rate across a window boundary.
- Not changed here: Celery and WebSocket pub/sub still depend on Redis. Direct `cache.*` users (agent nonce,
  import progress, routing selectors, WS task ownership) still fail closed; behind views that use the shared
  exception handler they now return 503 (not verified for each view).
- Database-backed suites `core/users/tests` and `core/common/tests` (including `test_auth_throttling.py` and
  `test_entra_security.py::test_entra_login_is_throttled`) pass against a local PostgreSQL. Not run: a real
  Redis outage with several workers; the per-worker multiplier is reasoned, not measured.
