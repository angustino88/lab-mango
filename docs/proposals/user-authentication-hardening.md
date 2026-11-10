# User Authentication Hardening Proposal

**Status:** Proposed — not approved, nothing implemented
**Risk tier:** T2 — authentication, API contract, migrations, settings
**Scope:** `core/users/features/auth`, `core/users/backends.py`, `core/users/checks.py`,
`core/users/features/lifecycle`, `core/users/features/urs_sync`, `core/websocket/middleware.py`,
`config/settings/`, `config/asgi.py`, `config/celery_app.py`.
**Basis:** read-only review of the code at commit `a8c3459`. No code was changed. No tests or quality
gates were run. Items marked *not verified* depend on deployment configuration that is not in this
repository.

## Objective

Close the gaps that would matter once the Entra-only authentication feature serves real users. The feature
is pre-production, so contract changes (route layout, cookie scope, token claims) are still cheap. Each
item below is a separate decision for the repository owner; none depends on all the others.

## What already holds and must be preserved

- [ ] The login nonce is single-use, stored only as a digest, and bound to a browser cookie
  (`aad_login/service.py:66-72`, `:110-121`).
- [ ] Refresh rotation and logout lock the same outstanding-token row, so concurrent refreshes have one
  winner (`tokens.py:16-21`).
- [ ] Every production request re-checks the user's Entra binding, so deactivating a user or unlinking an
  identity takes effect on the next request (`authentication.py:12-28`).
- [ ] Staff and superusers are never bound by username; only the operator command binds them
  (`aad_login/service.py:88`, `management/commands/bind_entra_identity.py`).
- [ ] Password, LDAP and OTP routes are not mounted in production (`auth/urls.py:10-14`).
- [ ] Production settings are checked for consistency at startup (`checks.py`).

## Findings and proposed changes

Severity: **High** = fix before production; **Medium** = fix before or shortly after; **Low** = cleanup.

### High

#### H1. First-login binding by username can bind the wrong person

- **Evidence:** `aad_login/service.py:75-99` binds an unbound Entra identity to the local user whose
  username equals `preferred_username` *or only its local part* (`:81-83`). The switch
  `ENTRA_BIND_BY_USERNAME` defaults to on (`config/settings/base.py:111`). `preferred_username` is mutable
  and Microsoft documents it as unsuitable for authorization. Accounts to bind are stubs created from URS
  data by username alone (`urs_sync/sync_group/service.py:106`).
- **Failure cases:** a guest account or a second verified domain with the same local part; a UPN reassigned
  to a new employee before the previous owner ever logged in. Whoever logs in first owns the account.
- **Also:** contradicts the model docstring "No email-based linking" (`models/entra_identity.py:1`).
- **Proposal:**
  - [ ] Match the full UPN only, against an allow-list of tenant domains; drop the local-part match.
  - [ ] Reject guest accounts (request the optional `acct` claim, or equivalent).
  - [ ] Default the switch off in production; require an explicit opt-in.
  - [ ] Preferred end state: URS sync (or an operator import) supplies the Entra object ID, so binding
    never relies on a name.
  - [ ] Emit an audit event for every automatic bind.

#### H2. No absolute session lifetime; Entra offboarding is not propagated

- **Evidence:** every rotation issues a new token with a fresh 7-day expiry (`tokens.py:55`,
  `base.py:368`). Nothing re-checks with Entra after login. A user disabled in Entra keeps access until URS
  sync deactivates the local account.
- **Proposal:**
  - [ ] Carry the original login time as a claim through rotation and reject refresh beyond an absolute
    limit (for example 12–24 hours) and an idle limit.
  - [ ] On expiry, force re-authentication through Entra.
  - [ ] Define and document the maximum delay between Entra offboarding and loss of access.

#### H3. Missing environment variable falls back to development settings

- **Evidence:** `config/asgi.py:11`, `config/celery_app.py:5` and `manage.py:13` default
  `DJANGO_SETTINGS_MODULE` to `config.settings.local`. That module has debug on (`local.py:6`), a placeholder
  secret key (`local.py:7-10`), open CORS (`local.py:66`), and password/LDAP login. Open self-registration is
  on by default in base settings (`base.py:320`). The Entra check returns early when SSO-only is off
  (`checks.py:12`), so nothing fails.
- **Proposal:**
  - [ ] Remove the default in `asgi.py` and `celery_app.py` (fail to start), or default to production.
  - [ ] Add a deploy check that fails on `DEBUG=True` or the placeholder secret key outside local runs.
  - [ ] Default `ACCOUNT_ALLOW_REGISTRATION` to off in base settings.

#### H4. Auth rate limits are per IP and likely spoofable

- **Evidence:** throttles use `ScopedRateThrottle` keyed by client address; `NUM_PROXIES` is not set in any
  settings module. DRF then keys on the whole `X-Forwarded-For` value, which the client controls.
  *Not verified:* the reverse-proxy configuration.
