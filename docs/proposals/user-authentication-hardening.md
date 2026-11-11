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
- **Constraint (owner, 2026-11-10/11):** URS provides usernames only, and Graph access for linking before
  first login is not available. First-login binding by username is therefore **the** linking path
  (reached through the Router's department chooser, H7), and the safeguards below are mandatory, not
  optional. The owner must accept the residual risk in writing.
- **Proposal:**
  - [ ] Accept the local-part match only when the UPN domain is on an explicit allow-list of corporate
    domains (setting, empty by default, startup check in production). Reject every other domain.
  - [ ] Reject guest accounts (request the optional `acct` claim, or equivalent).
  - [ ] Bind only accounts that never had a binding before; if a previously bound account is unlinked,
    require the operator command to bind it again (no automatic re-bind).
  - [ ] Emit an audit event for every automatic bind, and alert on binds of accounts older than a
    threshold (a long-dormant account claimed by a new person is the risky case).
  - [ ] Bind only on the backend the user chose, and only to a URS-provisioned account there (already the
    case: login never creates users).
  - [ ] Keep `ENTRA_BIND_BY_USERNAME` as the kill switch and document when to turn it off.
  - [ ] *Investigate with the tenant administrator (not verified):* whether the ID token can carry an
    on-premises identifier (optional claim `onprem_sid`, or `sAMAccountName` through a claims-mapping
    policy). Matching that exact value to the URS username would be stronger than `preferred_username`.

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
- **Deployment (owner, 2026-11-11):** the proxy tier belongs to the separate `labmango-router`
  repository and is out of scope here. The backend must not hard-code assumptions about it.
- **Proposal:**
  - [ ] Make the trusted proxy depth an explicit, required production setting (`NUM_PROXIES` from the
    environment), with a startup check that fails when it is unset.
  - [ ] Record in the router contract which forwarded headers the backend trusts and how many hops add them.
  - [ ] Add a test that two requests with different spoofed `X-Forwarded-For` prefixes share one counter.
  - [ ] Add a per-username throttle on the non-production password login path.

#### H5. URS sync, the source of roles and account activation, defaults to unverified TLS

- **Evidence:** `URS_API_VERIFY_SSL` defaults to `False` (`base.py:254`) and is passed to the HTTP call
  (`urs_sync/sync_group/service.py:47`). URS data decides group membership, Labs roles, account creation and
  activation. Anyone able to intercept that connection can grant roles. This chains with H1: a forged member
  list creates a stub account that the attacker's Entra login then binds to.
- **Proposal:**
  - [ ] Default to verified TLS with a configured CA bundle; make disabling it a failing production check.

### Multi-backend deployment (added 2026-11-11)

Context from `docs/agent-platform/routing-sync.md` and ADR 004: one backend per department behind one
shared frontend; the Router (separate repository) maps `entra:<tid>:<oid>` to a `backend_id` from claims the
backends publish; requests reach a backend through a public prefix such as `/api/dept_a/`, which the
proxy strips (`routing-sync.md:74`). The current authentication code was written for a single backend.

#### H6. Auth cookies collide and leak across department backends

- **Evidence:** the backend sets cookies with path `/api` and fixed names: `refresh_token`
  (`cookies.py:7-13`, `base.py:361`), `entra_login_challenge` (`aad_login/api.py:36-44`, `base.py:108`),
  and Django's default `sessionid` and `csrftoken`. Because the public path is `/api/<backend_id>/...`,
  the browser sends these cookies to **every** department backend on the shared host, and a login on one
  backend overwrites another backend's cookies of the same name.
- **Failure cases:** a refresh token issued by `dept_a` is sent to `dept_b`, a separate trust domain; a
  user or operator who uses two departments (testers, admins) is silently logged out of one; a challenge
  cookie from one backend breaks a login on another.
- **Proposal:**
  - [ ] Add a required setting for the backend's public prefix (for example `PUBLIC_PATH_PREFIX`), with a
    startup check in production.
  - [ ] Scope every auth cookie path to that prefix: refresh and challenge cookies to `<prefix>/auth/`,
    `SESSION_COOKIE_PATH` and `CSRF_COOKIE_PATH` to `<prefix>/`.
  - [ ] Include `BACKEND_ID` in every cookie name (`SESSION_COOKIE_NAME`, `CSRF_COOKIE_NAME`, refresh,
    challenge) so two backends can never overwrite each other.
  - [ ] Test that a response sets only prefixed paths and backend-specific names.
  - [ ] Do not rely on the proxy rewriting cookie paths; the backend must emit correct cookies itself.

#### H7. Target login flow through the Router, and what the backend must change

- **Confirmed (owner, 2026-11-11):**
  - The frontend signs the user in with Entra, asks the Router service for the user's prefix, then sends
    every request to that prefix; Nginx in the Router repository strips it and forwards to the backend.
  - When a user is known on several backends, the user chooses.
  - No Microsoft Graph access for linking users before their first login.
  - Whether the frontend can do a second, silent Entra sign-in is unknown.
- **Problems with the current backend code in this flow:**
  - **Nonce order.** The backend accepts only an ID token whose `nonce` matches a challenge it issued
    (`aad_login/service.py:110-121`), but the token was obtained before the frontend knew which backend to
    ask. Every login fails.
  - **CSRF.** Without the challenge call, the browser has no CSRF cookie for that backend, and
    `aad-login` returns `403` (`aad_login/api.py:60`).
  - **First login.** The Router has no claim for an unbound user, so it returns no prefix
    (`routing-sync.md` CNS-6).
  - **Cookies.** Nginx strips the prefix, so cookies set for `/api` reach every department (H6).
- **Target flow:**
  1. Frontend creates a random secret `S` and keeps it in memory (or `sessionStorage` for the redirect).
  2. Frontend signs in with Entra, passing `nonce = SHA-256(S)` (base64url) in the sign-in request.
  3. Frontend sends **only the ID token** to the Router service and gets back: one prefix, several prefixes
     (user chooses), or none (first login: user chooses a department from the Router's list).
  4. Frontend calls `GET <prefix>/auth/csrf` (M4), then `POST <prefix>/auth/aad-login` with the ID token
     and `S`, plus the CSRF header.
  5. Backend validates the token itself (signature, audience, issuer, tenant, expiry, issued within the
     last few minutes), checks `SHA-256(S) == nonce`, and records the nonce as used (unique constraint) so
     the same token cannot be used twice on this backend.
  6. Backend finds the bound identity, or binds by username with H1's safeguards, publishes the claim,
     and returns the access token with prefix-scoped, backend-named cookies (H6).
  - One Entra sign-in, no backend call before sign-in, no silent second sign-in.
  - The Router sees the token but not `S`, so it cannot replay the login; neither can anyone who copies the
    token from a log.
- **Backend changes (proposal):**
  - [ ] Replace the issued challenge (`EntraLoginChallenge`, `aad-login/challenge`, challenge cookie) with
    the secret/nonce check and a consumed-nonce record with expiry. Migration, API contract change.
  - [ ] Add the CSRF endpoint (M4); keep CSRF on `aad-login`, refresh and logout.
  - [ ] Bound token age (`iat`) on `aad-login`, so the consumed-nonce table stays small (M5 purges it).
  - [ ] Prefix-aware cookie paths and backend-specific cookie names (H6); one trusted forwarded hop (H4).
  - [ ] Keep validating the ID token on the backend even though the Router did: routing is not
    authorization (`routing-sync.md` P1).
  - [ ] End-to-end test through a prefix: resolve → csrf → login → refresh → logout, and switching between
    two backends in one browser.
- **Router-repository changes (not verified, outside this repository):** return a department list for
  zero or several claims (M14); accept the ID token for resolve without needing the backend's nonce.
- **Trade-off:** `S` lives in page memory, so script injection on the page could steal it together with the
  token. The current HttpOnly challenge cookie resists that slightly better, but needs a backend call
  before sign-in, which this flow does not have. L8 (Content-Security-Policy) reduces the risk.

#### M14. Multi-department users conflict with the Router's single-owner rule

- **Evidence:** the routing spec treats two claims for one key as a conflict that routes nowhere, and says
  a user must not exist in two departments (`routing-sync.md` CNS-6). The owner confirmed on 2026-11-11
  that users can belong to several departments and that **the user chooses** which one to use.
- **Proposal:**
  - [ ] Revise CNS-6 in the routing spec (Router repository change): several claims return the list of
    departments for the user to choose; zero claims return the department list for first login (H7);
    fail closed only for invalid claims.
  - [ ] Each backend keeps its own binding and claim for the same Entra key; nothing changes in this
    backend's data model. H6 (per-backend cookies) is mandatory for switching to work.

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
- **Deployment:** one shared frontend host for all department backends (`routing-sync.md` C1), so the
  app's own calls are same-site and `Strict` does not break them.
- **Proposal:** [ ] move auth routes under `<prefix>/auth/`, scope the cookie to that path (see H6 for the
  prefix), use `SameSite=Strict` and a `__Secure-` name prefix. Contract change; regenerate OpenAPI.

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
  "multi-factor OTP delivery". Not mounted in production; risk is limited to non-production environments.
- **Proposal:** [ ] remove it from the auth feature, or redesign with server-generated, hashed, expiring,
  attempt-limited codes and a verify endpoint.

#### M11. API keys are a second, identity-less authentication path

- **Evidence:** `HasAPIKey | IsAuthenticated` is the default on shared view bases
  (`core/common/api/command_views.py:37`, `core/common/api/options.py:97`) and on `GetMeView`
  (`profile/get_me/api.py:17`). A key bypasses Entra, carries no user, and cannot be object-scoped
  (AGENTS.md rule 5). `GetMeView` then looks up `request.user.pk` for an anonymous user (`:27`).
- **Usage (owner, 2026-11-10):** API keys are used only for API testing.
- **Proposal:**
  - [ ] Disable the API-key path in production: make `HasAPIKey` a no-op (always deny) when
    `ENTRA_SSO_ONLY` is on, or remove it from the production permission set, and add a startup check.
  - [ ] Remove it from user-centric endpoints such as `GetMeView`, where a key has no user to return.
  - [ ] For testing, prefer real test users with tokens over keys, so tests exercise the same
    authorization path as production.

#### M12. Token signing shares Django's secret key

- **Evidence:** `SIMPLE_JWT` sets no `SIGNING_KEY`, `ISSUER` or `AUDIENCE` (`base.py:366-373`).
- **Multi-backend impact:** the owner confirmed (2026-11-11) that each department backend runs in its own
  container with its own environment, so secret keys are expected to differ; nothing enforces it. If two
  environments ever share a key (for example a copied `.env`), a token from `dept_a` passes the signature
  check on `dept_b`. In production `EntraJWTAuthentication` then requires
  a local binding with the same tenant/object ID for that user ID (`authentication.py:22-27`), which stops
  a different person but not the same person present on two backends. Non-production
  `JWTAuthentication` has no such check.
- **Proposal:**
  - [ ] Dedicated signing key per backend, with a rotation procedure.
  - [ ] Set `ISSUER` and `AUDIENCE` from `BACKEND_ID` (defense in depth against a copied environment) (`base.py:115`) and environment, so a token issued by
    one backend or environment is rejected by every other one; startup check that they are set.

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
  variables, including regexes (`production.py:55`). Because all backends sit behind one shared frontend host,
  production needs no CORS: leave the allowed origins empty, turn credentials off, and add a
  startup check that fails if any origin or regex is configured. Set `CSRF_TRUSTED_ORIGINS` to that one
  origin only.

## Longer-term option

Move to a backend-driven authorization-code flow with PKCE (backend as confidential client). Microsoft
tokens never reach the browser, and the backend can confirm with Entra on refresh that the account is
still valid, which resolves H2 structurally. Cost: a client secret or certificate to manage, a redirect
endpoint, and a frontend change. Decide before investing in H2's claim-based limit.

## Suggested order

1. H7 and M14 — agree the target login flow and the chooser with the Router repository and frontend.
2. H3, H4, H5 — configuration only, no contract change.
3. H6 with M3 and M4 — one route/cookie contract change while there are no production clients.
4. H7 backend changes together with H1's safeguards (one change to the login endpoint and its migration).
5. H2 with M1, M2 and M12 — one change to the token model (likely a migration).
6. Remaining medium items, then L1 last so the spec is rewritten once.

## Process for each item

- [ ] T2 workflow per `AGENTS.md`: design note, security and QA review, independent review, owner approval.
- [ ] Tests for each acceptance criterion; quality gates from `docs/ai-team/quality-gates.md`.
- [ ] Regenerate OpenAPI and update `auth/docs/spec.md` in the same change when the contract moves.
- [ ] When an item is approved and implemented, fold its rule into the feature spec and remove it here.

## Owner decisions

| Question | Answer | Effect |
| --- | --- | --- |
| Reverse-proxy chain | Out of scope: owned by the separate `labmango-router` repository (2026-11-11) | H4: proxy depth becomes a required setting plus a router-contract entry |
| Can URS provide Entra object IDs | No, usernames only | H1: keep name binding, add the safeguards listed |
| Who uses API keys | API testing only | M11: disable the key path in production |
| Location of this document | `docs/proposals/` confirmed | — |
| Frontend and API addresses | Browser sees one shared host; backend URLs are not exposed | M3: `SameSite=Strict` is possible; L9: CORS can be off in production |
| Deployment topology | Multiple department backends; the router service maps users by Entra ID using the routing sync (2026-11-11) | New H6, H7, M14; M12 extended |
| How the frontend reaches a backend | Frontend asks the Router service for the user's prefix, then sends every request to that prefix; Router Nginx strips it and forwards to the backend | H7 target flow; H6 prefix-aware cookies; H4 one trusted hop |
| Graph permission for linking before first login | Not available | H1 first-login binding stays, safeguards mandatory; owner accepts residual risk |
| Silent second Entra sign-in | Unknown | H7 target flow avoids it (frontend-held secret, one sign-in) |
| Router returns a department list for zero or several matches | Yes (2026-11-11) | H7 and M14 Router side agreed; CNS-6 revision still to be written in the Router repository |
| Multi-department users | They can switch; when several backends match, the user chooses | M14: Router returns a department list; CNS-6 must change |
| Secrets per backend | Each department runs its own container and environment | M12: keys expected to differ; issuer/audience kept as defense in depth |

## Open questions for the owner

1. **Frontend nonce (H7).** Ask the frontend developer whether the Entra sign-in call can take a custom
   `nonce` value. With MSAL for browsers this is normally the `nonce` field of the login request, for example:

   ```ts
   const secret = crypto.getRandomValues(new Uint8Array(32));          // keep in memory / sessionStorage
   const digest = await crypto.subtle.digest("SHA-256", secret);
   const nonce = base64url(new Uint8Array(digest));                    // send to Entra
   await msal.loginRedirect({ scopes: ["openid", "profile"], nonce });
   // later: POST <prefix>/auth/aad-login { id_token, nonce_secret: base64url(secret) }
   ```

   *Not verified* against the MSAL version in use.
2. **Risk acceptance (H1).** First-login linking by username, with the safeguards, is acceptable — or every
   first link needs an operator's approval instead?
