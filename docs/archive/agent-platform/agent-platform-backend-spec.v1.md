# Agent Platform Backend Spec: LabMango per-department backend

Status: Historical draft 1.0 · superseded · retained for traceability only
Archive location: `docs/archive/agent-platform/agent-platform-backend-spec.v1.md`

> **Do not implement from this draft.** Start at the [agent-platform reading guide](../../README.md#agent-platform-start-here).
> The working [backend proposal](../../backend-agent-api-spec.md) replaces this document; its routing portions
> are themselves superseded by the [routing-sync design](../../backend-routing-sync-spec.md). Historical claims below
> about standalone implementation authority, equipment routing, credentials and deployment are not current guarantees.

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
| `agent_uid` | Server-generated UUID of one enrolled agent credential. Distinct from equipment `uid`, never derived from it, never a routing key, never a credential |
| Equipment `uid` | Existing LabMango equipment resource UUID; identifies the equipment record, not necessarily an agent installation |
| `user_key` | Stable user identity (SSO subject, employee ID or normalized email), never a local integer ID |
| Prefix | Public path of a backend, e.g. `/api/dept_a/`. Nginx strips it before the backend sees the request |
| Route | `{backend_id, base_url, prefix, auth, ttl, version}` |
| Version | Monotonic per-backend, per-entity-type counter. Changes only on routing-relevant changes |
| Grant | One-time enrollment token issued by a backend admin |
| Agent assertion | Short-lived JWT signed by the enrolled agent's private key |
| `kid` | Key id; two keys are trusted during rotation |

### Decisions (fixed)

D1 one backend per department, one shared frontend · D2 `backend_id` immutable · D3 Edge = Nginx + router in its own repo · D4 Edge **pulls** from backends; backends never call out · D5 version counter + change log with tombstones; bump only for routing-relevant changes · D6 Gateway is multi-app, depends on Edge one-way · D7 agents push directly to backends · D8 enrolled-agent identity = a key pair **generated on the device** (private key never leaves it) plus a server-issued `agent_uid`, linked to exactly one equipment record; equipment `uid` is the only routing key; public key flows through sync · D9 no secret travels Backend → Edge → Gateway, and no agent private key travels anywhere; backends issue short-lived per-agent tokens for a signed assertion · D10 config and manifests are signed (Ed25519, `kid`); agents keep last-known-good and roll back · D11 no secret manager; secrets are files / Docker or systemd secrets · D12 agents cache their route and keep working if Gateway or Edge is down.

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
3. A dedicated **agent API**: enrollment, per-agent tokens, agent-reported computing state (OS information, IP address, system information and disk usage), telemetry intake, and scoped booking access for the equipment associated with the authenticated agent.
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
SYNC_LONGPOLL_MAX_S = 30
CHANGELOG_RETENTION_DAYS = 30

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

### 4.1 Identity and routing

```
SyncState(entity_type PK [users|equipment], version BIGINT)

RoutingChange(id, entity_type, version, key, op [upsert|delete], created_at)
  index (entity_type, version)

AgentIdentity(agent_uid UUID PK (server-generated), equipment_id FK, public_key NULL (SPKI),
    public_key_sha256 UNIQUE NULL, alg [EdDSA|ES256], key_storage [tpm|os_keystore|software],
    fingerprint NULL, state [pending|active|revoked|decommissioned], replaces_agent_uid NULL,
    agent_version, last_seen_at, enrolled_at, key_rotated_at, created_by)
  partial unique (equipment_id) WHERE state IN ('pending', 'active') # one live enrollment/agent per equipment

EnrollmentGrant(id, token_hash UNIQUE, agent_uid FK, equipment_id FK,
  expires_at, used_at NULL, revoked_at NULL, created_by)
AgentToken(jti PK, agent_uid, issued_at, expires_at, revoked_at NULL) # for revocation
AssertionNonce(jti PK, agent_uid, expires_at)                         # replay protection
```

`AgentIdentity` links to the existing `Equipment` model through `equipment_id`. Identifier roles are fixed:

| Identifier | Generated by | Used for | Never used for |
|---|---|---|---|
| Equipment `uid` | Backend (existing) | Edge routing key, sync key | Authentication |
| `agent_uid` | Backend, when an admin creates a pending agent | Token `sub`, audit, revocation | Routing, authentication on its own |
| Public key | Agent device | Verifying assertions; published through sync | Routing key (it changes on rotation) |
| Private key | Agent device, non-exportable where possible | Signing assertions | Ever leaving the device |

Cardinality: at most one `pending` or `active` identity per equipment (DB partial unique constraint). An expired/revoked pending enrollment does not block a new grant; replacement of an active identity is explicit (6.2). The linked equipment record scopes every read and write.

User entity: the existing user model plus a stable `user_key` (SSO subject, employee ID or normalized email). **Never use the local integer ID as the routing key.**

### 4.2 Telemetry

```
AgentInventory(agent_uid PK, content_hash, data JSONB, collected_at, updated_at)   # latest snapshot only
AgentInventoryHistory(agent_uid, content_hash, data JSONB, valid_from)              # optional, changes only

AgentLatestMetrics(agent_uid PK, data JSONB, sampled_at)                            # for UI lists

MetricSample(agent_uid, ts, name, value DOUBLE, labels JSONB)                     # time series
  unique (agent_uid, ts, name, labels_hash)                                        # idempotency
  -- TimescaleDB hypertable on ts, if available (see O8)

AgentEvent(agent_uid, ts, type, data JSONB, booking_id NULL, idempotency_key)       # append-only
  unique (agent_uid, idempotency_key)
```

Telemetry tables are **outside** the routing change-log rule: bulk writes are allowed there.

### 4.3 Bookings

The agent uses the existing booking models. No new booking tables are needed. The agent endpoint is a scoped read through the booking service (see 6.6).

## 5. Version counter and change log

### 5.1 What bumps the version

| Entity | Bump on |
|---|---|
| `users` | create, delete or deactivate, `user_key` change |
| `equipment` | create, delete, equipment `uid` change, routing-state change, linked public-key change, department move |

**Never bump** for any of the following: `last_seen_at`, heartbeat, inventory, metrics, events, booking changes, or other business edits. This is the most important rule: otherwise the Edge refetches constantly.

### 5.2 Transactional guarantee

The version increment and the `RoutingChange` row are written **in the same DB transaction** as the entity change.

```python
@transaction.atomic
def upsert_agent_identity(**fields):
  identity = AgentIdentity.objects.update_or_create(
    agent_uid=fields["agent_uid"], defaults=fields
  )[0]
  record_change("equipment", key=str(identity.equipment.uid), op="upsert")
  return identity

def record_change(entity, key, op):
    state = SyncState.objects.select_for_update().get(entity_type=entity)
    state.version += 1
    state.save(update_fields=["version"])
    RoutingChange.objects.create(entity_type=entity, version=state.version, key=key, op=op)
```

### 5.3 Rules to keep it reliable

- Route **all** writes of routing-relevant fields through a service layer (the functions above). Django signals miss `bulk_create`, `bulk_update` and `queryset.update()`.
- Add a CI test that fails if code calls those bulk methods on routing models outside the service layer.
- Optional safety net: a DB trigger on the routing tables that writes `RoutingChange`.
- Use a monotonic integer counter, never a timestamp.
- Prune `RoutingChange` older than `CHANGELOG_RETENTION_DAYS`. A client asking for `since` older than the oldest retained version receives **full** mode.

### 5.4 Wake-up for long-poll

After commit, the service notifies local waiters (Postgres `LISTEN/NOTIFY` or an in-process condition). This is internal to the backend and involves no external system.

## 6. Agent API (`/agent/...`)

Publicly: `/api/dept_a/agent/...`. Paths below are as the backend sees them.

### 6.0 Common rules

| Rule | Detail |
|---|---|
| Auth | `Authorization: Bearer <agent access token>` (except the explicitly protected enrollment/bootstrap flow). No cookies, no CSRF. An equipment UID in a custom header is never authentication or authorization |
| Scope | The token's `sub` (`agent_uid`) resolves to one `AgentIdentity` and its linked equipment. Every read and write is limited to that equipment |
| Capability scopes | Token `scope` claim: `inventory:write`, `telemetry:write`, `activity:write`, and `bookings:read`. `activity:write` is for reporting observed computing activity only. The proposed booking-completion action requires a separate owner-approved `bookings:complete` scope; it is not yet enabled |
| Headers | `X-Agent-Version`; `Idempotency-Key` on retryable writes; `X-Seq` only where ordered processing is required. An optional equipment UID header is a consistency check against the equipment resolved from the token, never a selector or credential |
| Errors | `{"error": "...", "message": "...", "request_id": "..."}` |
| Status codes | `401` token expired → re-assert; `403` revoked or scope missing; `421` equipment/agent identity not owned here; `426` agent too old; `429` rate limited (`Retry-After`); `413` too large |
| Throttle | Per agent identity, separate scope per endpoint group |
| Logic | Views authenticate, validate, scope, call the service layer, serialize. No business logic |

Package layout:

```
agent_api/
  auth.py          # AgentTokenAuthentication (verifies EdDSA token, aud, scope) -> request.agent_identity
  permissions.py   # HasScope, OwnsEquipment
  throttles.py     # PerAgentThrottle
  views/           # enroll, token, equipment-state, inventory, metrics, events, bookings, heartbeat, info
  serializers/
  urls.py
services/          # shared with the user API: agent identities, telemetry ingest, bookings
openapi/agent.yml  # the contract, with contract tests
```

### 6.1 Credential model (fixed)

**The backend never generates, stores, displays or transmits an agent private key.** The private key is generated on the device and never leaves it. The backend only ever receives and stores the public key.

```
 Admin (UI) ──1 create pending agent──▶ Backend: AgentIdentity(state=pending) + EnrollmentGrant (hash only)
 Admin ──2 grant via installer prompt / trusted channel──▶ Device
 Device: 3 generate key pair in TPM / OS keystore (non-exportable)
 Device ──4 POST /agent/enroll {grant, public_key, proof}──▶ Backend: verify, bind key, state=active
 Device ──5 POST /agent/token {assertion signed by device key}──▶ Backend ──▶ short-lived access token
 Device ──6 data calls with Bearer token──▶ Backend resolves sub ─▶ AgentIdentity ─▶ equipment (server-side)
```

Key storage tiers (record in `AgentIdentity.key_storage`; departments decide the minimum accepted tier):

| Tier | Where | Use |
|---|---|---|
| `tpm` | TPM 2.0 / secure enclave, non-exportable | Preferred default |
| `os_keystore` | Windows CNG/DPAPI (machine scope), macOS Keychain, Linux kernel keyring or root-only file | Acceptable |
| `software` | Key file, mode 600, service account only | Only with department approval; shorter token TTL |

Forbidden: backend-generated key pairs, downloadable key bundles, private keys in email/tickets/browsers, any endpoint that issues a credential based on an equipment UID or `agent_uid` alone, shared keys across devices.

### 6.1.1 Create pending agent (admin)

`POST /agent/enrollment-grants` (user-API auth; role `lab_admin` or equipment owner, object-scoped to the equipment)
```json
{ "equipment_uid": "3d52…", "ttl_minutes": 60, "replace_active": false }
```
In one transaction: create `AgentIdentity(state=pending, agent_uid=<server UUIDv4>)` and an `EnrollmentGrant` bound to that `agent_uid` and equipment. Response `201` (grant shown once, never retrievable again):
```json
{ "agent_uid": "7b1f4c2e-…", "grant": "eg_Zk3…", "expires_at": "2026-11-05T10:30:00Z" }
```
Rules: default TTL 60 min, max `ENROLL_GRANT_TTL_H`; grant stored as SHA-256 only; creator audited; admin can revoke an unredeemed grant; expired pending identities are cleaned up and alerted. `409` if the equipment already has an active agent and `replace_active` is false.

### 6.2 Enroll (device, one time)

`POST /agent/enroll` (no Bearer; protected by grant + proof of possession; strict per-IP and per-grant rate limit)
```json
{
  "grant": "eg_Zk3…",
  "public_key": "base64url(SPKI)",
  "alg": "EdDSA",
  "key_storage": "tpm",
  "fingerprint": "sha256:…",
  "agent_version": "1.4.2",
  "proof": "base64url( sign(sk, \"labmango-enroll-v1\" || backend_id || sha256(grant) || public_key) )"
}
```
The backend derives `agent_uid` and equipment from the grant and returns them in the response; the request cannot choose either.

Checks, in one transaction with `select_for_update` on the grant: grant exists, unused, unrevoked, unexpired; identity is `pending`; `proof` verifies against `public_key` with the declared `alg`; `public_key_sha256` not used by any other identity; `key_storage` meets the department minimum. Then: store public key, set `state=active`, mark grant used, revoke the replaced identity if `replace_active`, record the equipment routing change (key = equipment `uid`).

Optional high-assurance mode (department setting): enrollment ends in `pending_approval`; the device shows the public-key fingerprint and the admin confirms the same fingerprint in the UI before activation. This defeats a stolen-grant race.

Response `201`:
```json
{
  "agent_uid": "7b1f4c2e-…",
  "equipment_uid": "3d52…",
  "backend_id": "dept_a",
  "base_url": "https://lab.example.com/api/dept_a/",
  "auth": { "method": "agent_assertion", "token_endpoint": "https://lab.example.com/api/dept_a/agent/token" }
}
```
Errors: `400 invalid_proof`, `403 grant_invalid` (same response for unknown, used, expired or revoked, to avoid an oracle), `409 public_key_in_use`, `422 key_storage_not_allowed`.

### 6.2.1 Key rotation, recovery, revocation

- **Rotation** `POST /agent/keys/rotate` (Bearer): body `{new_public_key, alg, key_storage, proof_new}` where `proof_new` is signed by the new key over `"labmango-rotate-v1" || agent_uid || new_public_key`. The call itself is authenticated by the old key's token. Atomic swap; old key rejected immediately; routing change recorded. Recommended every 90 days for `software` tier, yearly otherwise.
- **Recovery** (device rebuilt, key lost): admin creates a new grant with `replace_active=true`. A new `agent_uid` is issued; the old identity becomes `revoked`. Keys are never recovered or exported.
- **Revocation** (admin): `state=revoked`, all outstanding `AgentToken` rows marked revoked, auth cache invalidated, effective on the next request.

### 6.2.2 Request authentication and scoping

```python
class AgentTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        claims = verify_access_token(request)        # EdDSA, kid, aud == BACKEND_ID, exp, jti not revoked
        agent = get_active_agent(claims["sub"])      # short cache (<= 60 s), invalidated on change
        if agent is None:
            raise AuthenticationFailed("agent_not_active")
        request.agent_identity = agent               # carries equipment_id, resolved server-side
        return (AgentPrincipal(agent), claims)
```

- The token carries `sub` and `scope` only, never `equipment_id`. Equipment is resolved per request from `AgentIdentity`, so relink or revocation applies immediately.
- No agent endpoint accepts an equipment or computing id. Such fields in body or query are rejected (`422`). `X-Equipment-UID`, if sent, is only compared with the resolved equipment.
- Service functions take `equipment_id` as a trusted argument from the auth layer and always filter by it.
- Booking-linked events are accepted only if the booking belongs to the same equipment, otherwise `403`.
- Equipment field projection (for example `os_name`) uses a fixed server-side allowlist; everything else is stored only as agent inventory.

### 6.3 Token

`POST /agent/token` with `{ "assertion": "<JWT EdDSA>" }`.

Assertion claims: `iss=sub=<agent_uid>`, `aud=<token endpoint URL>`, `iat`, `exp` (≤ 60 s after `iat`), `jti`.

Checks: agent identity exists and `state == active` (else `403`, or `421` if its equipment/ownership has moved), header `alg` equals the registered `alg` (no `none`, no algorithm switching), signature valid with stored public key, `aud` equals this endpoint, `iat` within ±60 s of server time, `jti` unused (`AssertionNonce`, kept until `exp`), fingerprint matches if provided. Rate limit per `agent_uid` and per IP.

Response `200`:
```json
{ "access_token": "<JWT EdDSA signed by backend key>", "token_type": "Bearer", "expires_in": 3600,
  "scope": "inventory:write telemetry:write activity:write bookings:read" }
```
Access token claims: `iss=dept_a`, `sub=<agent_uid>`, `aud=dept_a`, `scope`, `iat`, `exp`, `jti`, `kid` header. The backend checks `aud == BACKEND_ID` on every call. No refresh token: the agent re-asserts with its enrolled private key.

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
#### `POST /agent/events` (scope `activity:write`; timestamped computing activity such as session/job lifecycle)
```json
{ "batch_id": "…",
  "events": [ { "id": "e-001", "ts": "2026-11-05T13:02:11Z", "type": "session_started",
                "booking_id": "b-9912", "data": { "user_key": "e12345" } } ] }
```

Common behavior for the three:
- Validate size (`AGENT_MAX_BODY_BYTES`), count (`AGENT_MAX_BATCH_RECORDS`), timestamp window (reject older than `AGENT_TS_MAX_PAST_H` or later than `AGENT_TS_MAX_FUTURE_S` ahead), and field allowlists (see privacy below).
- Idempotent: duplicate `Idempotency-Key`, `(agent_uid, ts, name, labels)` or `(agent_uid, event id)` are ignored. Response `202 {"accepted": n, "duplicates": m}`.
- Writes go to a queue and are inserted in bulk by workers; the view answers fast.
- Each accepted batch updates `AgentIdentity.last_seen_at` and `AgentLatestMetrics`, **never** `SyncState`.
- Events with a `booking_id` are linked to the booking in the service layer. The booking endpoint itself stays read-only.

Privacy: the allowed inventory and event fields are defined in a server-side allowlist (hostname, OS, hardware, usernames only if required). Anything outside it is dropped. The Gateway config can switch categories off per department. Activity events are append-only observations; associating an event with a booking does not grant permission to modify that booking.

### 6.6 Retention and rollups

| Data | Retention | Mechanism |
|---|---|---|
| Raw metric samples | `METRICS_RAW_RETENTION_DAYS` | Drop old chunks / scheduled delete |
| 5-minute rollups | `METRICS_ROLLUP_RETENTION_DAYS` | Continuous aggregate or scheduled job |
| Events | `EVENTS_RETENTION_DAYS` | Scheduled delete |
| Inventory history | Keep changes only, policy per department | Scheduled delete |
| Latest snapshots | While the associated equipment/agent identity exists | n/a |

### 6.7 Bookings (read-only baseline)

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

**Booking updates are not authorized by equipment UID.** The owner has specified one candidate action: an agent may report completion only for a booking that is currently `in_progress`, following the existing bench-booking completion/lifecycle logic. This does not authorize schedule/detail edits or arbitrary status changes. Implementation remains blocked until a machine credential other than the equipment UID and the `bookings:complete` scope are approved; the UID can only identify or cross-check the equipment after authentication. Once approved, completion must use a dedicated narrowly scoped action and the booking feature's application command, re-check current state atomically, be retry-safe and auditable, and preserve booking concurrency guards. Agents must not directly PATCH booking rows or write `status`/`approval_status`.

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
  "capabilities": ["equipment_state_write", "inventory", "metrics", "computing_activity", "bookings_read"],
  "limits": { "max_batch_records": 500, "max_body_bytes": 1000000 },
  "min_agent_version": "1.2.0" }
