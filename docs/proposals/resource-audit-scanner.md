# Design: Resource audit scanner (desktop tool)

- Tier: T2 · Status: Draft, not approved, nothing implemented · Date: 2026-11-12
- Scope: `core/labs/features/resource_audit`, a new audit-catalog read, `core/users/features/auth`
  (new authentication class), changes to the existing frontend Entra app registration, frontend label
  printing, and the tool guide `docs/proposals/resource-audit-scanner-tool.md`.
- Basis: read-only review of the code at commit `f8af818`. No code was changed and no checks were run.

## Problem and acceptance criteria

Auditors check lab resources with a desktop tool (an `.exe`), not with the web frontend. The tool downloads
the resources, scans a QR tag, shows the resource, and sends one audit result per resource to the backend.

Owner decisions (2026-11-12):
- New QR tags are printed now; old SKU-only QR tags are replaced (development phase).
- The QR holds only the resource `uid` (plain UUID text, no host or URL). SKU, name and serial number are
  printed as text next to it.
- Every resource type is tagged and audited: equipment, bench, station, room, license.
- A license gets its **own** tag (license `uid`) attached to its carrier hardware (option A). No carrier
  model is added. Licenses without hardware are audited on the web, not in the tool.
- The tool does not detect missing items (no audit sessions or reconciliation); it records per-resource results.

Acceptance criteria:
- AC1 An auditor signs in to the tool with Microsoft; the backend records that user as `auditor`.
- AC2 The tool downloads the auditable resources of all five types once, then only the changes.
- AC3 Scanning a tag resolves to exactly one resource offline, by `uid`.
- AC4 The tool records PASS / FAIL / NOT_ASSESSED with remarks and the time of the check.
- AC5 Sending the same result twice (retry after a network failure) creates one audit.
- AC6 Users without the Labs coordinator or admin role cannot read the catalog or write audits.
- AC7 License keys (`License.identifier`) never leave the server through these paths.

## Current state (from repository evidence)

- Audits can be recorded for all five types: `resolve_resource` covers equipment, bench, license, room and
  station (`core/labs/features/resource_audit/queries/selectors.py:60-130`).
- `POST /api/labs/resources/uid/{uid}/audits` exists (`resource_audit/api/urls.py:20-24`,
  `ResourceAuditByUidView`), body `result`, `remarks`, `audited_at`
  (`resource_audit/api/serializers.py:71-87`).
- `ResourceAudit.auditor` is a required FK to the user (`core/labs/models/auditing/resource_audit.py:45-49`);
  `record_resource_audit` refuses a caller without an authenticated user
  (`resource_audit/application/commands.py:117-118`). API-key callers have no user
  (`core/common/api/command_views.py:46-48`), so an API key can read but not record audits.
- Labs endpoints allow coordinators and admins, or an API key (`core/labs/features/base/access.py:22-24`).
- Production authenticates only Lab Mango JWTs issued after Entra login
  (`config/settings/production.py:18`, `core/users/features/auth/authentication.py:12-28`). Getting one
  needs the browser flow of `POST /api/aad-login` (CSRF cookie, nonce secret, refresh cookie;
  `core/users/features/auth/docs/spec.md` §3.1-3.2), which a desktop tool cannot use cleanly.
- `uid` is unique per table and not editable (`core/labs/models/resource/base/resource.py:57`); `sku` is unique
  only per table among non-deleted rows (`resource.py:180-186`).
- `License.identifier` holds the license key and is secret (`core/labs/models/resource/license/license.py:106-110`).
- No audit write has idempotency today; the write-safety rule marks `Idempotency-Key` as "no compliant
  implementation yet" (`.github/instructions/write-safety.instructions.md:48`).
- No QR or label code exists in the repository.

Drift found (report only, not fixed by this design):
- `resource_audit/docs/spec.md` §3 lists `/api/labs/resource-audits...` routes that do not exist; the real routes
  are in `resource_audit/api/urls.py`.
- `TypedResourceAuditListCreateView.handle_post` treats an all-digit identifier as a primary key
  (`resource_audit/api/views.py`, `"id" if resource_id.isdigit() else "sku"`), so a numeric SKU audits the
  wrong row or returns 404.
- SKU lookups for room and station also match `name` (`selectors.py:100`, `:111-112`).
- `AuditBySkuRequestSerializer` is unused (`resource_audit/api/serializers.py:108`).

The tool avoids all four by addressing resources by `uid` only.

## Proposed behavior and invariants

Tool workflow:
1. Sign in with Microsoft. The tool is written in Python and uses MSAL for Python as a public client
   (Windows broker or system browser). No secret in the tool.
2. Download the audit catalog; later runs request only rows changed since the last cursor.
3. Scan a QR: the content is the `uid` itself; the tool checks it is a valid UUID. Fallback when
   the tag is damaged: type the SKU and pick from the local matches (type shown).
4. Look up the `uid` in the local catalog; not found → "Unknown tag". Online, fetch fresh detail.
5. Record the result into a local outbox (SQLite) with a tool-generated `client_audit_id` (UUID) and the
   time of the check.
