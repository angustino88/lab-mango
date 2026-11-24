## Summary

Fixes two problems found while reviewing anti-spam protection after the performance work in #45:

- **A. A Redis outage takes down every authenticated API** (500 on every request, each waiting for the
  socket timeout first).
- **B. Auth throttles can be passed by a concurrent burst, and refresh is limited per office instead of per user.**

**Tier T2** (authn, infra/config): needs security + QA review and owner approval. No migration, no API schema
change, no new dependency, **no new required setting**.

Design note with alternatives and residual risks: `docs/proposals/redis-outage-and-auth-throttles.md`.

## All issues found in the review, and what this PR does with each

Production signs in through Entra SSO only (aad-login + refresh cookie), so password-login and OTP findings
are non-production. Severity reflects that.

| # | Issue | Severity | In this PR? |
|---|---|---|---|
| A | Redis outage → default throttles raise → **500 on every authenticated API**; `safe_cache_*` waits for the 3 s timeout on every call, holding semaphore slots 6–9 s per request | High | **Fixed** |
| B1 | DRF `SimpleRateThrottle` reads then writes non-atomically → a concurrent burst passes the limit (20 of 20 passed a 5/min limit in the test) | Medium (auth budgets are small) | **Fixed for auth endpoints** |
| B2 | aad-login / refresh keyed per IP → colleagues behind one NAT/proxy address share one budget | Medium | **Fixed for refresh** (per verified user). aad-login stays per IP at 10/min: no trustworthy identity exists before the ID token is verified. |
| B3 | `NUM_PROXIES` unset → client-supplied `X-Forwarded-For` is the identity → spoofed values get fresh budgets | Low in prod (signed SSO tokens cannot be guessed) | **Configurable only**: optional `DJANGO_NUM_PROXIES`; unset keeps current behavior. The hop count is not known yet. |
| 1 | Load-test report (1000 requests, one JWT, 0 % errors) cannot reflect production throttling | Measurement only | Not in this PR. Rerun with many users and production rates. |
| 3 | Search/import/export only have the general 300/min budget; distinct `?q=` values miss the read cache | Low now (small tables), grows with data | Deferred |
| 6 | Semaphore queue is unbounded, with no 503 load-shedding | Medium | Deferred |
| 7 | No `RateLimit-*` headers; CORS does not expose `Retry-After` | Low | Deferred |
| 8 | `/internal` routing sync has no throttle | Low if the router blocks `/internal` (not verified) | Deferred |
| N1 | Uploads are read fully before the 10 MB size check | Medium | Deferred (better as a body limit in the router) |
| N2 | No per-user cap on WebSocket connections | Medium | Deferred |
| N3 | Failed authentication (401) is never throttled | Low–medium | Deferred |

## Changes

| Area | Change |
|---|---|
| `core/common/cache.py` | Process-local circuit breaker. After one Redis/timeout error, fail-open readers skip Redis for `API_CACHE_CIRCUIT_OPEN_SECONDS` (default 10 s). Writes and invalidation bumps always try. |
| `core/common/api/throttling.py` (new) | `FailOpenAnonRateThrottle` / `FailOpenUserRateThrottle`: same rates and semantics as before; on a cache outage they allow, log and trip the circuit. `AtomicRateThrottle`: fixed window with cache `add` + `incr` (atomic); fails closed. |
| `core/common/api/exceptions.py` | Cache outage errors reaching a view become `503 service_unavailable` + `Retry-After: 30` instead of 500. |
| `core/users/features/auth/throttles.py` (new) + auth views | aad-login: per IP 10/min (unchanged rate, new env `THROTTLE_AUTH_SSO_LOGIN`). Refresh: per user from the **signature-verified** cookie, 30/min, plus a per-IP backstop of 300/min (`auth_ip`); a forged cookie counts against the sender's IP. Password login (non-SSO): per username plus `auth_ip`. OTP (non-SSO): per caller. |
| `config/settings/base.py`, `test.py`, `.env.example` | New default throttle classes and rates; optional `DJANGO_NUM_PROXIES`; circuit setting (disabled in tests). |
| Docs | `core/users/features/auth/docs/spec.md` §3.3, H4 status in `docs/proposals/user-authentication-hardening.md`, the design note. |

## Behavior changes for reviewers

- A cache outage returns **503 instead of 500** wherever the error reaches a view.
- While Redis is down, **general API throttling is off** (the per-worker semaphore still bounds load). Auth
  throttles still fail closed, so SSO sign-in and refresh return 503 during an outage. This keeps the existing
  owner decision.
- Refresh is limited **per user** instead of per IP.
- aad-login reads `THROTTLE_AUTH_SSO_LOGIN` (default 10/min) instead of `THROTTLE_AUTH_LOGIN`. A deployment that
  overrides `THROTTLE_AUTH_LOGIN` must set both.
- Fixed windows can admit up to twice the rate across a window boundary.

## Evidence: same tests on `main` and on this branch

`core/common/tests/test_redis_outage_resilience.py` and
`core/users/tests/features/auth/test_auth_throttle_integrity.py` (database-free):

| Scenario | `main` | This branch |
|---|---|---|
| Authenticated GET while Redis is down | 500 | 200 |
| 20 cache reads while Redis is down | 20 backend calls | 1 |
| 5 requests, Redis fails after 0.2 s | `[500]*5`, each waits | `[200]*5`, only the first waits |
| Cache-dependent handler during outage | 500 | 503 + `Retry-After` |
| 20 parallel logins, limit 5/min | 20 reach the credential check | exactly 5 |
| 6 users behind one IP refresh once, limit 3/min | users 4–6 get 429 | none throttled |
| One user refreshes 4×, limit 3/min | 4th is 429 | 4th is 429 (unchanged) |
| Login during outage | 503, credentials not checked | same (unchanged) |
| Spoofed `X-Forwarded-For` with `NUM_PROXIES=1` | — | shares the real client's budget |

## Test plan

- [x] New tests: 7 of 9 fail on `main`; 9 of 9 pass here.
- [x] Auth, cache, throttle-settings and agent-info suites: 132 passed (local PostgreSQL).
- [x] Full suite: 3643 passed. The remaining failures are not regressions:
  - telemetry: `Unknown or inactive metric`; fails identically on `main`.
  - `tests/websocket/*`: no local Redis; `test_pubsub` also fails on `main`.
- [x] `ruff check` on the CI scope plus the new files.
- [ ] CI run with Redis and PostgreSQL services.
- [ ] Owner decision on `DJANGO_NUM_PROXIES` once the `labmango-router` hop count is known.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