```

## 7. Sync API (`/internal/...`, read-only, Edge only)

Authentication: `Authorization: Bearer <sync token>`; constant-time comparison against hashed tokens. Not routable from public Nginx; reachable only from the Router's address.

### `GET /internal/info`
```json
{ "backend_id": "dept_a", "versions": { "users": 45, "equipment": 128 },
  "entities": ["users", "equipment"] }
```

### `GET /internal/sync/{entity}?since={n}&wait={s}`

`entity` is `users` or `equipment`. `wait` (0 to `SYNC_LONGPOLL_MAX_S`) holds the request until the version exceeds `since` or the time expires.

| Status | Meaning |
|---|---|
| `304` | No change (after `wait` seconds at most) |
| `200` delta | Changes after `since` |
| `200` full | `since` unknown or older than retained history |
| `401/403` | Bad token |

Delta example:
```json
{
  "backend_id": "dept_a", "entity_type": "equipment", "version": 131, "mode": "delta",
  "changes": [
    { "version": 129, "op": "upsert", "key": "7b1f4c2e-…",
      "data": { "state": "active", "public_key": "base64url…", "fingerprint": "sha256:…" } },
    { "version": 130, "op": "delete", "key": "0c9a…" },
    { "version": 131, "op": "upsert", "key": "3d52…",
      "data": { "state": "revoked", "public_key": "…", "fingerprint": "…" } }
  ]
}
```
Full example:
```json
{ "backend_id": "dept_a", "entity_type": "users", "version": 45, "mode": "full",
  "items": [ { "key": "e12345", "data": { "state": "active" } } ] }