- **Proposal:**
  - [ ] Set `NUM_PROXIES` to the real proxy depth and add a test.
  - [ ] Add a per-username throttle on the non-production password login path.

#### H5. URS sync, the source of roles and account activation, defaults to unverified TLS

- **Evidence:** `URS_API_VERIFY_SSL` defaults to `False` (`base.py:254`) and is passed to the HTTP call
  (`urs_sync/sync_group/service.py:47`). URS data decides group membership, Labs roles, account creation and
  activation. Anyone able to intercept that connection can grant roles. This chains with H1: a forged member
  list creates a stub account that the attacker's Entra login then binds to.
- **Proposal:**
  - [ ] Default to verified TLS with a configured CA bundle; make disabling it a failing production check.

### Medium

#### M1. Refresh-token reuse is not treated as theft

- **Evidence:** replaying a rotated token returns a plain 401 (`refresh_token/api.py:47-48`).
- **Proposal:** [ ] add a token-family identifier, revoke the whole family on reuse, log a security event.

#### M2. Old refresh tokens revive when an account or binding is restored

- **Evidence:** deactivation and unlinking block refresh through live checks (`tokens.py:28-53`) but do not
  blacklist outstanding tokens (`lifecycle/application.py`). Reactivating the user, or re-binding the same
  object ID, within 7 days makes the old tokens valid again.
- **Proposal:** [ ] blacklist a user's outstanding tokens in `set_user_active(False)`, unlink and replace.

#### M3. Refresh cookie is sent on every API request

- **Evidence:** cookie path is `/api` (`cookies.py:13`), `SameSite=Lax`.
- **Proposal:** [ ] move auth routes under `/api/auth/`, scope the cookie to that path, use
  `SameSite=Strict` and a `__Secure-` name prefix. Contract change; regenerate OpenAPI.

#### M4. No dedicated way to obtain a CSRF token

- **Evidence:** the CSRF cookie is HttpOnly (`base.py:218`); the token is only returned by the challenge
  endpoint (`aad_login/api.py:35`) and by staff login (`:96`). After a page reload the client must call the
  challenge endpoint, which writes a database row each time.
- **Proposal:** [ ] add a small read-only CSRF endpoint; keep the challenge endpoint for login only.

#### M5. Challenge and token tables grow without cleanup

- **Evidence:** `purge_entra_challenges` exists only as a manual command; `flushexpiredtokens` is not
  scheduled anywhere. The challenge endpoint is unauthenticated and writes a row per call.
- **Proposal:** [ ] schedule both as periodic tasks and document them next to the other beat schedules.

#### M6. ID-token validation gaps

- **Evidence:** `aad_login/service.py:44-51` checks signature, audience, issuer, tenant and nonce but not
  `azp`/`ver`, and applies no MFA requirement to staff or superusers. An unknown `kid` triggers an outbound
  key fetch from an unauthenticated endpoint. Tenant and client IDs have hard-coded defaults
  (`base.py:100-105`).
- **Proposal:**
  - [ ] Validate `ver` and `azp` where present.
  - [ ] Require an MFA indicator (`amr`, or a Conditional Access authentication context) for privileged users.
  - [ ] Rate-limit or cache negative key lookups.
  - [ ] Require tenant, audience and key URL explicitly in production.

#### M7. Key-server outage is reported as an invalid token

- **Evidence:** a JWKS connection failure is mapped to 401 `invalid_sso_token`
  (`aad_login/service.py:58-60`, `aad_login/api.py:86-91`).
- **Proposal:** [ ] return 503 with `Retry-After`, matching the cache-outage path in `auth/api.py:25-38`.

#### M8. Staff admin session outlives the identity binding

- **Evidence:** staff get a Django session at login (`aad_login/api.py:94-96`) with the default two-week age;
  `EntraSessionBackend` (`backends.py`) inherits `get_user` and checks only `is_active`. Unlinking an
  identity leaves the admin session alive.
- **Proposal:** [ ] set a short `SESSION_COOKIE_AGE`, and re-check the binding in the backend's `get_user`.

#### M9. WebSocket token in the query string, no re-validation

- **Evidence:** `core/websocket/middleware.py:36-38` reads `?token=`, which reaches access logs. No check
  after connect was found, so a socket survives token expiry, logout and deactivation.
- **Proposal:** [ ] use a short-lived single-use ticket or first-message authentication; close sockets when
  the token expires or the user is deactivated.

#### M10. `send-otp` is not an authentication factor

- **Evidence:** the caller supplies the code and the server never verifies it
  (`send_otp/serializer.py`, `send_otp/service.py:15-32`). Any authenticated user or API-key holder can send
  arbitrary text to any mailbox in the corporate domain (`send_otp/api.py:17`). The spec calls this
  "multi-factor OTP delivery".