6. A background sender posts outbox rows one by one; a row is removed only after `201` or a replay.

Invariants:
- I1 An audit always has a real user as `auditor` (unchanged).
- I2 One `(auditor, Idempotency-Key)` creates at most one audit (database constraint, see below).
- I3 Audit result, lifecycle state, condition and booking/assignment status stay separate (AGENTS.md rule 2).
  A FAIL result never changes `lifecycle_state` or `condition`; marking a unit lost stays the manual command
  in `core/labs/features/equipment/application/change_state.py`.
- I4 The catalog never includes `License.identifier`.

## Module ownership and allowed dependencies

| Part | Owner module | Depends on |
|---|---|---|
| Audit catalog read | `core/labs/features/resource_audit/queries` (new selector) and `api` | Labs resource models through the feature's existing model imports; other features only via `public.py` |
| Idempotent record | `core/labs/features/resource_audit/application/commands.py` | none new |
| Entra access-token authentication | `core/users/features/auth` (new `authentication` class) | `core.users.models.EntraIdentity` |
| Label printing | frontend | the catalog endpoint |

`core.common` gains no business imports.

## API contract (endpoints, errors, breaking?)

| # | Endpoint | Status |
|---|---|---|
| 1 | `GET /api/labs/audit-catalog` | New |
| 2 | `GET /api/labs/equipment/uid/{uid}` | Exists, unchanged |
| 3 | `POST /api/labs/resources/uid/{uid}/audits` | Exists; adds `Idempotency-Key` |

**1. `GET /api/labs/audit-catalog`**
- Query: `changed_since` (ISO 8601, optional), `cursor` (opaque, optional), `page_size` (default 500, max 1000).
- Keyset order `(updated_at, resource_type, id)`; response `results`, `next_cursor`, `server_time`. The tool
  stores `server_time` as its next `changed_since`.
- Item: `uid`, `resource_type` (`equipment|bench|station|room|license`), `sku`, `name`, `serial_number`
  (equipment only, else empty), `location` (id and name, when the type has one), `lifecycle_state` or the
  type's status, `condition` (equipment only), `updated_at`, `deleted` (true for soft-deleted or retired rows
  since `changed_since`, so the tool removes them).
- Never: `License.identifier`, prices, user data beyond what the existing detail endpoints show.
- Errors: `400 invalid_query`, `401`, `403`.

**2. Detail.** Unchanged. Bench, station, room and license have no `uid` detail route; the tool shows the
catalog row for them. Adding those routes is out of scope.

**3. Record audit.** Body unchanged. New request header `Idempotency-Key` (required for this tool, optional for
existing callers so the web frontend is not broken). Per RW-6 and the golden example
(`docs/api/response-golden-examples.md:212`):
- first request → `201` with the audit;
- same key and same body → `201`, same body, header `Idempotency-Replayed: true`;
- same key, different body → `422 idempotency_key_reuse`;
- same key while the first is still running → `409 request_in_progress`.
- Existing errors stay: `401`, `403`, `404`, `422`.

Breaking: no. Endpoint 1 is additive; the header on 3 is optional. The new authentication class is added
next to the existing one.

## Data model, constraints, concurrency

New columns on `ResourceAudit` (migration, additive, nullable):
- `idempotency_key` `CharField(128)`, null.
- `request_hash` `CharField(64)`, null (SHA-256 of the canonical body plus `uid`).
- Constraint `resource_audit_idempotency_uniq`: unique `(auditor, idempotency_key)` where
  `idempotency_key IS NOT NULL`.

The key is scoped to the user and this one endpoint. A separate idempotency table is not needed while
only this endpoint uses keys.

| Write path | Race | Guard | Idempotency | Concurrency test |
|---|---|---|---|---|
| Record audit by uid | Same result sent twice in parallel (retry) | `resource_audit_idempotency_uniq`; loser catches `IntegrityError` and returns the stored row | `Idempotency-Key` + `request_hash` | Two threads, same key → one row, both `201`, one replayed |
| Record audit by uid | Two auditors check the same resource | none needed: separate audits are valid history | different keys → two rows | not needed |

## Read paths and query budget

| Endpoint | Query function | Joins / annotations | Budget | Page cap |
|---|---|---|---|---|
| `GET /api/labs/audit-catalog` | new `list_audit_catalog` selector | one query per resource type with `select_related` for location; merged in keyset order | ≤ 6 queries per page | 1000 |

Indexes on `(updated_at, id)` per resource table are needed if they do not exist (not verified).

## Authorization and threat notes

- New `EntraAccessTokenAuthentication`: accepts Microsoft **access tokens** issued for the scope exposed on
  the existing frontend app registration (`AAD_AUDIENCE`, `config/settings/base.py:100`). Checks RS256
  signature via JWKS, issuer = the configured tenant, audience = `api://<client-id>` (or the client ID),
  `scp` contains `LabMango.Audit`, token not expired. Maps `tid` + `oid` to `EntraIdentity` → user; no
  identity → `401`. No user is created from a token. Pattern follows `core/routing/api/authentication.py`
  for JWKS handling, but for delegated user tokens.