```

Notes:
- Only routing data (key, state, public key, fingerprint). **No profiles, no telemetry, no bookings, no PII beyond the key.**
- Large full responses are paginated (`items` + `next_cursor`); the version is the one at the start of a `REPEATABLE READ` snapshot.
- Deletes are tombstones in `changes`.

### `GET /internal/equipment/{equipment_uid}`

Single lookup used by the Router for unknown equipment UIDs.
- `200` `{ "equipment_uid": "…", "state": "active", "public_key": "…", "fingerprint": "…" }`
- `404` not found here.

### Long-poll implementation

Held requests must not exhaust workers. Use async views (ASGI) or a dedicated worker pool for `/internal/sync/*`. Cost is one open request per backend per entity type.

## 8. Equipment moves

Moving equipment from `dept_a` to `dept_b`:
1. Admin configures the equipment in `dept_b` and associates the approved agent identity/public key. `dept_b` records an equipment `upsert`.
2. `dept_a` marks its routing ownership inactive with reason `moved`, records a `delete` (tombstone), and answers `421` for that equipment key from then on.
3. Router sync applies both. The Router accepts `dept_b` as new owner because the previous owner is tombstoned.
4. Historical telemetry and events remain in `dept_a` (see O6). Bookings follow the equipment record.

The agent authenticates to `dept_b` with the approved existing key association. No new secret is issued.

## 9. Security requirements

- Hash grants and sync tokens at rest. Constant-time comparison.
- Access-token signing key is a file (mode 600); support two keys by `kid` during rotation.
- `/internal/*` blocked at public Nginx and checked again in Django by source address and token.
- Per-agent rate limits on token and all agent endpoints; per-scope token checks.
- Allowlist-based filtering of telemetry fields; reject oversized or out-of-window records.
- Redact tokens, grants and assertions in logs and error reports.
- Revocation: revoking an agent identity denies its active `jti`s and returns `403` immediately. Whether that action also changes the equipment routing state/version must be specified separately; agent credential lifecycle and equipment lifecycle are not interchangeable.
- Agent private keys are generated on the device and never transmitted, stored or displayed by the backend (6.1). Code review rejects any endpoint returning key material.
- TLS 1.2+ on every hop, including internal; HSTS on public endpoints.
- Agent data is untrusted input: typed validation, range and timestamp checks, never rendered as HTML.

### 9.1 Go-live checklist

| # | Item | Owner |
|---|---|---|
| 1 | Device-generated keys only; no key-bundle or key-download path exists (test asserts it) | Backend |
| 2 | Grant: hashed, single use, ≤ 60 min default, bound to agent and equipment, creator audited | Backend |
| 3 | Pending identities cannot obtain data scopes; only `enroll` accepts them | Backend |
| 4 | Assertion and access-token checks: `alg` pinned, `aud`, `exp`, `jti` replay, clock skew | Backend |
| 5 | Per-request server-side equipment resolution; cross-equipment test on every agent endpoint | Backend / QA |
| 6 | Backend token-signing key: file mode 600, two `kid`s for rotation, rotation drill done | Ops |
| 7 | Gateway release/config signing key off CI, approval per release (Gateway repo) | Gateway / Ops |
| 8 | Alerts: token failure spikes, revoked-agent traffic, unredeemed grants, fingerprint mismatch | Ops |
| 9 | Incident drill: revoke agent, rotate signing key, halt release | Ops |
| 10 | Independent security review / pen test of enroll, token, rotate paths | Security |

## 10. Observability

Metrics: `sync_requests_total{entity,status}`, `sync_longpoll_waiters`, `changelog_rows`, `enroll_total{result}`, `token_issued_total`, `token_failures_total{reason}`, `agent_requests_total{endpoint,status}`, `agent_ingest_records_total{kind}`, `agent_ingest_queue_depth`, `agent_version_count{version}`, `agents_stale` (not seen for `STALE_AGENT_AFTER_S`), `booking_requests_total{status}`.

Alerts: changelog growth without pruning, token failure spikes, ingest queue depth, stale agent count, sync API errors.

## 11. Testing

- Unit: version bumps only on routing-relevant changes (and **not** on inventory, metrics, events, bookings); transactional integrity; bulk-method guard.
- Sync API: delta, full, `304`, long-poll timeout, old-`since` fallback to full, tombstones.
- Agent API: scope enforcement (own equipment only), idempotent retries, timestamp window, batch limits, allowlist filtering, `426` behavior.
- Booking: window limits, ETag/`304`, no cross-equipment access.
- Security: replay of `jti`, wrong `aud`, expired or reused grant, revoked agent identity, cross-backend token, missing scope.
- Compatibility: an old recorded agent request set replays successfully (additive-only guarantee).
- Move scenario: new owner upsert, old owner tombstone, `421` behavior.
- Prefix: URLs generated with `FORCE_SCRIPT_NAME`; cookies do not collide across backends.

## 12. Migration checklist for existing LabMango

1. Add models and migrations (`SyncState`, `RoutingChange`, `AgentIdentity`, grants, nonces, telemetry tables).
2. Introduce the service layer and refactor routing-relevant writes to use it.
3. Add `user_key` to users and backfill from SSO or employee ID.
4. Create the `agent_api` package with auth, permissions, throttles; add `/internal` sync endpoints. Do not introduce feature flags unless the repository's feature-flag policy is revised.
5. Provision the telemetry store and retention jobs (O8).
6. Configure prefix, cookies and the Nginx block (including the agent rate-limit zone) for the department.
7. Register the backend in `backends.yml` (Edge repo) and verify sync end to end.

## 13. Implementation plan

### 13.1 Decide before coding

1. **O8 telemetry store** (TimescaleDB vs PostgreSQL partitioning). Determines the `MetricSample` model and retention jobs.
2. **O6 move history** (default: stays in the old backend).
3. **Agent/equipment identity link**: resolved in 4.1 and 6.1 (server-issued `agent_uid`, one active agent per equipment). Remaining decision: which key-storage tiers (6.1) are accepted per department.
4. **`user_key` source**: SSO subject, employee ID or normalized email. Backfill plan for existing users.
5. **Async deployment**: ASGI server or dedicated worker pool for long-poll endpoints.

### 13.2 Milestones

| # | Milestone | Deliverables | Done when |
|---|---|---|---|
| M1 | Version core | `SyncState`, `RoutingChange`, service layer (`upsert_agent_identity`, `record_change`, user equivalents), `user_key` + backfill, bulk-write CI guard | Version bumps on routing changes only; transactional tests pass |
| M2 | Sync API | `/internal/info`, `/internal/sync/{users,equipment}` (delta, full, `304`, long-poll, tombstones), `/internal/equipment/{uid}`, sync-token auth | Stub router (13.4) syncs a full and a delta cycle |
| M3 | Agent identity | `agent_api` package: auth class, permissions, throttles; `enrollment-grants`, `enroll`, `token`, `heartbeat`, `ping`, `info`; signing key and `kid` handling | Stub agent enrolls, gets a token, calls ping; replay and wrong-`aud` tests pass |
| M4 | Telemetry | `inventory`, `metrics`, `events`; queue and bulk insert workers; latest-snapshot tables; retention and rollup jobs; allowlist filtering; limits | 1,000 batches replayed twice produce no duplicates; routing version unchanged |
| M5 | Bookings | `GET /agent/bookings` with window, ETag, scoping, optional long-poll | Cross-equipment access impossible (tested); `304` on unchanged |
| M6 | Hardening | Prefix and cookies, Nginx rate-limit zone for `/agent`, metrics and alerts, `openapi/agent.yml`, compatibility replay tests, runbook notes | All acceptance criteria below pass |

Each milestone is independently releasable; deployment gating must follow the repository's approved release policy.

### 13.3 Acceptance criteria

- [ ] Changing `last_seen_at`, inventory, metrics, events or bookings never changes `SyncState`.
- [ ] Creating, deleting or moving equipment, or changing routing-relevant agent public-key data, bumps `equipment` exactly once, atomically with the relevant equipment/routing change; agent credential revocation alone does not silently redefine equipment lifecycle.
- [ ] `since` older than retained history returns full mode; `since == version` returns `304` after at most `wait` seconds.
- [ ] Tombstones are delivered for deletes and moves.
- [ ] `/internal/*` is unreachable through the public prefix, and refused without a valid sync token.
- [ ] An agent token for `dept_a` is rejected by `dept_b` (`aud` check).
- [ ] A grant works once; an expired or reused grant returns `403`.
- [ ] Replayed assertion (`jti`) is rejected.
- [ ] `421` is returned for equipment/agent identity no longer owned here; `426` for a too-old agent.
- [ ] Booking endpoint returns only the authenticated agent identity's linked equipment and only `user_key` for users.
- [ ] Duplicate telemetry (same idempotency key, or same `(agent_uid, ts, name, labels)`) is ignored.
- [ ] Records outside the timestamp window or over the batch limits are rejected with clear errors.
- [ ] URLs are generated with the prefix; cookie names do not collide across departments.
- [ ] An old recorded set of agent requests still passes after every change (additive-only guarantee).

### 13.4 Stubs for independent development

- **Stub router** (`tools/stub_router.py`): loops `GET /internal/sync/equipment?since=<n>&wait=30` and `users`, with the sync token, applies deltas in memory, verifies `backend_id`, and prints versions. Use it to test long-poll and full fallback.
- **Stub agent** (`tools/stub_agent.py`): generates an Ed25519 key pair, enrolls with a grant, requests tokens with a signed assertion, posts inventory, metrics and events, and reads bookings. Include fault options: replay, wrong audience, oversized batch, old timestamps.
- Use these in CI as integration tests.

### 13.5 Out of scope for this repo

Router logic, Nginx generation (Edge repo), config and update delivery (Gateway), agent retry behavior (Agent repo). This repo only honors the contracts above.

---

# Part B. Shared contracts and context

## B1. Security formats used by this backend

#### 7.1 Enrollment grant

Opaque random string, 256-bit (`eg_` + base64url). Stored as SHA-256 hash with `expires_at`, `used_at`, `revoked_at`, and the bound `agent_uid` and `equipment_id`. Redeemed once with a proof-of-possession signature (6.2). It is a bootstrap ticket, not a key: it carries no data scope and is useless after redemption.

#### 7.2 Agent assertion (JWT, EdDSA)

```
header:  { "alg": "EdDSA" | "ES256", "typ": "JWT" }   # must equal the alg registered for the key
claims:  { "iss": "<agent_uid>", "sub": "<agent_uid>", "aud": "<token endpoint URL>",
           "iat": 1762335000, "exp": 1762335060, "jti": "<uuid>" }
```
Lifetime ≤ 60 s. `jti` single-use.

#### 7.3 Backend access token (JWT, EdDSA)

```
header:  { "alg": "EdDSA", "typ": "JWT", "kid": "be-dept_a-2026-01" }
claims:  { "iss": "dept_a", "sub": "<agent_uid>", "aud": "dept_a", "scope": "inventory:write telemetry:write activity:write bookings:read",
           "iat": …, "exp": … (≤ 3600 s), "jti": "<uuid>" }
```

#### 8.2 Backend token key

Add new `kid` (backend verifies both) → start signing with new → wait one token TTL → drop old.

### 9. Anti-clone strategy

- Fingerprint = hash of stable hardware identifiers plus install id. It is **not** the identity; it is a consistency check.
- Agent verifies the fingerprint on start; mismatch stops the agent.
- Backend compares the fingerprint at enroll and token issue; mismatch returns `403 fingerprint_mismatch` and alerts.
- Router raises a conflict if the same equipment UID is claimed by two backends.
- Equipment UIDs are tombstoned and never reused. Agent UID uniqueness and reuse policy is a separate decision.

## B2. Context

### What the Edge router does with the sync API (for context)

- One task per `(backend, entity)`: long-poll `GET /internal/sync/{entity}?since=<cursor>&wait=30` with the sync token.
- Verifies `backend_id` in each response against its registry. A mismatch rejects the batch.
- Applies deltas and tombstones, stores the cursor in the same transaction. Runs a full resync at startup and nightly.
- Never purges a backend's entries when the backend is unreachable.
- For unknown equipment UIDs, calls `GET /internal/equipment/{equipment_uid}` on enabled backends with a short timeout and a negative cache.
- Keeps a conflict (and does not overwrite) if two active backends claim one key.

Implication for this repo: delivery of tombstones and full snapshots must be correct, versions must be monotonic, and the API must tolerate frequent long-polls from one client.

### What the agent does against this API (for context)

- Enrolls once; then requests a token with a signed assertion and renews it before expiry or on `401`.
- Sends inventory on change, metrics every 30 s to 5 min, events batched; each batch has an `Idempotency-Key` and a per-agent `X-Seq`, persisted in its spool so retries do not duplicate.
- Reacts to responses: `401` re-assert, `421` re-resolve through the Gateway, `403` stop pushing, `426` update now, `429` honor `Retry-After`, `5xx` backoff with jitter and spool.
- Reads bookings every 1 to 5 minutes with `If-None-Match`, caches them with `valid_until`, and applies an offline policy from its config.
- Sends `X-Agent-Version` on every call.