- **Proposal:** [ ] remove it from the auth feature, or redesign with server-generated, hashed, expiring,
  attempt-limited codes and a verify endpoint.

#### M11. API keys are a second, identity-less authentication path

- **Evidence:** `HasAPIKey | IsAuthenticated` is the default on shared view bases
  (`core/common/api/command_views.py:37`, `core/common/api/options.py:97`) and on `GetMeView`
  (`profile/get_me/api.py:17`). A key bypasses Entra, carries no user, and cannot be object-scoped
  (AGENTS.md rule 5). `GetMeView` then looks up `request.user.pk` for an anonymous user (`:27`).
- **Proposal:** [ ] inventory which callers need keys, restrict keys to those endpoints, and bind each key
  to a service identity with explicit scope. Remove the key path from user-centric endpoints.

#### M12. Token signing shares Django's secret key

- **Evidence:** `SIMPLE_JWT` sets no `SIGNING_KEY`, `ISSUER` or `AUDIENCE` (`base.py:366-373`).
- **Proposal:** [ ] dedicated signing key with a rotation procedure; set issuer and audience per
  environment so tokens from one environment are rejected by another.

#### M13. Thin audit trail

- **Evidence:** failures log one generic line with no reason category or source
  (`aad_login/service.py:59`, `:62`); `UPDATE_LAST_LOGIN` is off (`base.py:371`), so dormant accounts cannot
  be found.
- **Proposal:** [ ] structured security events for login success/failure (with reason), refresh reuse,
  logout, automatic and operator binding; record last login.

### Low

- [ ] **L1. Spec drift.** `auth/docs/spec.md` disagrees with the code: identity field names and `CASCADE`
  vs `PROTECT` (lines 28-33); a soft-delete field that does not exist (line 22); access lifetime 15–60 min
  vs 10 (line 43); response shapes (lines 60-65); "Upsert User" although login never creates users
  (line 91). Rewrite the spec from the code once the decisions above are made.
- [ ] **L2. Stale duplicate view.** `admin_login/__init__.py:10` holds a copy of the admin login view without
  the SSO-only redirect; `login/__init__.py` and siblings duplicate their `urls.py`.
- [ ] **L3. Logout.** No throttle, and a leftover nested function (`logout/api.py:36-42`).
- [ ] **L4. Non-production LDAP path.** Hard-coded mail domain (`login/ldap_service.py:77`); response timing
  reveals whether a username exists (`login/service.py:33-40`).
- [ ] **L5. Misnamed tests.** `test_refresh_token.py:27` and `:36` are named `..._returns_400` and assert 401.
- [ ] **L6. Legacy hasher.** `PBKDF2SHA1PasswordHasher` is still accepted (`base.py:137`).
- [ ] **L7. Unused surface in production.** allauth apps and middleware stay installed although its routes
  are unmounted.
- [ ] **L8. Browser hardening.** No Content-Security-Policy is configured; the access token lives in page
  memory, so script injection exposes it.
- [ ] **L9. CORS with credentials.** `CORS_ALLOW_CREDENTIALS` is on and origins come from environment
  variables, including regexes (`production.py:55`). Add a check that rejects wildcard-like patterns.

## Longer-term option

Move to a backend-driven authorization-code flow with PKCE (backend as confidential client). Microsoft
tokens never reach the browser, and the backend can confirm with Entra on refresh that the account is
still valid, which resolves H2 structurally. Cost: a client secret or certificate to manage, a redirect
endpoint, and a frontend change. Decide before investing in H2's claim-based limit.

## Suggested order

1. H3, H4, H5 — configuration only, no contract change.
2. H1 — decide the binding source of truth.
3. H2 with M1 and M2 — one change to the refresh-token model (likely a migration).
4. M3 and M4 — one route/cookie contract change while there are no production clients.
5. Remaining medium items, then L1 last so the spec is rewritten once.

## Process for each item

- [ ] T2 workflow per `AGENTS.md`: design note, security and QA review, independent review, owner approval.
- [ ] Tests for each acceptance criterion; quality gates from `docs/ai-team/quality-gates.md`.
- [ ] Regenerate OpenAPI and update `auth/docs/spec.md` in the same change when the contract moves.
- [ ] When an item is approved and implemented, fold its rule into the feature spec and remove it here.

## Open questions for the owner

1. Is the frontend served from the same site as the API? M3's `SameSite=Strict` assumes yes.
2. What is the reverse-proxy chain in production (H4)?
3. Can URS provide Entra object IDs (H1)?
4. Which callers use API keys today (M10, M11)?
5. Is this path (`docs/proposals/`) the right home for this document? It was chosen per
   `docs/ai-team/documentation-map.md`, "Proposal not yet approved".
