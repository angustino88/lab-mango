# Agent Platform Backend Spec: LabMango per-department backend

Status: Historical draft 2.0 · superseded · retained for traceability only
Archive location: `docs/archive/agent-platform/agent-platform-backend-spec.v2.md`

> **Do not implement from this draft.** Start at the [agent-platform reading guide](../../README.md#agent-platform-start-here).
> Use the working [backend proposal](../../backend-agent-api-spec.md); routing is owned exclusively by the
> [routing-sync design](../../backend-routing-sync-spec.md). "Reviewed and hardened" in historical material does not
> establish current approval, deployment or interoperability.

### Review log (1.0 → 2.0)

| # | Finding in 1.0 | Change in 2.0 |
|---|---|---|
| R1 | Credential lifecycle and equipment routing lifecycle were mixed; revocation propagation to Edge and Gateway was left unspecified | New sync entity `agent_keys` (credentials) separate from `equipment` (ownership); revocation reaches Router and Gateway as a high-priority change (4.1, 5.1, 7) |
| R2 | Sync API could return inconsistent or unbounded data; no protection against backend restore | Routing projection table, `epoch`, `limit`/`has_more`, snapshot + catch-up paging with per-item versions, digest endpoint (4.1, 5, 7) |
| R3 | Access-token revocation relied on a per-token table and a 60 s cache, contradicting "effective on the next request" | `credential_version` in the token, cache invalidation by `LISTEN/NOTIFY`, explicit SLA of 10 s (6.2.2, 9.2); `AgentToken` table removed |
| R4 | Assertion used `agent_uid` as issuer, which breaks after a move or recovery | Assertion identifies the key by its thumbprint `kid`; the device never needs `agent_uid` to authenticate (6.3, B1) |
| R5 | Assertion `aud` was derived from the request URL, which Nginx prefix stripping makes unreliable | `aud` is compared with the configured canonical public URL (`AGENT_PUBLIC_BASE_URL`) (2, 6.3) |
| R6 | `key_storage` tier was a self-reported claim used for policy | Tier is only trusted with verified attestation; unattested keys are treated as `software` (6.1, 6.2) |
| R7 | Enrollment proof was an ad-hoc concatenation; stolen-grant race only mitigated by an optional mode | Proof is a JWS over canonical JSON; approval with fingerprint confirmation is the default for departments without attested keys; grant lockout after failed attempts (6.2) |
| R8 | Rotation swapped keys atomically, so a lost response could lock the agent out | Two-phase rotation (`next` → `active`, old `retiring`) (6.2.1) |
| R9 | Single `public_key` column per identity | `AgentKey` table with `kid`, status and attestation flag (4.1) |
| R10 | Unique constraint only for `active`; two pending agents per equipment possible | Partial unique indexes for `active` and for `pending/pending_approval` (4.1) |
| R11 | Move procedure ("associate the approved agent identity") was undefined between independent backends | Explicit key-adoption procedure with possession proof, dual approval and conflict detection (8) |
| R12 | State snapshot (`PATCH /agent/equipment/state`), inventory and metrics overlapped; concurrent user edits undefined | Ownership table, agent-owned fields read-only in the user API, monotonic `collected_at` rule (6.4.1) |
| R13 | Nonce and token tables are write-heavy | Nonce in a TTL store; no per-token rows (4.1) |
| R14 | Per-IP limits would see only the proxy address | Trusted-proxy real-IP handling required (2, 9) |
| R15 | No SLOs, no incident drills for the new paths | SLOs, alerts, chaos and restore tests added (10, 11, 13) |
| R16 | Agent booking writes were too restrictive | Owner-approved `bookings:end_time:write` permits updating only the end time of a booking belonging to the linked equipment; `bookings:complete` separately permits reporting completion (6.7) |

**Scope of this repo:** additions to the existing Django backend: sync API for the Edge, agent API (enrollment, tokens, telemetry, bookings), version counters, prefix handling.

## 0. System context (read first)

This document is **standalone**: everything needed to implement this repository is inside it, including the contracts it shares with the other repositories. The other repositories are specified in their own documents, but you do not need them to build or test this one (stubs are described in the last section).

LabMango is deployed as **one backend per department** behind **one shared frontend**. Lab equipment runs an **agent**. A **gateway** (multi-application) manages agent config and updates. An **edge** (Nginx + router) routes users and equipment to the right backend.

```
Agent ──▶ Gateway ──▶ Edge ──▶ Backends
Agent ───────────────────────▶ Backends   (data path, through the Nginx prefix)
```

| Component | Repo | Role |
|---|---|---|
| Edge (Nginx + Router) | `labmango-edge` | Owns `{entity_key} → backend_id`, public prefix routing, backend registry, user/equipment resolve |
| Gateway | `gateway` | App-agnostic control plane for agents: resolve, signed config, updates, agent auth |
| Backend (per department) | `labmango-backend` | Business data, read-only sync API, agent enrollment, agent tokens, telemetry, bookings |
| Agent | `agent` | Runs on equipment; pushes data to its backend; fetches config and updates; self-heals routing |

Dependency rules (never violate):
- Backends know nothing about the Edge, the Gateway or other backends.
- The Edge knows backends only. The Gateway knows the Edge (through a per-app `resolver_url`).
- No shared database between repositories. Contracts are the APIs in this document.
- Control plane (Gateway, Edge router) is never in the data path. Agents push directly to backends.

### Glossary

| Term | Meaning |
|---|---|
| `app_id` | Application served by the Gateway (`labmango`) |
| `backend_id` | Immutable logical name of a department backend (`dept_a`). Never a hostname |
| `agent_uid` | Server-generated UUID of one enrolled agent. Distinct from equipment `uid`, never derived from it, never a routing key, never a credential |
| `kid` (agent key) | Thumbprint of an agent public key: base64url(SHA-256(DER SPKI)). Names the key in assertions |
| `credential_version` | Integer on the agent identity; incremented on revocation or key change; carried in access tokens |
| `epoch` | UUID of a sync stream's counter history; changes when the history is not continuous (restore, reset) |
| Equipment `uid` | Existing LabMango equipment resource UUID; identifies the equipment record, not necessarily an agent installation |
| `user_key` | Stable user identity (SSO subject, employee ID or normalized email), never a local integer ID |
| Prefix | Public path of a backend, e.g. `/api/dept_a/`. Nginx strips it before the backend sees the request |
| Route | `{backend_id, base_url, prefix, auth, ttl, version}` |
| Version | Monotonic per-backend, per-entity-type counter. Changes only on routing-relevant changes |
| Grant | One-time enrollment token issued by a backend admin |
| Agent assertion | Short-lived JWT signed by the enrolled agent's private key |
| `kid` | Key id; two keys are trusted during rotation |

### Decisions (fixed)

D1 one backend per department, one shared frontend · D2 `backend_id` immutable · D3 Edge = Nginx + router in its own repo · D4 Edge **pulls** from backends; backends never call out · D5 version counter + change log with tombstones; bump only for routing-relevant changes · D6 Gateway is multi-app, depends on Edge one-way · D7 agents push directly to backends · D8 enrolled-agent identity = a key pair **generated on the device** (private key never leaves it) plus a server-issued `agent_uid`, linked to exactly one equipment record; equipment `uid` is the only routing key; public key flows through sync · D9 no secret travels Backend → Edge → Gateway, and no agent private key travels anywhere; backends issue short-lived per-agent tokens for a signed assertion · D10 config and manifests are signed (Ed25519, `kid`); agents keep last-known-good and roll back · D11 no secret manager; secrets are files / Docker or systemd secrets · D12 agents cache their route and keep working if Gateway or Edge is down · D13 credential lifecycle (`agent_keys`) is a separate sync entity from equipment ownership (`equipment`) · D14 the sync API is snapshot + catch-up with `epoch`, bounded deltas and a digest; backends serve it from a routing projection, never from live domain tables · D15 access tokens are revoked through `credential_version`, not per-token rows.

### Assumed defaults for open decisions (change here if the team decides otherwise)

| ID | Question | Default |
|---|---|---|
| O1 | Is the enrolled-agent UID unique globally or per app? | Resolved: server-generated UUIDv4, globally unique, never reused |
| O2 | One agent with modules, or one agent per app? | One agent with app modules |
| O3 | Can a user exist in two departments? | No. Conflict flagged; existing owner wins |
| O4 | Router and Gateway store | PostgreSQL (in-memory cache; Redis optional) |
| O5 | Shared per-backend API key needed? | No. Per-agent tokens only |
| O6 | History when equipment moves department | Stays in the old backend |
| O7 | Fleet size and push rate | Unknown; size after measuring (control plane traffic is small) |
| O8 | Telemetry store | TimescaleDB if available, else PostgreSQL with partitioning |

### API conventions

- Edge internal API is versioned in the path (`/internal/v1`), Gateway agent API too (`/v1`). **Backend APIs (`/agent/...`, `/internal/...`) have no version segment**: additive-only changes, capability discovery through `GET /agent/info`, and `426` plus `min_agent_version` for breaking changes.
- Times are UTC ISO-8601. Keys and signatures are base64url.
- Error body: `{"error": "<code>", "message": "<text>", "request_id": "<id>"}`. Every request carries `X-Request-Id`, propagated across components.

---

# Part A. Backend requirements

## 1. Purpose

Each department runs its own LabMango backend. This document covers only the **additions** needed for the multi-backend platform:

1. A **read-only sync API** so the Edge can learn which users and equipment live here.
2. **Version counters and a change log** that make sync cheap and correct.
3. A dedicated **agent API**: enrollment, per-agent tokens, agent-reported computing state (OS information, IP address, system information and disk usage), inventory and metrics telemetry, an event-monitoring push API, and booking read access plus narrowly scoped end-time updates and completion reporting for the equipment associated with the authenticated agent.
4. **Prefix handling** so one frontend works against many backends.

**Principles**
- The backend knows only its own `BACKEND_ID`. It never calls the Edge or the Gateway and has no list of other backends.
- The agent API is **separate** from the user-facing endpoints. It reuses the same service layer and models but has its own authentication, permissions, throttles and contract.
- The agent never calls user-facing endpoints.

## 2. Settings

```python
BACKEND_ID = "dept_a"                      # immutable
FORCE_SCRIPT_NAME = f"/api/{BACKEND_ID}"   # Nginx strips the prefix; Django generates prefixed URLs
SESSION_COOKIE_NAME = f"sessionid_{BACKEND_ID}"
CSRF_COOKIE_NAME = f"csrftoken_{BACKEND_ID}"

SYNC_TOKENS_FILE = "/run/secrets/sync_tokens"   # tokens allowed on /internal (hashed at load)
AGENT_TOKEN_TTL_S = 3600
ENROLL_GRANT_TTL_H = 24
TOKEN_SIGNING_KEY_FILE = "/run/secrets/token_signing_key"   # Ed25519 private key, mode 600
TOKEN_SIGNING_KID = "be-dept_a-2026-01"
AGENT_PUBLIC_BASE_URL = "https://lab.example.com/api/dept_a"   # canonical; used for assertion `aud` (never build_absolute_uri)
TRUSTED_PROXY_CIDRS = ["10.0.0.0/24"]                          # only these may set X-Forwarded-For (real client IP)
AGENT_TOKEN_TTL_BY_TIER = {"tpm": 3600, "os_keystore": 3600, "software": 900}
ENROLL_REQUIRE_APPROVAL = True                                 # fingerprint confirmation by an admin
ENROLL_MAX_FAILED_ATTEMPTS = 5                                 # per grant, then locked
KEY_ROTATION_GRACE_S = 600
KEY_NEXT_EXPIRES_H = 24
REVOCATION_CACHE_TTL_S = 30                                    # fallback; NOTIFY invalidates immediately
SYNC_LONGPOLL_MAX_S = 30
SYNC_LONGPOLL_MAX_PER_TOKEN = 8
SYNC_PAGE_LIMIT_DEFAULT = 500
SYNC_PAGE_LIMIT_MAX = 2000
CHANGELOG_RETENTION_DAYS = 30
ROUTING_TOMBSTONE_RETENTION_DAYS = 90

# telemetry
METRICS_RAW_RETENTION_DAYS = 14
METRICS_ROLLUP_RETENTION_DAYS = 365
EVENTS_RETENTION_DAYS = 90
AGENT_MAX_BATCH_RECORDS = 500
AGENT_MAX_BODY_BYTES = 1_000_000
AGENT_TS_MAX_PAST_H = 72
AGENT_TS_MAX_FUTURE_S = 300
STALE_AGENT_AFTER_S = 600
```

Secrets are files or Docker/systemd secrets. Nothing secret lives in the repo.

## 3. API surface at a glance

| Surface | Path (as the backend sees it) | Audience | Auth |
|---|---|---|---|
| User API (existing) | existing paths | Browsers | Session / user login |
| Sync API | `/internal/...` | Edge Router only | Sync token, network allowlist |
| **Agent API** | `/agent/...` | Equipment agents | Agent assertion → agent token |

Public Nginx exposes only the user API and `/agent/...` (under the prefix, for example `/api/dept_a/agent/...`). `/internal/...` is blocked at Nginx and re-checked in Django.

### 3.1 No version segment in paths: compatibility rules

Paths are unversioned (`/agent/metrics`, `/internal/sync/users`). Compatibility is maintained by rules instead:

1. **Additive changes only** on existing endpoints: new optional request fields, new response fields. Never remove, rename or change the meaning of a field.
2. **Tolerant readers**: agents ignore unknown response fields; the backend ignores unknown request fields (and may log them).
3. **New behavior = new endpoint or new capability**, not a changed one.
4. **Capability discovery**: `GET /agent/info` returns the capabilities this backend supports (see 6.9). Agents use only what is listed.
5. **Agent identifies itself** on every call with `X-Agent-Version: 1.4.2`. The backend logs the version distribution.
6. **Minimum version gate**: when something truly breaks, the backend answers `426 Upgrade Required` with `{"min_agent_version": "1.6.0"}`, and the agent runs its update check immediately (the Gateway serves the update).
7. A deprecated endpoint stays until the `X-Agent-Version` distribution shows no remaining callers.

The same rules apply to `/internal/...`: the Router and backends are deployed together under an additive-only contract, with `GET /internal/info` listing supported entity types.

## 4. Data model

### 4.1 Identity, credentials and routing projection

```
SyncState(entity_type PK [users|equipment|agent_keys], version BIGINT, epoch UUID)

RoutingChange(entity_type, version, key, op [upsert|delete], created_at)
  PK (entity_type, version)

RoutingEntity(entity_type, key, version, state, data JSONB, data_hash, deleted_at NULL)   # current routing projection
  PK (entity_type, key)
  # written ONLY by the service layer, in the same transaction as the domain change and the RoutingChange row.
  # The sync API reads this table and RoutingChange, never the live domain tables.

AgentIdentity(agent_uid UUID PK (server-generated), equipment_id FK,
    state [pending|pending_approval|active|revoked|decommissioned],
    credential_version INT NOT NULL DEFAULT 1, replaces_agent_uid NULL,
    agent_version, last_seen_at, enrolled_at, approved_by NULL, created_by)
  unique (equipment_id) WHERE state = 'active'
  unique (equipment_id) WHERE state IN ('pending','pending_approval')     # one open enrollment per equipment

AgentKey(kid PK (= thumbprint), agent_uid FK, alg [EdDSA|ES256], public_key (SPKI),
    status [next|active|retiring|revoked], key_storage_claimed, attestation_verified BOOL,
    created_at, activated_at, retire_at)
  unique (agent_uid) WHERE status = 'active'
  unique (public_key_sha256)                                                # a key belongs to one identity

EnrollmentGrant(id, token_hash UNIQUE, agent_uid FK, equipment_id FK, failed_attempts INT,
  expires_at, used_at NULL, revoked_at NULL, locked_at NULL, created_by)

AssertionNonce(jti, kid, expires_at)   # TTL store (Redis) or table with unique(jti) and an index on expires_at, purged every minute
AgentAuditEvent(ts, actor, agent_uid, equipment_id, action, outcome, request_id, detail)   # append-only
```

`AgentIdentity` links to the existing `Equipment` model through `equipment_id`. There is **no per-token table**: access tokens are revoked by incrementing `credential_version` (6.2.2).

Identifier roles are fixed:

| Identifier | Generated by | Used for | Never used for |
|---|---|---|---|
| Equipment `uid` | Backend (existing) | Edge routing key, sync key | Authentication |
| `agent_uid` | Backend, when an admin creates a pending agent | Token `sub`, audit, revocation | Routing, authentication on its own, anything the device must know to authenticate |
| `kid` (key thumbprint) | Derived from the agent's public key | Naming the key in assertions, lookup of the public key | Routing |
| Public key | Agent device | Verifying assertions; published through sync (`agent_keys`) | Routing key (it changes on rotation) |
| Private key | Agent device, non-exportable where possible | Signing assertions | Ever leaving the device |

Cardinality: at most one `active` identity per equipment and one open enrollment per equipment. Replacement is explicit (6.2.1). The linked equipment record scopes every read and write.

User entity: the existing user model plus a stable `user_key` (SSO subject, employee ID or normalized email). **Never use the local integer ID as the routing key.**

### Sync entities (what the Router receives)

| Entity | Key | `data` | Purpose |
|---|---|---|---|
| `users` | `user_key` | `{ "state": "active" }` | Frontend user resolve |
| `equipment` | equipment `uid` | `{ "state": "active\|moved\|decommissioned", "agent_enabled": true }` | Which backend owns this equipment. **Ownership only** |
| `agent_keys` | equipment `uid` | `{ "agent_uid": "…", "state": "pending\|active\|revoked\|none", "credential_version": 4, "keys": [ { "kid": "…", "alg": "EdDSA", "public_key": "…", "status": "active" } ] }` | Credentials for the Gateway to verify agent signatures; revocation |

Only equipment with `agent_enabled` appears in the `equipment` entity, which keeps the table small and avoids exposing equipment that has no agent.

### 4.2 Telemetry

```
AgentInventory(agent_uid PK, content_hash, data JSONB, collected_at, updated_at)   # latest snapshot only
AgentInventoryHistory(agent_uid, content_hash, data JSONB, valid_from)              # optional, changes only

AgentLatestMetrics(agent_uid PK, data JSONB, sampled_at)                            # for UI lists

MetricSample(agent_uid, ts, name, value DOUBLE, labels JSONB)                     # time series
  unique (agent_uid, ts, name, labels_hash)                                        # idempotency
  -- TimescaleDB hypertable on ts, if available (see O8)

AgentEvent(agent_uid, event_id, occurred_at, received_at, type, data JSONB,
  booking_id NULL, request_id)
  unique (agent_uid, event_id)                                                     # append-only, retry-safe
```

Telemetry tables are **outside** the routing change-log rule: bulk writes are allowed there.

### 4.3 Bookings

The agent uses the existing booking models. No new booking tables are needed. The agent endpoint is a scoped read through the booking service (see 6.6).

## 5. Version counter and change log

### 5.1 What bumps the version

| Entity | Bump on |
|---|---|
| `users` | create, delete or deactivate, `user_key` change |
| `equipment` | agent enabled or disabled, delete, equipment `uid` change, state change (`active`, `moved`, `decommissioned`), department move |
| `agent_keys` | identity state change (`pending`, `pending_approval`, `active`, `revoked`), key added, activated, retiring or revoked, `credential_version` change |

**Never bump** for any of the following: `last_seen_at`, heartbeat, inventory, metrics, events, computing-state snapshots, booking changes, or other business edits. This is the most important rule: otherwise the Edge refetches constantly.

Revocation is routing-relevant for the Gateway (it must stop trusting the key). It bumps `agent_keys` only, never `equipment`: equipment lifecycle and credential lifecycle are separate.

### 5.2 Transactional guarantee

The domain change, the `RoutingEntity` row, the `RoutingChange` row and the version increment are written **in the same DB transaction**.

```python
@transaction.atomic
def revoke_agent(agent_uid, actor):
    identity = AgentIdentity.objects.select_for_update().get(agent_uid=agent_uid)
    identity.state = "revoked"
    identity.credential_version += 1
    identity.save(update_fields=["state", "credential_version"])
    AgentKey.objects.filter(agent_uid=agent_uid).exclude(status="revoked").update(status="revoked")  # allowed: not a routing model
    publish_routing("agent_keys", key=str(identity.equipment.uid), op="upsert",
                    state="revoked", data=build_agent_keys_data(identity))   # last statement: shortest lock hold
    audit(actor, "agent.revoke", identity)
    transaction.on_commit(lambda: notify_waiters("agent_keys"))               # LISTEN/NOTIFY

def publish_routing(entity, key, op, state, data):
    ss = SyncState.objects.select_for_update().get(entity_type=entity)       # serializes writers; commit order == version order
    ss.version += 1
    ss.save(update_fields=["version"])
    RoutingChange.objects.create(entity_type=entity, version=ss.version, key=key, op=op)
    RoutingEntity.objects.update_or_create(entity_type=entity, key=key,
        defaults=dict(version=ss.version, state=state, data=data, data_hash=sha256(canon(data)),
                      deleted_at=None if op == "upsert" else now()))
```

Why this is correct: the row lock on `SyncState` is held until commit, so versions become visible **in order** and a reader that has seen version *n* has seen every version below it. Keep routing transactions short, do no network I/O inside them, and take the `SyncState` lock as the last step.

### 5.3 Rules to keep it reliable

- Route **all** writes of routing-relevant fields through the service layer. Django signals miss `bulk_create`, `bulk_update` and `queryset.update()` on routing models.
- CI test: fail if those bulk methods are called on routing models outside the service layer. Optional safety net: DB trigger that refuses direct writes to `RoutingEntity`.
- Monotonic integer counter, never a timestamp.
- **Epoch:** `SyncState.epoch` is created with the row. **Any database restore, point-in-time recovery, counter reset or cloning of a backend database must run `manage.py rotate_sync_epoch`** (mandatory step of the restore runbook). The Router treats a changed epoch, or a head version lower than its cursor, as "start over" (full snapshot).
- Prune `RoutingChange` older than `CHANGELOG_RETENTION_DAYS`. Keep `RoutingEntity` tombstones (`deleted_at`) for `ROUTING_TOMBSTONE_RETENTION_DAYS`.
- Compaction: a delta response returns the **latest operation per key** in the requested range.
- `RoutingEntity` is rebuildable from domain data by `manage.py rebuild_routing_projection` (also used for verification in CI).

### 5.4 Wake-up for long-poll

After commit, the service sends Postgres `NOTIFY routing_<entity>`. Every ASGI worker holds a `LISTEN` connection (or a shared listener process) and wakes its local waiters. Without it, multi-worker deployments miss wake-ups. No external system is involved.

## 6. Agent API (`/agent/...`)

Publicly: `/api/dept_a/agent/...`. Paths below are as the backend sees them.

### 6.0 Common rules

| Rule | Detail |
|---|---|
| Auth | `Authorization: Bearer <agent access token>` (except the explicitly protected enrollment flow and the token endpoint). No cookies, no CSRF. An equipment UID in a custom header is never authentication or authorization |
| Scope | The token's `sub` (`agent_uid`) resolves to one `AgentIdentity` and its linked equipment. Every read and write is limited to that equipment |
| Capability scopes | Token `scope` claim may include `inventory:write`, `telemetry:write`, `activity:write`, `bookings:read`, and owner-enabled `bookings:end_time:write` and `bookings:complete`. `activity:write` authorizes only append-only observed monitoring events; it never authorizes a booking or equipment state transition. Booking scopes permit only the specific actions in 6.7 |
| Headers | `X-Agent-Version`; `Idempotency-Key` on retryable writes; `X-Seq` only where ordered processing is required. An optional `X-Equipment-UID` is a consistency check against the equipment resolved from the token, never a selector or credential |
| Errors | `{"error": "...", "message": "...", "request_id": "..."}`. Auth failures never reveal whether an identity, grant or key exists |
| Status codes | `401` token expired or credential version stale → re-assert; `403` revoked or scope missing; `421` equipment/agent identity not owned here; `426` agent too old; `429` rate limited (`Retry-After`); `413` too large |
| Server time | Every `401` includes `server_time`, so devices can correct clock skew |
| Throttle | Per agent identity and per endpoint group; per-IP only for unauthenticated endpoints, using the real client IP from `TRUSTED_PROXY_CIDRS` |
| Logic | Views authenticate, validate, scope, call the service layer, serialize. No business logic |
| Audit | Enroll, approve, token failures, rotate, revoke, state projection, event-ingest security/validation outcomes, and any booking-linked event write an `AgentAuditEvent` |

Package layout:

```
agent_api/
  auth.py          # AgentTokenAuthentication (verifies EdDSA token, aud, scope, credential_version) -> request.agent_identity
  permissions.py   # HasScope, OwnsEquipment
  throttles.py     # PerAgentThrottle, EnrollThrottle
  views/           # enroll, approve, token, rotate, equipment-state, inventory, metrics, events, bookings, heartbeat, info
  serializers/
  urls.py
services/          # shared with the user API: agent identities, routing publish, telemetry ingest, bookings
openapi/agent.yml  # the contract, with contract tests
```

### 6.1 Credential model (fixed)

**The backend never generates, stores, displays or transmits an agent private key.** The private key is generated on the device and never leaves it. The backend only ever receives and stores public keys.

```
 Admin (UI) ──1 create pending agent──▶ Backend: AgentIdentity(state=pending) + EnrollmentGrant (hash only)
 Admin ──2 grant via installer prompt / trusted channel──▶ Device
 Device: 3 generate key pair in TPM / OS keystore (non-exportable), compute kid, show fingerprint code
 Device ──4 POST /agent/enroll {grant, public_key, proof, attestation?}──▶ Backend: verify
 Backend: 5a attested key or ENROLL_REQUIRE_APPROVAL=False → state=active
          5b otherwise state=pending_approval; admin confirms the same fingerprint code in the UI → active
 Device ──6 POST /agent/token {assertion signed by device key, kid}──▶ Backend ──▶ short-lived access token
 Device ──7 data calls with Bearer token──▶ Backend resolves sub ─▶ AgentIdentity ─▶ equipment (server-side)
```

Key storage tiers. `key_storage` sent by the device is a **claim**. Policy uses the **verified tier**:

| Tier | Where | Verified by | Policy |
|---|---|---|---|
| `tpm` | TPM 2.0 / secure enclave, non-exportable | Attestation statement verified at enroll (`attestation_verified=true`) | Preferred; skips mandatory approval if the department allows |
| `os_keystore` | Windows CNG/DPAPI (machine scope), macOS Keychain, Linux kernel keyring or root-only file | Not verifiable; treated as `software` for approval policy | Acceptable with approval |
| `software` | Key file, mode 600, service account only | n/a | Only with department approval; token TTL 15 min (`AGENT_TOKEN_TTL_BY_TIER`) |

Departments set a minimum verified tier. Unattested claims never satisfy a `tpm` requirement.

Forbidden: backend-generated key pairs, downloadable key bundles, private keys in email/tickets/browsers, any endpoint that issues a credential based on an equipment UID or `agent_uid` alone, shared keys across devices.

### 6.1.1 Create pending agent (admin)

`POST /agent/enrollment-grants` (user-API auth; role `lab_admin` or equipment owner, object-scoped to the equipment; recent re-authentication required)
```json
{ "equipment_uid": "3d52…", "ttl_minutes": 60, "replace_active": false }
```
In one transaction: create `AgentIdentity(state=pending, agent_uid=<server UUIDv4>)` and an `EnrollmentGrant` bound to that `agent_uid` and equipment, publish `equipment` (`agent_enabled=true`) and `agent_keys` (`state=pending`) so the Router knows the equipment immediately. Response `201` (grant shown once, never retrievable again):
```json
{ "agent_uid": "7b1f4c2e-…", "grant": "eg_Zk3…", "expires_at": "2026-11-05T10:30:00Z" }
```
Rules: default TTL 60 min, max `ENROLL_GRANT_TTL_H`; grant stored as SHA-256 only; creator audited; admin can revoke an unredeemed grant; expired pending identities are cleaned up and alerted; `409` if the equipment already has an active agent and `replace_active` is false. `replace_active=true` requires a second approver when `ENROLL_REQUIRE_APPROVAL` is on.

### 6.2 Enroll (device, one time)

`POST /agent/enroll` (no Bearer; protected by grant + proof of possession; strict per-IP and per-grant rate limit)
```json
{
  "grant": "eg_Zk3…",
  "public_key": "base64url(DER SPKI)",
  "alg": "EdDSA",
  "key_storage": "tpm",
  "attestation": { "type": "tpm2", "statement": "base64url…" },
  "fingerprint": "sha256:…",
  "agent_version": "1.4.2",
  "proof": "<compact JWS signed by the new key>"
}
```
`proof` is a JWS (`alg` = the key's algorithm, `kid` = thumbprint of `public_key`) over canonical JSON (sorted keys, no whitespace):
```json
{ "v": 1, "typ": "labmango-enroll", "backend_id": "dept_a", "grant_sha256": "…", "alg": "EdDSA", "public_key_sha256": "…", "iat": 1762335000 }
```
(The 1.0 concatenation format is dropped: it was ambiguous.) The backend derives `agent_uid` and equipment from the grant. The request cannot choose either.

Checks, in one transaction with `select_for_update` on the grant: grant exists, unused, unrevoked, unexpired, not locked; identity is `pending`; proof verifies with the declared `alg`, `backend_id` matches, `iat` within ±5 min; `public_key_sha256` unused by any other identity; `kid` computed by the server equals the thumbprint of the key; attestation verified when present; verified tier meets the department minimum. Failures increment `failed_attempts`; after `ENROLL_MAX_FAILED_ATTEMPTS` the grant is locked and an alert is raised.

Outcome:
- Create `AgentKey(status=active)` and publish `agent_keys`.
- If the verified tier is `tpm` (or `ENROLL_REQUIRE_APPROVAL` is false): `state=active`.
- Otherwise `state=pending_approval`. The admin UI shows the short fingerprint code reported by the device; an admin (not the grant creator when dual control is configured) confirms that it matches the code on the device. Only then `state=active`. This defeats the stolen-grant race.
- Mark the grant used; if `replace_active`, revoke the replaced identity (`credential_version` bump, `agent_keys` publish).

Response `201`:
```json
{
  "agent_uid": "7b1f4c2e-…",
  "equipment_uid": "3d52…",
  "backend_id": "dept_a",
  "base_url": "https://lab.example.com/api/dept_a/",
  "state": "pending_approval",
  "auth": { "method": "agent_assertion", "token_endpoint": "https://lab.example.com/api/dept_a/agent/token" }
}
```
Errors: `400 invalid_proof`, `403 grant_invalid` (the same response for unknown, used, expired, locked or revoked grants, to avoid an oracle), `409 public_key_in_use`, `422 key_storage_not_allowed`.

While `pending_approval`, the token endpoint answers `403 pending_approval` (with `Retry-After`); no data scopes are ever granted.

### 6.2.1 Key rotation, recovery, revocation

**Rotation (two-phase, no lockout)** `POST /agent/keys/rotate` (Bearer, current key):
body `{new_public_key, alg, key_storage, attestation?, proof_new}` where `proof_new` is a JWS signed by the **new** key over `{"v":1,"typ":"labmango-rotate","agent_uid":"…","public_key_sha256":"…","iat":…}`.
1. The backend stores the key as `AgentKey(status=next)`. The old key stays `active`. Nothing is published yet.
2. The agent requests a token with an assertion signed by the new key. The first successful assertion promotes the key to `active`, marks the old key `retiring` (`retire_at = now + KEY_ROTATION_GRACE_S`), increments `credential_version`, and publishes `agent_keys`.
3. After the grace period a job marks the old key `revoked` and publishes again.
4. A `next` key that is never confirmed is discarded after `KEY_NEXT_EXPIRES_H`.
A lost response at any step cannot lock the device out, because the old key remains valid until the new one proves itself. Recommended every 90 days for `software`, yearly otherwise.

**Recovery** (device rebuilt, key lost): an admin creates a new grant with `replace_active=true`. A new `agent_uid` is issued; the old identity becomes `revoked`. Keys are never recovered or exported.

**Revocation** (admin, or automatic on decommission): `state=revoked`, `credential_version += 1`, all keys `revoked`, `agent_keys` published, auth caches invalidated by `NOTIFY`. The SLA is in 9.2.

### 6.2.2 Request authentication and scoping

```python
class AgentTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        claims = verify_access_token(request)              # EdDSA, kid, aud == BACKEND_ID, exp, iat
        agent = get_agent_cached(claims["sub"])            # cache entry invalidated by NOTIFY; TTL REVOCATION_CACHE_TTL_S
        if agent is None or agent.state != "active" or agent.credential_version != claims["cv"]:
            raise AuthenticationFailed("agent_not_active")  # includes server_time
        request.agent_identity = agent                     # carries equipment_id, resolved server-side
        return (AgentPrincipal(agent), claims)
```

- The token carries `sub`, `scope` and `cv` (credential version). It never carries `equipment_id`. Equipment is resolved per request from `AgentIdentity`, so relinking or revocation applies without waiting for token expiry.
- There is no per-token table. Revocation increments `credential_version`; every older token fails the `cv` check. The cache entry is dropped by `NOTIFY` on all workers, so the effective delay is milliseconds, bounded by `REVOCATION_CACHE_TTL_S` if a notification is lost.
- No agent endpoint accepts an equipment or computing id. Such fields in body or query are rejected (`422`). `X-Equipment-UID`, if sent, is only compared with the resolved equipment.
- Service functions take `equipment_id` as a trusted argument from the auth layer and always filter by it.
- Booking-linked events are accepted only if the booking belongs to the same equipment, otherwise `403`.
- Equipment field projection (for example `os_name`) uses a fixed server-side allowlist; everything else is stored only as agent inventory.

### 6.3 Token

`POST /agent/token` with `{ "assertion": "<JWT>" }`.

Assertion (signed by the device key): header `{alg, kid, typ:"JWT"}`, claims `iss = sub = <kid>`, `aud = AGENT_PUBLIC_BASE_URL + "/agent/token"` (the canonical configured URL, not the request URL), `iat`, `exp` (≤ 60 s after `iat`), `jti`.

The device identifies itself by the **key thumbprint**. It needs no server-issued id to authenticate, so recovery, moves and renames never change what the device sends.

Checks: look up `AgentKey` by `kid`; key status `active`, `retiring` (within grace) or `next` (promotion path, 6.2.1); identity `state == active` (else `403`; `pending_approval` → `403 pending_approval`; moved or unknown to this backend → `421` after the same checks that avoid an existence oracle); header `alg` equals the registered `alg` (no `none`, no algorithm switching); signature valid; `aud` equals the canonical URL; `iat` within ±60 s of server time; `jti` unused (`AssertionNonce`, kept until `exp`); fingerprint matches if provided. Rate limit per `kid` and per real client IP.

Response `200`:
```json
{ "access_token": "<JWT EdDSA signed by backend key>", "token_type": "Bearer", "expires_in": 3600,
  "scope": "inventory:write telemetry:write activity:write bookings:read bookings:end_time:write bookings:complete" }
```
Access token: header `{alg:"EdDSA", typ:"JWT", kid:"be-dept_a-2026-01"}`, claims `iss=dept_a`, `sub=<agent_uid>`, `aud=dept_a`, `scope`, `cv=<credential_version>`, `iat`, `exp` (TTL from `AGENT_TOKEN_TTL_BY_TIER`), `jti`. The backend checks `aud == BACKEND_ID` and `cv` on every call. No refresh token: the agent re-asserts with its device key.

The granted `scope` is the intersection of the capabilities enabled for the equipment's department and what the agent identity is allowed to use.

### 6.4 Agent-reported computing state

Agents can publish a bounded snapshot of fields owned by the agent. This is distinct from equipment lifecycle status and booking status; a computing-state update must not transition either state machine. Live computing activity (such as a user session or running job) is a separate, time-varying stream defined in 6.5 and must not be treated as part of this snapshot.

`PATCH /agent/equipment/state`

Authentication: short-lived Bearer agent token with `inventory:write` scope. The backend resolves its `agent_uid` to the enrolled identity and linked equipment; the request cannot select another equipment record. If the request also supplies optional `X-Equipment-UID`, it must canonicalize to the linked equipment's UID or the request is rejected without changing data. Missing/unknown/revoked credentials are rejected; a missing or mismatched optional header never grants access.

Request body (candidate contract; exact JSON schemas and units require owner approval):

```json
{
  "collected_at": "2026-11-05T09:30:00Z",
  "ip_address": "192.0.2.12",
  "os_name": "Example OS",
  "os_version": "12.4.1",
  "system_info": {"architecture": "x86_64", "memory_bytes": 17179869184},
  "disk_usage": [{"mount": "/", "total_bytes": 512000000000, "used_bytes": 128000000000}]
}
```

- Only allowlisted fields are writable. Reject unknown keys and server-managed fields. `collected_at` is an observation timestamp, not an equipment `updated_at`; reject timestamps outside the existing telemetry window and prevent older snapshots from overwriting newer accepted state.
- Current `ComputingEquipment` fields are `ip_address`, `os_name`, `system_info`, and `disk_usage`; there is no dedicated `os_version` field. Decide whether `os_version` belongs in a documented `system_info` schema or a new persisted field before implementation. Do not silently change the model.
- Validate IP address format; define maximum JSON size/depth, string and array lengths, disk byte units, allowed system-info keys, privacy/redaction rules, and update frequency. Never trust arbitrary agent JSON as an unbounded or unrestricted payload.
- `X-Equipment-UID` is only an optional consistency assertion. A UID is an identifier, not a secret, credential, or proof of possession. UID-only requests are rejected even when the UID exists. Missing/invalid authentication returns `401`; an authenticated but revoked or insufficiently scoped identity is denied without exposing another equipment record.
- Update only the agent-owned computing fields using a feature command. Do not accept `uid`, SKU, owner, RDP configuration, technical user, resource lifecycle status, booking status, audit fields, or unrelated equipment fields. Audit the agent identity, equipment target, changed field names, request ID and outcome; redact credentials and avoid logging full system information.
- Require retry-safe semantics (`Idempotency-Key` or a unique per-agent snapshot sequence), and define conflict behavior if a user/admin and agent can write the same fields. If shared concurrent editing is allowed, use a strong ETag/version and `If-Match`; never use `updated_at` as the concurrency token.

Success: `200` with the standard response envelope and accepted snapshot metadata (not credentials), or `204` only if selected by the final API contract. Validation follows the API standards: malformed request `400`, unknown/read-only field or invalid value `422`, stale precondition `412`, rate limit `429`, oversized body `413`.

#### 6.4.1 Data ownership and single source of truth

| Data | Written by | Stored in | Read by |
|---|---|---|---|
| Computing state snapshot (`ip_address`, `os_name`, `system_info`, `disk_usage`) | Agent via `PATCH /agent/equipment/state` | The agent-owned fields of `ComputingEquipment` | UI, other features |
| Inventory (detailed hardware and software) | Agent via `POST /agent/inventory` | `AgentInventory` | UI details, audit |
| Metrics | Agent via `POST /agent/metrics` | `MetricSample`, `AgentLatestMetrics` | Charts, alerts |
| Activity events | Agent via `POST /agent/events` | `AgentEvent` | Timeline, reports |

Rules:
- **Agent-owned fields are read-only in the user API** (UI and admin) so no human edit can collide with the agent. If a human override is a requirement, store it in a separate field.
- Concurrency rule: an update is accepted only if `collected_at` is newer than the stored `state_collected_at`; older snapshots are acknowledged but ignored. No ETag is needed for agent-owned fields.
- Do not send the same value through two paths. `os_name` and `disk_usage` in the state snapshot are the "current" values; inventory holds the detailed structure without duplicating those keys; metrics hold the time series. The server may derive `disk_usage` from the latest metrics sample if the owner prefers a single write path.
- The agent's `collected_at` is untrusted: the server also stores `received_at`, rejects records outside the window, and flags agents whose clock offset exceeds `AGENT_TS_SKEW_ALERT_S` (default 120 s).
- Projection to `ComputingEquipment` is performed by one service function with a field allowlist, audited with the field names changed.

### 6.5 Telemetry and live computing activity: inventory, metrics, events

Inventory, measurements, and events are separate streams so the agent can send each kind at its own pace. Live computing activity (for example, session/job start and end) is represented as timestamped events, not as equipment state or booking mutation.

| Kind | Examples | Rate | Storage |
|---|---|---|---|
| Inventory | OS, hostname, CPU, RAM, disks, NICs, installed software, agent version | On start and on change | Latest snapshot (+ optional change history) |
| Metrics | Disk usage, CPU, memory, uptime, free space | Every 30 s to 5 min | Time series |
| Events | Logins, running jobs, process start/stop, session start/end, errors | Event-driven | Append-only |

#### `POST /agent/inventory` (scope `telemetry:write`)
```json
{ "collected_at": "2026-11-05T09:30:00Z",
  "content_hash": "sha256:…",
  "data": { "os": {"name": "Windows 11", "build": "22631"}, "cpu": {"model": "…", "cores": 16},
            "ram_mb": 65536, "disks": [{"mount": "C:", "size_gb": 953}], "nics": [ ] } }
```
- If `content_hash` equals the stored hash: `304`/`200 {"changed": false}` and only `last_seen_at` updates.
- Otherwise upsert the snapshot (and history row if enabled). No routing version bump.

#### `POST /agent/metrics` (scope `telemetry:write`)
```json
{ "batch_id": "…",
  "samples": [ { "ts": "2026-11-05T09:30:00Z", "name": "disk.used_pct",
                 "labels": {"mount": "C:"}, "value": 71.4 } ] }
```
#### `POST /agent/events` (scope `activity:write`; authenticated event-monitoring push API)

The agent pushes observed monitoring events to the backend; this is not a polling endpoint and does not permit remote process control. Events are immutable observations. The backend derives `agent_uid` and equipment from the verified bearer token; clients must not supply either as a selector. The endpoint accepts bounded batches so agents can buffer locally and retry after temporary network failures.

```json
{ "events": [
    { "id": "01JBS…", "ts": "2026-11-05T13:02:11Z", "type": "session_started",
      "booking_id": "b-9912", "data": { "user_key": "e12345" } },
    { "id": "01JBS…", "ts": "2026-11-05T13:03:02Z", "type": "process_started",
      "data": { "process_category": "instrument_control" } }
  ] }
```

Contract and behavior:
- Each event has a client-generated, stable `id` (UUIDv4 or ULID) reused unchanged for retries, UTC `ts`, an allowlisted `type`, and a bounded, type-specific `data` object. `booking_id` is optional and may only reference a booking already belonging to the authenticated equipment.
- Initial event categories are session/job lifecycle (`session_started`, `session_ended`, `job_started`, `job_ended`), process lifecycle (`process_started`, `process_ended` using policy-approved process categories, not arbitrary command lines), and agent/host health (`agent_error`, `host_status_changed`). Departments may disable categories. Exact event types and schemas are versioned additively in the capability contract.
- Do not ingest arbitrary process command lines, environment variables, file contents, credentials, or unrestricted usernames. User identifiers are omitted by default; if needed, accept only the configured stable `user_key`. Apply field allowlists, string/array/depth limits, and privacy redaction before persistence. Never render event data as HTML.
- Validate the whole request against `AGENT_MAX_BODY_BYTES`, `AGENT_MAX_BATCH_RECORDS`, and the timestamp window (`AGENT_TS_MAX_PAST_H`, `AGENT_TS_MAX_FUTURE_S`). Reject malformed or disallowed payloads; do not silently drop unknown event types or fields. Stable per-event IDs are the canonical retry key. If a batch-level `Idempotency-Key` is also supplied, bind it to the authenticated agent and request-body digest in a bounded idempotency record with documented retention.
- Enforce unique `(agent_uid, event_id)` in the database. Replayed events are counted as duplicates and never create a second record. Return `202` with accepted and duplicate counts only after durable acceptance (database transaction or durable queue/outbox); a volatile in-memory queue is not sufficient. If queueing is selected, persist the batch before acknowledging it and make consumers idempotent.
- Store both `occurred_at` (agent-supplied `ts`) and server `received_at`; preserve the original event time, flag excessive clock skew, and do not use event timestamps to order security decisions. Events are append-only; corrections use a new event with a reference to the prior event rather than mutation.
- Update agent `last_seen_at` for an authenticated accepted request. Event ingestion never changes equipment lifecycle, booking status, or any `SyncState` version. Booking association is a read-only validation/link; it grants no booking mutation permission.
- Audit the authenticated agent, linked equipment, accepted/duplicate/rejected counts, request ID, and outcome without copying sensitive event payloads into audit logs.

Success response (envelope details follow the repository API response standard): `202 Accepted`, with `accepted`, `duplicates`, and a server `request_id`. Repeating an identical batch is safe. Apply per-agent and endpoint-group throttles; return `413` for an oversized body, `422` for disallowed schema/value, `429` with `Retry-After` when throttled, and standard authentication errors without revealing identity existence.

Common behavior for inventory, metrics and events:
- Inventory and metrics validate size (`AGENT_MAX_BODY_BYTES`), count (`AGENT_MAX_BATCH_RECORDS`), timestamp windows, and field allowlists. Event-specific constraints above also apply to `/agent/events`.
- Idempotent: duplicate inventory/metrics idempotency keys or `(agent_uid, ts, name, labels)` samples and duplicate `(agent_uid, event_id)` events are ignored. Use database uniqueness and conflict-safe inserts; a pre-insert existence check is not a race guard. Return accepted and duplicate counts.
- **Cardinality control:** metric names and label keys come from a server-side allowlist; label values are length-limited; a per-agent cap on distinct series prevents label explosion.
- Writes go to a queue and are inserted in bulk by workers; the view answers fast.
- Each accepted batch updates `AgentIdentity.last_seen_at` and `AgentLatestMetrics`, **never** `SyncState`.
- Events with a `booking_id` are linked to a booking only after verifying equipment ownership in the service layer. This remains observational linkage and grants no booking mutation permission; the separate `bookings:complete` action is defined in 6.7.

Privacy: allowed inventory and event fields are defined in server-side schemas and allowlists (hostname, OS, hardware, and usernames only if required). Disallowed fields/types are rejected with a validation error, not silently dropped. The Gateway config can disable event categories per department. Activity events are append-only observations; associating an event with a booking does not grant permission to modify that booking.

### 6.6 Retention and rollups

| Data | Retention | Mechanism |
|---|---|---|
| Raw metric samples | `METRICS_RAW_RETENTION_DAYS` | Drop old chunks / scheduled delete |
| 5-minute rollups | `METRICS_ROLLUP_RETENTION_DAYS` | Continuous aggregate or scheduled job |
| Events | `EVENTS_RETENTION_DAYS` | Scheduled delete |
| Event-ingest idempotency keys | Retained at least as long as their event records | Event-row uniqueness; no separate unbounded key table |
| Inventory history | Keep changes only, policy per department | Scheduled delete |
| Latest snapshots | While the associated equipment/agent identity exists | n/a |

### 6.7 Bookings (read plus narrowly scoped end-time update and completion report)

`GET /agent/bookings?from=2026-11-05T00:00:00Z&to=2026-11-12T00:00:00Z` (scope `bookings:read`)

Headers: `If-None-Match: "<etag>"`.

Response `200`:
```json
{
  "equipment_uid": "7b1f4c2e-…",
  "server_time": "2026-11-05T09:30:00Z",
  "valid_until": "2026-11-05T09:45:00Z",
  "bookings": [
    { "id": "b-9912", "start": "2026-11-05T13:00:00Z", "end": "2026-11-05T17:00:00Z",
      "status": "confirmed", "booked_by": { "user_key": "e12345" } }
  ]
}
```
Rules:
- Scoped to the equipment linked to the authenticated agent identity through the booking service. The agent cannot request another resource.
- Bounded window: default the next 7 days, maximum 31 days.
- Minimal user data: `user_key` only unless a concrete need is documented.
- `ETag` is derived from the booking set in the window; `304` when unchanged.
- `server_time` lets the agent compensate clock skew; `valid_until` tells it how long the cache may be trusted.
- Optional `wait=30` long-poll (same mechanism as 5.4) if near-instant changes are needed.
- Booking changes never bump `SyncState`.

Booking writes are authorized by the authenticated agent identity and its server-side equipment link, never by an equipment UID supplied by the caller. Agents may update only the end time and report completion for an associated booking. They cannot change the start time, bench, project, reason, owner, approval state, cancel a booking, or request arbitrary status transitions. Each operation has a distinct scope: `bookings:end_time:write` for the end-time action and `bookings:complete` for the completion-report action. Department policy grants these scopes independently.

`PATCH /agent/bookings/{booking_id}` (scope `bookings:end_time:write`)

Headers: `Idempotency-Key: <UUID>`.

Request schema, strict with no additional properties:
```json
{ "ends_at": "2026-11-05T18:00:00Z" }
```
Only `ends_at` is writable. The end-time update must preserve the booking's valid interval and minimum duration, must not change `starts_at`, and must pass the booking feature's overlap/conflict and lifecycle rules. It is available only for an approved booking in an eligible reserving state (`reserved` or `in_progress`) associated with the agent's equipment. The booking command re-checks eligibility, equipment/bench ownership and conflicts atomically under the feature's established booking/bench locks. An unassociated booking resolves as `404`; invalid state or a conflict returns `409`. The operation must be retry-safe, auditable, and protected by the booking feature's application command. A user-supplied equipment UID is never accepted as a selector.

`POST /agent/bookings/{booking_id}/actions/complete` (scope `bookings:complete`)

Headers: `Idempotency-Key: <UUID>`; the backend resolves the booking and verifies that the booking's bench is associated with the equipment linked to this authenticated agent. A caller-provided equipment UID is never used as the authorization selector.

Request: `{}`. No status, approval, equipment, or other writable fields are accepted.

Success: `200` with the updated booking action result. The action is allowed only when the booking is approved, currently `in_progress`, and belongs to the agent's linked equipment; otherwise return a non-disclosing `404` for an unassociated booking or `409 invalid_state_transition` for a visible booking in an ineligible state. Replaying the same idempotency key and request returns the original outcome without repeating the mutation.

The agent adapter must call dedicated commands exposed through the bench-bookings feature's `public.py`; it must not write booking models or call internal application modules across the feature boundary. Commands re-check equipment/bench association and eligibility under the booking feature's transactional locks, apply the requested end-time change or existing allowed completion transition, and record an auditable actor reference (`agent_uid`), equipment, booking, request ID, and outcome. The operations must use the booking application's lifecycle, validation and concurrency rules. Booking-write scopes are enabled only by department policy and granted explicitly in tokens; they are distinct from `bookings:read` and `activity:write`.

### 6.8 Heartbeat and ping

- `POST /agent/heartbeat` (Bearer): `{ "agent_version": "…", "uptime_s": … }` → `204`. Updates `last_seen_at` only.
- `GET /agent/ping` (Bearer): `200 {"backend_id": "dept_a"}`. Used by the agent's health check after config changes.

### 6.9 Adding a new agent capability (recipe)

1. Implement or reuse a **service function** (no HTTP concerns).
2. Add a thin view in `agent_api/views/`, with scope enforcement, linked-equipment scoping and serializer.
3. Add a throttle scope and an Nginx rate-limit rule if the traffic pattern differs.
4. Add the endpoint to `openapi/agent.yml`, advertise it in `GET /agent/info`, and add a contract test.
5. Release the backend first; agents begin using it once `info` lists it.

### 6.10 Capabilities

`GET /agent/info` (Bearer):
```json
{ "backend_id": "dept_a",
  "capabilities": ["equipment_state_write", "inventory", "metrics", "event_monitoring_push", "bookings_read", "booking_end_time_write", "booking_completion_report"],
  "event_types": ["session_started", "session_ended", "job_started", "job_ended", "process_started", "process_ended", "agent_error", "host_status_changed"],
  "limits": { "max_batch_records": 500, "max_body_bytes": 1000000 },
  "min_agent_version": "1.2.0" }
```

## 7. Sync API (`/internal/...`, read-only, Edge only)

Authentication: `Authorization: Bearer <sync token>`; constant-time comparison against hashed tokens, a list of tokens accepted during rotation, or mTLS. Not routable from public Nginx; reachable only from the Router's address (checked again in Django). At most `SYNC_LONGPOLL_MAX_PER_TOKEN` concurrent held requests per token.

The API serves data from `RoutingEntity` and `RoutingChange` only (5.2). Entities: `users`, `equipment`, `agent_keys` (4.1).

### `GET /internal/info`
```json
{ "backend_id": "dept_a", "server_time": "2026-11-05T09:30:00Z",
  "entities": { "users":       { "version": 45,  "epoch": "5f0c…" },
                "equipment":   { "version": 128, "epoch": "a17b…" },
                "agent_keys":  { "version": 301, "epoch": "c902…" } } }
```
Used for liveness, lag calculation and epoch checks.

### `GET /internal/sync/{entity}`

Query parameters: `since` (cursor, default 0), `epoch` (the epoch the client knows), `limit` (default 500, max 2000), `wait` (0 to `SYNC_LONGPOLL_MAX_S`), `cursor` (opaque, for paging a snapshot).

| Status | Meaning |
|---|---|
| `304` | Nothing newer than `since` (after at most `wait` seconds) |
| `200` delta | Changes after `since`, at most `limit` |
| `200` full | `since` is unknown, older than retained history, or `epoch` differs: a snapshot page |
| `409` | Client sent an `epoch` or `since` that the server cannot satisfy and `full` was not allowed (`allow_full=false`) |
| `401/403` | Bad token |

Delta response:
```json
{
  "backend_id": "dept_a", "entity_type": "agent_keys", "epoch": "c902…", "mode": "delta",
  "version": 303, "head_version": 305, "has_more": true,
  "oldest_retained_version": 97, "generated_at": "2026-11-05T09:30:00Z",
  "changes": [
    { "version": 301, "op": "upsert", "key": "3d52…",
      "data": { "agent_uid": "7b1f…", "state": "active", "credential_version": 2,
                "keys": [ { "kid": "…", "alg": "EdDSA", "public_key": "…", "status": "active" } ] } },
    { "version": 303, "op": "delete", "key": "0c9a…" }
  ]
}
```
Rules for the producer:
- Changes are ordered by version, each key appears **at most once** (its latest operation in the range).
- `version` is the cursor the client must store: the last returned change version if `has_more`, otherwise `head_version`.
- If `since > head_version` or `epoch` differs from the server epoch, the server answers `mode: "full"` (never an error that would leave the client stuck).

Full response (paged keyset scan, ordered by key):
```json
{ "backend_id": "dept_a", "entity_type": "users", "epoch": "5f0c…", "mode": "full",
  "snapshot_version": 45, "head_version": 47, "next_cursor": "eyJrIjoiZTEyMzQ1In0",
  "items": [ { "key": "e12345", "version": 31, "data": { "state": "active" } } ] }
```
- `snapshot_version` is `SyncState.version` read at the first page (opaque `cursor` carries it for later pages). Items carry their own `version`.
- Pages are read at the current state; rows changed after `snapshot_version` may appear in a page with a newer version. The client continues with a delta from `snapshot_version`, which re-delivers anything changed later, so the combination is exact (idempotent apply with per-key versions).
- Tombstones are not part of full mode. Deleted keys arrive as `delete` changes.

### `GET /internal/digest/{entity}`

```json
{ "epoch": "c902…", "version": 305, "count": 812, "checksum": "sha256:…" }
```
`checksum` = SHA-256 over the sorted lines `key|state|data_hash` of live `RoutingEntity` rows, computed in a `REPEATABLE READ` transaction together with `version`, cached per version. The Router compares it with its own checksum for this backend to detect drift without pulling data.

### `GET /internal/equipment/{equipment_uid}`

Single lookup used by the Router for unknown equipment UIDs. Returns equipment ownership and `agent_keys` composed:
```json
{ "equipment_uid": "…", "equipment": { "state": "active", "agent_enabled": true },
  "agent_keys": { "state": "active", "credential_version": 2, "keys": [ { "kid": "…", "alg": "EdDSA", "public_key": "…", "status": "active" } ] } }
```
`404` if this backend does not own it.

### Payload rules

- Only routing data: keys, states, public keys, versions. **No profiles, telemetry, bookings, usernames, hostnames or other PII.**
- Responses are bounded (`limit`, max response size); `Cache-Control: no-store`.
- Backwards compatible, additive-only. `GET /internal/info` lists supported entities; unknown query parameters are ignored.

### Long-poll implementation

Held requests must not exhaust workers. Use async views (ASGI) or a dedicated worker pool for `/internal/sync/*`; wake-ups come from `NOTIFY` (5.4); drop the request when the client disconnects. Cost is one open request per Router stream.

## 8. Equipment moves

Backends are independent and never talk to each other, so a move is a **coordinated admin procedure**, enforced by the Router's ownership rules.

1. **Destination (`dept_b`):** an admin configures the equipment and starts *adopt key*: `POST /agent/enrollment-grants` with `adopt_kid=<kid>` and the public key copied from the source through an admin-to-admin channel (the public key is not secret; the **fingerprint is verified by a human**). `dept_b` creates `AgentIdentity(state=pending_approval)` with the adopted `AgentKey(status=next)` and publishes `equipment` and `agent_keys` for that equipment.
2. **Source (`dept_a`):** an admin marks the equipment `moved` (reason `moved`). `dept_a` publishes `equipment(state=moved)`, sets the identity to `decommissioned`, bumps `credential_version`, publishes `agent_keys(state=revoked)`, and answers `421` for that equipment from then on.
3. **Router:** claims from both backends are evaluated by the ownership rules; the new owner takes over once the old claim is `moved`/tombstoned and the new claim is live. A key claimed by two backends at once is a conflict, not a silent transfer.
4. **Device:** receives `421`, re-resolves through the Gateway (now `dept_b`), requests a token from `dept_b` with an assertion signed by the **same key** (identified by its `kid`). Possession of the private key is proven by that first valid assertion; an admin approves, the key becomes `active`.
5. Historical telemetry and events remain in `dept_a` (see O6). Bookings follow the equipment record.

No new secret is issued and the private key never moves. The `agent_uid` changes (it is local to a backend); the device does not need it to authenticate.

## 9. Security requirements

- Hash grants and sync tokens at rest. Constant-time comparison. Grants lock after `ENROLL_MAX_FAILED_ATTEMPTS`.
- Access-token signing key is a file (mode 600); support two keys by `kid` during rotation.
- `/internal/*` blocked at public Nginx and checked again in Django by source address and token.
- Per-agent rate limits on token and all agent endpoints; per-scope token checks; per-IP limits use the real client IP from `TRUSTED_PROXY_CIDRS` (otherwise they apply to the proxy).
- Allowlist-based filtering of telemetry fields; reject oversized or out-of-window records; treat all agent data as untrusted input (typed validation, never rendered as HTML).
- Redact tokens, grants, assertions and `Authorization` headers in logs and error reports; never put secrets in URLs.
- `agent_uid` is not a credential; an equipment UID is not a credential; neither is accepted alone for any action.
- Agent private keys are generated on the device and never transmitted, stored or displayed by the backend (6.1). Code review rejects any endpoint returning key material.
- TLS 1.2+ on every hop, including internal; HSTS on public endpoints; mTLS between Router and backends is recommended.
- Attestation verification, when used, runs against a maintained allowlist of trusted roots; failures are logged and counted.

### 9.1 Go-live checklist

| # | Item | Owner |
|---|---|---|
| 1 | Device-generated keys only; no key-bundle or key-download path exists (test asserts it) | Backend |
| 2 | Grant: hashed, single use, ≤ 60 min default, bound to agent and equipment, creator audited, locks after failed attempts | Backend |
| 3 | Pending and `pending_approval` identities cannot obtain any data scope | Backend |
| 4 | Assertion and access-token checks: `alg` pinned, canonical `aud`, `exp`, `jti` replay, clock skew, `cv` | Backend |
| 5 | Per-request server-side equipment resolution; cross-equipment test on every agent endpoint | Backend / QA |
| 6 | Revocation reaches the Gateway within the SLO (9.2), measured in staging | Backend / Edge / Gateway |
| 7 | Backend token-signing key: file mode 600, two `kid`s for rotation, rotation drill done | Ops |
| 8 | Restore runbook includes `rotate_sync_epoch`; restore drill done | Ops |
| 9 | Gateway release/config signing key off CI, approval per release (Gateway repo) | Gateway / Ops |
| 10 | Alerts: token failure spikes, revoked-agent traffic, unredeemed or locked grants, fingerprint mismatch, sync errors | Ops |
| 11 | Incident drill: revoke agent, rotate signing key, halt release, restore a backend | Ops |
| 12 | Independent security review / pen test of enroll, approve, token, rotate, sync paths | Security |

### 9.2 Revocation SLA

| Path | Target |
|---|---|
| Backend rejects the revoked agent's next request | < 1 s (NOTIFY), ≤ `REVOCATION_CACHE_TTL_S` worst case |
| `agent_keys` change visible at the Router | < 10 s at p99 (long-poll) |
| Gateway stops serving config and updates to the revoked agent | Router cache invalidation + Gateway cache TTL; total < 30 s at p99 |

Measure these in staging with a scripted revocation and keep the numbers in the release notes.

## 10. Observability

Metrics: `sync_requests_total{entity,status}`, `sync_longpoll_waiters`, `sync_full_responses_total{entity,reason}`, `sync_epoch_mismatch_total`, `changelog_rows`, `routing_entity_rows{entity}`, `enroll_total{result}`, `enroll_grants_locked_total`, `approvals_pending`, `token_issued_total{tier}`, `token_failures_total{reason}`, `key_rotations_total{result}`, `agent_requests_total{endpoint,status}`, `agent_ingest_records_total{kind}`, `agent_ingest_queue_depth`, `agent_version_count{version}`, `agents_stale`, `agent_clock_skew_seconds` (histogram), `booking_requests_total{status}`, `revocations_total`.

SLOs:

| SLO | Target |
|---|---|
| Token endpoint availability | 99.9% |
| Token endpoint latency | p99 < 300 ms |
| Agent ingest acceptance | 99.5% of valid requests succeed first try; accepted data visible < 60 s |
| Sync freshness | 99% of routing changes served to a polling Router < 2 s |
| Revocation | see 9.2 |

Alerts: changelog growth without pruning, token failure spikes, `approvals_pending` older than 24 h, locked grants, ingest queue depth, stale agent count, sync API errors, epoch mismatches, clock skew outliers, `RoutingEntity` verification failure (rebuild differs from live).

## 11. Testing

- Unit: version bumps only on routing-relevant changes (and **not** on inventory, metrics, events, state snapshots, bookings); transactional integrity of change + projection + log; bulk-method guard; projection rebuild equals live projection.
- Sync API: delta, full paging, `304`, long-poll timeout, `limit`/`has_more`, compaction (latest op per key), old-`since` fallback to full, epoch change, `since` greater than head, tombstones, digest equals Router's checksum, concurrency cap per token.
- Concurrency: concurrent writers produce strictly increasing, gap-free visible versions; reader never sees version *n+1* before *n*.
- Agent API: scope enforcement (own equipment only), idempotent retries, timestamp window, batch limits, allowlist filtering, `426` behavior, cardinality caps, event-monitoring schema/privacy and durable-acceptance behavior.
- Enrollment and keys: grant reuse, lockout, expired grant, proof canonicalization, wrong `backend_id`, `public_key_in_use`, unattested `tpm` claim rejected, approval flow, two-phase rotation with each step's response lost, rotation `next` expiry.
- Auth: replay of `jti`, wrong `aud`, `alg` confusion, stale `cv`, revoked agent, cross-backend token, missing scope, clock skew with server-time hint.
- Revocation: measured propagation to a stub Router and Gateway within the SLA.
- Booking: window limits, ETag/`304`, no cross-equipment access.
- Compatibility: an old recorded agent request set replays successfully (additive-only guarantee).
- Move scenario: adopt key at the destination, `moved` at the source, `421`, conflict handling, both arrival orders.
- Disaster recovery: restore a backend database, run `rotate_sync_epoch`, verify the Router performs a full resync; verify that skipping the step is caught by version regression detection.
- Prefix: URLs generated with `FORCE_SCRIPT_NAME`; cookies do not collide across backends; assertion `aud` stays correct behind Nginx.
- Load: token endpoint and ingest at fleet size with jittered clients; long-poll connections per Router.

## 12. Migration checklist for existing LabMango

1. Add models and migrations (`SyncState` with `epoch`, `RoutingChange`, `RoutingEntity`, `AgentIdentity`, `AgentKey`, grants, audit, telemetry tables, agent-owned computing fields and `state_collected_at`).
2. Introduce the service layer (`publish_routing`) and refactor routing-relevant writes to use it; add the bulk-write CI guard and `rebuild_routing_projection`.
3. Add `user_key` to users and backfill from SSO or employee ID. Backfill `RoutingEntity` for existing users and agent-enabled equipment.
4. Create the `agent_api` package with auth, permissions, throttles; add `/internal` sync endpoints. Do not introduce feature flags unless the repository's feature-flag policy is revised.
5. Provision the telemetry store and retention jobs (O8) and the nonce store.
6. Make agent-owned computing fields read-only in the user API.
7. Configure prefix, cookies, `AGENT_PUBLIC_BASE_URL`, trusted proxies and the Nginx block (including the agent rate-limit zone) for the department.
8. Add `rotate_sync_epoch` to the database restore runbook.
9. Register the backend in `backends.yml` (Edge repo) and verify sync end to end.

## 13. Implementation plan

### 13.1 Decide before coding

1. **O8 telemetry store** (TimescaleDB vs PostgreSQL partitioning). Determines the `MetricSample` model and retention jobs.
2. **O6 move history** (default: stays in the old backend).
3. **Key policy per department:** minimum verified tier, whether approval is mandatory, TTLs. Attestation support (TPM) is an option; software keys with approval is the minimum.
4. **`user_key` source**: SSO subject, employee ID or normalized email. Backfill plan for existing users.
5. **Async deployment**: ASGI server or dedicated worker pool for long-poll endpoints; `LISTEN/NOTIFY` listener design.
6. **Agent-owned fields**: confirm the list and make them read-only in the user API; decide where `os_version` lives (a documented `system_info` key or a new field).
7. **Nonce store**: Redis or table.

### 13.2 Milestones

| # | Milestone | Deliverables | Done when |
|---|---|---|---|
| M1 | Routing core | `SyncState` + `epoch`, `RoutingChange`, `RoutingEntity`, `publish_routing`, service layer, `user_key` + backfill, bulk-write CI guard, projection rebuild command | Version bumps on routing changes only; ordering and transactional tests pass |
| M2 | Sync API | `/internal/info`, `/internal/sync/{users,equipment,agent_keys}` (delta with `limit`/`has_more`, paged full with snapshot version, `304`, long-poll with `NOTIFY`, epoch handling), `/internal/digest/{entity}`, `/internal/equipment/{uid}`, token auth with rotation | Stub router (13.4) completes snapshot + catch-up + live cycles, survives an epoch change, and its digest matches |
| M3 | Agent identity | `agent_api` package; `enrollment-grants`, `enroll` (proof JWS, attestation hook, approval), `approve`, `token` (kid-based), `rotate` (two-phase), revocation with `credential_version`, `heartbeat`, `ping`, `info`; audit | Stub agent enrolls, is approved, gets a token, rotates with a lost response, is revoked; replay, wrong-`aud` and stale-`cv` tests pass |
| M4 | Telemetry and state | `equipment/state`, `inventory`, `metrics`, event-monitoring push (`events`); queue/durable acceptance and bulk insert workers; latest-snapshot tables; retention and rollup jobs; event/field allowlists and metric cardinality caps; limits | 1,000 batches replayed twice produce no duplicates; event ownership and privacy tests pass; routing version unchanged |
| M5 | Bookings | `GET /agent/bookings` with window, ETag, scoping, optional long-poll | Cross-equipment access impossible (tested); `304` on unchanged |
| M6 | Hardening | Prefix and cookies, trusted proxies, Nginx rate-limit zone for `/agent`, metrics, SLO dashboards and alerts, `openapi/agent.yml` and `openapi/sync.yml`, compatibility replay tests, restore drill, revocation SLA measurement, runbook notes | All acceptance criteria below pass |

Each milestone is independently releasable; deployment gating must follow the repository's approved release policy.

### 13.3 Acceptance criteria

- [ ] Changing `last_seen_at`, inventory, metrics, events, state snapshots or bookings never changes `SyncState`.
- [ ] Creating, deleting or moving equipment bumps `equipment` exactly once, atomically with the change and its projection and log rows; credential changes bump only `agent_keys`.
- [ ] Versions become visible in order with no gaps under concurrent writers (test).
- [ ] `since` older than retained history, an unknown `epoch`, or `since` above head returns full mode; `since == head` returns `304` after at most `wait` seconds; deltas honor `limit` and `has_more`.
- [ ] A full snapshot followed by a delta from `snapshot_version` equals the live state, even with writes during paging (test).
- [ ] Tombstones are delivered for deletes and moves; `RoutingEntity` rebuild equals live projection.
- [ ] `/internal/*` is unreachable through the public prefix, and refused without a valid sync token.
- [ ] An agent token for `dept_a` is rejected by `dept_b` (`aud` check).
- [ ] A grant works once; an expired, reused or locked grant returns `403` with an identical body.
- [ ] A claimed `tpm` tier without verified attestation is treated as `software` and cannot skip approval.
- [ ] Two-phase rotation never locks out the device, even if any single response is lost.
- [ ] Replayed assertion (`jti`) is rejected; tokens with an old `cv` are rejected immediately after revocation.
- [ ] Revocation meets the SLA in 9.2 in staging.
- [ ] `421` is returned for equipment/agent identity no longer owned here; `426` for a too-old agent.
- [ ] Booking endpoint returns only the authenticated agent identity's linked equipment and only `user_key` for users.
- [ ] Duplicate telemetry and monitoring events are idempotently ignored using database-backed keys; unknown metric/event types, disallowed event fields, and excess metric cardinality are rejected.
- [ ] The agent can push bounded monitoring-event batches; each persisted event has server-derived agent/equipment ownership, occurred/received timestamps, an immutable event ID, and no effect on booking state or `SyncState`.
- [ ] Records outside the timestamp window or over the batch limits are rejected with clear errors; stale state snapshots never overwrite newer ones.
- [ ] URLs are generated with the prefix; cookie names do not collide across departments; assertion `aud` is correct behind Nginx.
- [ ] A restored database with `rotate_sync_epoch` forces a clean Router resync; without it the Router still detects the regression.
- [ ] An old recorded set of agent requests still passes after every change (additive-only guarantee).

### 13.4 Stubs for independent development

- **Stub router** (`tools/stub_router.py`): implements snapshot + catch-up + long-poll with epoch and digest checks for all three entities, using the sync token; applies deltas with per-key versions; prints lag and conflicts. Includes fault modes: lost response, restart mid-snapshot, epoch change.
- **Stub agent** (`tools/stub_agent.py`): generates a key pair, enrolls with a grant (and confirms approval), requests tokens by `kid`, posts state, inventory, metrics and buffered monitoring-event batches (including retry/replay), reads bookings, rotates keys (with lost-response mode), and handles `421`. Fault options: replay, wrong audience, stale `cv`, oversized/invalid event batch, duplicate event IDs, old timestamps, clock skew.
- **Stub gateway** (`tools/stub_gateway.py`): consumes `agent_keys` through the stub router and measures revocation propagation.
- Use these in CI as integration tests.

### 13.5 Out of scope for this repo

Router logic (see the router sync service spec), Nginx generation (Edge repo), config and update delivery (Gateway), agent behavior (agent design spec). This repo only honors the contracts above.

# Part B. Shared contracts and context

## B1. Security formats used by this backend

#### Enrollment grant

Opaque random string, 256-bit (`eg_` + base64url). Stored as SHA-256 hash with `expires_at`, `used_at`, `revoked_at`, `locked_at`, `failed_attempts` and the bound `agent_uid` and `equipment_id`. Redeemed once with a proof-of-possession JWS (6.2). It is a bootstrap ticket, not a key: it carries no data scope and is useless after redemption.

#### Key thumbprint (`kid`)

`kid = base64url( SHA-256( DER-encoded SubjectPublicKeyInfo ) )`. The backend recomputes it from the submitted public key and never trusts a client-provided `kid`.

#### Agent assertion (JWT, EdDSA or ES256)

```
header:  { "alg": "EdDSA" | "ES256", "typ": "JWT", "kid": "<thumbprint>" }   # alg must equal the registered alg
claims:  { "iss": "<kid>", "sub": "<kid>", "aud": "<AGENT_PUBLIC_BASE_URL>/agent/token",
           "iat": 1762335000, "exp": 1762335060, "jti": "<uuid>" }
```
Lifetime ≤ 60 s. `jti` single-use.

#### Backend access token (JWT, EdDSA)

```
header:  { "alg": "EdDSA", "typ": "JWT", "kid": "be-dept_a-2026-01" }
claims:  { "iss": "dept_a", "sub": "<agent_uid>", "aud": "dept_a",
           "scope": "inventory:write telemetry:write activity:write bookings:read bookings:end_time:write bookings:complete",
           "cv": 2, "iat": …, "exp": … (≤ tier TTL), "jti": "<uuid>" }
```

#### Backend token key rotation

Add the new `kid` (backend verifies both) → start signing with the new one → wait one token TTL → drop the old one.

### Anti-clone strategy

- Fingerprint = hash of stable hardware identifiers plus install id. It is **not** the identity; it is a consistency check.
- The agent verifies the fingerprint on start; mismatch stops the agent.
- The backend compares the fingerprint at enroll and token issue; mismatch returns `403 fingerprint_mismatch` and alerts.
- The Router raises a conflict if the same equipment UID or the same key `kid` is claimed by two backends.
- Equipment UIDs are tombstoned and never reused. Agent UIDs and key thumbprints are never reused.

## B2. Context

### What the Edge router does with the sync API (for context)

- One task per `(backend, entity)`: starts with a **snapshot** (paged full into a staging table), merges it atomically, then **catches up** with deltas from `snapshot_version`, then stays **live** with long-polls (`since`, `epoch`, `limit`, `wait`).
- Verifies `backend_id` and `epoch` in each response. Epoch change, `head_version` below its cursor, or a `409` triggers a new snapshot. Responses are schema-validated before anything is written.
- Applies deltas idempotently with per-key versions; the cursor moves in the same transaction as the data, protected by a fencing token.
- Compares `/internal/digest/{entity}` with its own checksum periodically; a mismatch triggers a resync. Runs a nightly full resync as a backstop.
- Never purges a backend's entries when the backend is unreachable.
- Computes ownership from per-backend claims; keeps a conflict (and does not overwrite) if two live backends claim one key.
- For unknown equipment UIDs, calls `GET /internal/equipment/{equipment_uid}` on enabled backends with a short timeout and a negative cache.

Implication for this repo: versions must be monotonic and visible in order, epochs must be rotated after restores, deltas and snapshots must be bounded and exact, and the API must tolerate one held long-poll per entity per Router.

### What the agent does against this API (for context)

- Enrolls once with a grant, shows a fingerprint code, and (when required) waits for approval; then requests tokens with a signed assertion identified by the key thumbprint and renews before expiry or on `401`.
- Sends the state snapshot on change, inventory on change, metrics every 30 s to 5 min, and monitoring events in bounded batches. It persists each event ID and the pending batch in its local outbox before sending, retries with stable IDs, and removes acknowledged events only after a successful response.
- Reacts to responses: `401` re-assert, `421` re-resolve through the Gateway, `403` stop pushing, `426` update now, `429` honor `Retry-After`, `5xx` backoff with jitter.
- Rotates its key in two phases and never loses access if a response is lost.
- Reads bookings every 1 to 5 minutes with `If-None-Match`, caches them with `valid_until`, and applies an offline policy from its config.
- Sends `X-Agent-Version` on every call.