- Enabled on endpoints 1-3 only, not globally, until the owner decides otherwise.
- Authorization stays the Labs policy: coordinator or admin. API keys keep their current access; they still
  cannot record audits.
- The tool is a public client: no client secret, PKCE, tokens cached encrypted by Windows (DPAPI or broker).
- Local data: the catalog and outbox are internal data. The SQLite file is encrypted (or stored in a
  DPAPI-protected location) and can be wiped from the tool.
- A QR tag is an identifier, not a credential. A phone camera shows only the UUID text; it opens nothing.

## Async/integration behavior

No Celery work. The tool's outbox is client-side. External integration: Microsoft Entra (token issuance and
JWKS). JWKS unavailable → `503`, matching the routing sync behavior.

## Migration, rollout, rollback

1. Entra, on the **existing** frontend app registration (no new app). Owner action:
   - Authentication: add platform "Mobile and desktop applications" with redirect URIs `http://localhost`
     and `ms-appx-web://microsoft.aad.brokerplugin/<client-id>` (Windows broker).
   - Expose an API: Application ID URI `api://<client-id>`, scope `LabMango.Audit`.
   - Optional: "Allow public client flows" = Yes, only if device-code sign-in is used.
2. Backend: migration for the two columns and the constraint (additive); authentication class; catalog
   endpoint; idempotency in `record_resource_audit`; regenerated OpenAPI; updated `resource_audit/docs/spec.md`.
3. Frontend: label printing page (QR with the plain `uid`, plus SKU, name, serial as text). The QR library
   is a new frontend dependency (AGENTS.md rule 7: purpose, alternative, owner needed).
4. Print and attach new tags for all five types; license tags go on the carrier hardware.
5. Tool release.

Rollback: disable the new authentication class in settings; the columns are nullable and can stay.

## Observability

- Log each audit record with `audit_id`, `uid`, `resource_type`, `auditor_id`, replayed yes/no. Never log the
  token or license key.
- Log authentication failures by reason category (expired, audience, scope, unknown identity) without the token.

## Test plan (criterion → test)

| Criterion | Test |
|---|---|
| AC1 | Valid access token with scope → audit has that user as `auditor`; missing scope → 403; unknown `oid` → 401; wrong audience or tenant → 401 |
| AC2 | Catalog returns all five types; `changed_since` returns only changed rows; deleted rows returned with `deleted: true`; cursor paging stable |
| AC3 | Each catalog row has a unique `uid`; tag parsing accepts a UUID and rejects other text (tool-side test) |
| AC4 | Record by uid for each of the five types |
| AC5 | Same key + body → one row, replay header; different body → 422; parallel same key → one row |
| AC6 | Plain Labs user and no-role user → 403 on endpoints 1 and 3 |
| AC7 | Catalog and responses never contain `identifier` for licenses |
| Query budget | `django_assert_max_num_queries` on a catalog page with all types |

## Alternatives considered

- **API key for the tool.** Already supported for reads, but there is no user for `auditor`, and a key in a
  distributed `.exe` can be extracted. Rejected.
- **Reuse `/api/aad-login` from the tool.** Needs CSRF cookie, nonce secret and refresh cookie built for a
  browser. Rejected as fragile.
- **QR holds the SKU.** SKU is not unique across types, can be edited and reused. Rejected for new tags.
- **QR holds a URL (`https://<host>/t/<uid>`).** Lets a phone open the resource page, but ties every printed
  tag to a domain. Rejected by the owner (2026-11-12) in favor of the plain `uid`.
- **Model license carriers as equipment (option B).** Handles several licenses per carrier and audits the
  carrier itself. The owner chose option A (one tag per license); B stays possible later.
- **Audit sessions to detect missing items.** Out of scope by owner decision.
- **Batch push endpoint.** Not needed now; one-by-one with idempotency covers retries.
- **Separate app registrations for the tool and the API.** Microsoft's general recommendation, but one
  registration as both client and API is allowed and keeps one client ID. Decided: reuse the frontend
  registration (2026-11-12); splitting later changes only settings and the tool's client ID.
- **Tool reuses the frontend's login.** The frontend's Lab Mango tokens live in the browser (memory and an
  HttpOnly cookie) and cannot be read by another program; a hand-off would reinvent OAuth. Rejected.

## Open questions / decisions needed from the owner

Decided (2026-11-12):
1. Tag content: the plain `uid` only, no host or URL. Tags never depend on a domain, so no reprint when hosts
   change. Trade-off accepted: a phone camera scan shows the UUID text and opens no page; there is no
   frontend `/t/<uid>` route.
2. Owners: the repository owner (full stack) owns the backend, the frontend and the QR dependency. Creating
   the Entra changes on the existing app registration needs rights in the Microsoft tenant; if the owner
   does not hold them, a
   tenant admin creates or approves them (not verified).
3. `EntraAccessTokenAuthentication` is used for the scanner endpoints first and later also for the web
   frontend login. The frontend switch is a separate T2 change with its own design.
4. The four drift items are fixed as separate tasks, not in this change.
