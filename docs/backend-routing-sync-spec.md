# Backend Routing and Sync Spec

| | |
|---|---|
| Revision | 2.0, 2026-11-09. Replaces the "Edge-facing" draft |
| Status | **Proposed for review.** R0 schema slice exists in the worktree; R1 stream readiness and the R2 sync API are not approved and not implemented (Appendix A) |
| Owner | Backend team (routing and sync) |
| Consumer | **Router** (`labmango-router`: Nginx + router service) |
| Required reviews | Architecture, Security, Operations, QA |
| Placement | Follow the repository documentation map. Model-level parts (tables, constraints, ownership) go next to the code in `core/labs/models/docs/`; the API contract goes in `openapi/routing-sync.yml` |
| Companions | [backend agent API proposal](backend-agent-api-spec.md), [agent design](agent-design-spec.md), [platform reading guide](README.md#agent-platform-start-here). Router and Gateway contracts live in separate repositories and are not verified here |

## What changed in this revision

| # | Change | Why |
|---|---|---|
| 1 | "Edge" is now **Router** everywhere (`labmango-router`; Nginx tier plus router service) | Single name for the component |
| 2 | The sync API is **GET-only** and has no side effects (section 8.1, GET-1..GET-6) | Pull-only, safe, cache- and retry-friendly; removes server-side state created by reads |
| 3 | **Authentication simplified**: TLS with server verification and a scoped credential, with the **backend never configured with anything about the Router**. Preferred credential: an Entra application token with an app role; fallback: a static bearer token. mTLS becomes optional (section 10.3, Appendix C) | The API is read-only, minimal-data and single-consumer. mTLS forces Router-specific trust configuration onto backends and needs proxy attestation, the largest source of risk and operational cost. **Proposed revision of the 2026-11-08 accepted boundary; needs Security approval** |
| 4 | **No retained snapshot generations.** Full sync is a keyset scan of live claims plus replay of the change log from a watermark (section 8.4, SNAP-1..SNAP-6) | Keeps `GET` safe and stateless; removes generation storage, retention and cursor-expiry logic. **Proposed; replaces the "retained immutable generation" gate of the previous draft** |
| 5 | Endpoints split: `info`, `snapshot`, `changes`, `digest` (was `info`, `sync` with modes, `digest`) | One purpose per endpoint; strict, simple query validation |
| 6 | **Digest algorithm fixed** with test vectors (section 8.6, Appendix E) | Was an open R2 decision |
| 7 | Conflict policy clarified: the Router **fails closed** on a double claim and alerts; "existing owner wins" (old O3) is withdrawn | The Router has no reliable cross-backend ordering to decide who was first |
| 8 | Normative text separated from implementation status and history. Equipment/`agent_keys` material moved to Appendix D | The previous draft mixed requirements with status notes and superseded designs |
| 9 | Requirement IDs, error catalog, limits, reference sizing, threat model, consumer contract | Testable and reviewable |

## 0. How to read this document

- **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as in RFC 2119.
- Decisions are tagged **Confirmed** (owner decided), **Proposed** (this revision; needs approval) or **Open**.
- Requirement IDs (for example `GET-2`, `AUTH-3`) are stable and are what tests and reviews cite.
- This is a target design. It is not evidence that any routing table, publisher or endpoint exists in production. Implementation status is reported separately in Appendix A and must be verified against the source.

## 1. Purpose, scope and non-goals

The Router routes authenticated Entra users and enrolled agents to the department backend that owns them. To do that it needs to know which backend owns which identity. Each backend publishes a **claim** for every identity it owns, and the Router pulls those claims over a read-only API and combines them into one routing table.

| In scope | Out of scope |
|---|---|
| Routing projection, change log, version counter, epoch (backend side) | Agent enrollment, tokens, telemetry, bookings (agent API spec) |
| Publisher that writes them atomically with domain changes | Router internals, Nginx generation, public prefix routing (Router repository) |
| The read-only sync API the Router pulls | Gateway behavior |
| Restore and disaster-recovery behavior of the sync stream | Business data replication of any kind |

Streams (**Confirmed**): `users` and `agents`. There is no equipment ownership stream and no `agent_keys` stream (Appendix D).

## 2. System context

```
Agent ──▶ Gateway ──▶ Router ──▶ Backends            control plane: resolve
Agent ───────────────────────▶ Backends               data path, through the Router's Nginx prefix
Router ──── GET only (pull) ──▶ Backend /internal/*   routing sync (this document)
```

| Component | Repository | Role |
|---|---|---|
| Router (Nginx + router service) | `labmango-router` | Owns `{entity, key} -> backend_id`, public prefix routing, backend registry, user and agent resolve |
| Gateway | `gateway` | App-agnostic control plane for agents: resolve, signed config, updates, agent auth |
| Backend (one per department) | `labmango-backend` | Business data, read-only sync API, agent enrollment and tokens, telemetry, bookings |
| Agent | `agent` | Runs on equipment; pushes data to its backend; fetches config and updates |

**Dependency rules (never violate)**

1. Backends know nothing about the Router, the Gateway or other backends. A backend never calls out for routing purposes.
2. The Router knows backends only (from a provisioned registry). The Gateway knows the Router through a per-app `resolver_url`.
3. No shared database between repositories. The contracts are the APIs in this document.
4. The control plane (Gateway, Router service) is never in the data path. Agents and users reach backends through Nginx prefix routing.

### Glossary

| Term | Meaning |
|---|---|
| `backend_id` | Immutable logical name of a department backend (`dept_a`). Never a hostname |
| Prefix | Public path of a backend, for example `/api/dept_a/`. Nginx strips it before the backend sees the request |
| `user_key` | `entra:<lowercase-tenant-uuid>:<lowercase-object-uuid>`. Derived from the persisted Entra identity. Never a local ID, username or display name |
| `agent_uid` | Server-generated, globally unique UUIDv4 of one enrolled agent. Distinct from equipment `uid`. An identity locator, **not** a credential |
| Claim | A backend's statement "I own this key", published as a live `RoutingEntity` row |
| Stream | The ordered set of claims and changes for one entity type (`users` or `agents`) on one backend |
| Version | Monotonic, gap-free counter per backend and stream. Changes only on routing-relevant changes |
| Epoch | UUID naming one continuous history of a stream's counter. Changes whenever continuity is lost (restore, reset) |
| Watermark | The `head_version` read together with the first snapshot page; the point from which the Router replays changes |
| Tombstone | A `delete` change (and a retained deleted projection row) for a key that left eligibility |

Agent-platform terms (grants, assertions, booking codes, sessions) are defined in the agent API spec and are not used here.

## 3. Principles

| ID | Principle |
|---|---|
| P1 | **Routing is not authorization.** A claim only says where to send a request. The destination backend authenticates and authorizes every request itself, so a stale or wrong claim can misroute but never grant access |
| P2 | **Pull only.** The Router pulls. Backends never push or call out |
| P3 | **GET only.** The sync API is read-only and uses only GET (section 8.1) |
| P4 | **Fail closed.** Unknown, conflicting or invalid claims resolve to nothing |
| P5 | **Minimal data.** Keys, active state and versions only. No profiles, usernames, emails, equipment UIDs, public keys, hostnames or secrets |
| P6 | **Recoverable.** Versioned, epoch-protected, restorable, and rebuildable from domain data |
| P7 | **Bounded and observable.** Every response, wait and concurrency level has a limit; every failure mode has a metric |

## 4. Decisions

### 4.1 Confirmed (owner, revised target of 2026-11-07)

| ID | Decision |
|---|---|
| C1 | One backend per department behind one shared frontend; `backend_id` is immutable |
| C2 | Entity names are `users` and `agents`. No equipment stream |
| C3 | User routing key is `user_key` from the persisted `EntraIdentity` tenant/object UUID pair. Only active local users with an Entra binding are eligible. The Router validates the Entra ID token and derives the key from trusted `tid` and `oid`; it never routes by username |
| C4 | Agent routing key is `agent_uid`. Only an active `AgentIdentity` is eligible |
| C5 | Leaving eligibility (deactivation, unlink, deletion, revoke, decommission) publishes a tombstone for the old key. Replacing a user's Entra binding tombstones the old key and publishes the new one |
| C6 | Claim payload is the route key plus active state; `data` is `{}`. No names, usernames, emails, equipment UIDs, public keys or token material |
| C7 | `equipment` and `agent_keys` labels remain accepted by the database schema temporarily (migration 0011 compatibility). They are never seeded, written, advertised or served |
| C8 | Router and Gateway store state in PostgreSQL with an in-memory cache (old O4) |
| C9 | There is no shared per-backend API key for agents; agents use per-agent tokens (old O5). The sync token in section 10 is a different, Router-to-Backend service credential |
| C10 | Separation of credentials: Router sync credentials are not Agent credentials. Provisioning them requires no `AgentIdentity`, Computing resource or other Lab Mango entity. Agent credentials cannot access Router-only APIs and Router credentials cannot impersonate agents. Sync never distributes agent keys or certificates and never authorizes immediate agent revocation (carried over from the 2026-11-08 boundary) |

### 4.2 Proposed in this revision

| ID | Decision | Detail |
|---|---|---|
| X1 | Sync API is GET-only | Section 8.1 |
| X2 | Authentication: TLS (server-verified) + scoped credential, backend does not know the Router (AUTH-11). Method A Entra application token preferred, Method B static token as fallback, mTLS optional | Section 10.2 and 10.3. Replaces the mandatory "bearer and mTLS" boundary |
| X3 | Full sync is keyset scan + change-log replay from a watermark; no retained snapshot generations | Section 8.4 |
| X4 | Four endpoints: `info`, `snapshot`, `changes`, `digest` | Section 8.2 |
| X5 | Digest is SHA-256 over a fixed canonical encoding | Section 8.6 and Appendix E |
| X6 | Conflict policy: fail closed and alert | Section 9 (CNS-6) |
| X7 | Recommended retention defaults: change log at least 14 days, plus a size alarm | Section 6.4 |

### 4.3 Open

| ID | Question | Recommended default | Blocks |
|---|---|---|---|
| O-R4 | Exact retention numbers and pruning job | 14-day change-log floor (X7); no time-based pruning until implemented and reviewed | Pruning job, runbook |
| O-R5 | Owner of the atomic publisher | The routing feature; producers call it inside their own transaction | R1 |
| O-R6 | Final envelopes, query names, bounds and OpenAPI | Section 8 as written | R2 |
| O-R7 | How the Gateway or agent obtains `agent_uid` for resolution | Outside this spec. An agent uses the backend from its enrollment grant until an authenticated discovery method is approved. Do not infer it from equipment detail or resource-placement APIs | Router/Gateway contract |
| O-R8 | Stale-route policy during a long backend outage | Keep last-known claims, alert on staleness (P1 bounds the risk). A hard expiry is a product decision | Router behavior |
| O-R9 | Writer inventory and reconciliation for the user stream | Required before advertising the stream (section 7.3) | R1 readiness |
| O-R10 | Approval of X2 (including A versus B per backend) and X3 | Security (X2), Architecture (X3) | R2 |

## 5. Data model

The R0 models live in `core/labs/models/` (`routing/`) and are documented in `core/labs/models/docs/labs-model-architecture.md`. The projection is a **per-backend claim**: a backend publishes only its own eligible identities. The Router derives `{entity, key} -> backend_id` by combining claims from all configured backends. No row stores a peer backend, a public URL or a prefix.

```text
SyncState(entity_type PK, version BIGINT NOT NULL, epoch UUID NOT NULL)

RoutingChange(id PK, entity_type, version BIGINT, key, op, state NULL, data NULL, data_hash NULL, created_at)
  op is "upsert" or "delete"; UNIQUE (entity_type, version)
  index (entity_type, key, version)            -- latest operation per key
  immutable events: an upsert keeps its full state/data/hash; a delete has null payload fields

RoutingEntity(id PK, entity_type, key, version BIGINT, state NULL, data JSONB NULL, data_hash NULL, deleted_at NULL)
  UNIQUE (entity_type, key)                    -- current projection, rebuildable from domain data
```

- `entity_type` is a plain string. The database check allows `users` and `agents` and temporarily keeps the two legacy labels (C7). The publisher emits only `users` and `agents`.
- No `UserRoutingKey` model is needed: `user_key` is derived from the unique `EntraIdentity(tenant_id, object_id)` pair.
- Current DB checks cover labels, unique natural keys, operations and payload nullability. They do **not** cover key format, active-only eligibility, minimal `data`, event immutability or sync with domain mutations. R1 adds validated write paths and tests (PUB-4); the API MUST NOT serve unvalidated or legacy rows.
- Migrations are expand-only.

### 5.1 Key formats (validated on write and on read)

| Entity | Key | Format |
|---|---|---|
| `users` | `user_key` | `entra:` + lowercase hyphenated tenant UUID + `:` + lowercase hyphenated object UUID |
| `agents` | `agent_uid` | Lowercase hyphenated UUID |

### 5.2 Identity-to-claim mapping

| Source and eligibility | Claim | On loss of eligibility |
|---|---|---|
| `EntraIdentity` linked to a local `User.is_active=True` | `users`, `user_key`, `state="active"`, `data={}` | `delete` for the **old** key on unlink, deactivation or deletion. On replacement, delete the old key then upsert the new one |
| `AgentIdentity.state="active"` | `agents`, `agent_uid`, `state="active"`, `data={}` | `delete` on revoked, decommissioned or removal. Reinstating the same UID only if its lifecycle permits |

- `state` is a sibling of `data`, never duplicated inside it. The key lives only in `key`.
- A full snapshot contains only live rows. A `delete` change has null `state`, `data` and `data_hash`; the projection stores the same nulls with `deleted_at` set.
- `user_key` is pseudonymous but linkable sensitive identity data (section 10.7). `agent_uid` is a locator, not proof of possession.
- A missing agent route while enrollment is pending is intentional.
- There is no safe `equipment_uid -> agent_uid` mapping in this scope (O-R7).

### 5.3 Canonical hashing

`data_hash` is lowercase SHA-256 hex over the UTF-8 bytes of canonical JSON of the object `{"state": ..., "data": ...}`: recursively sorted object keys, compact separators (`,` and `:`), normalized lowercase UUID strings, JSON scalars only, arrays in their defined order. Never hash JSONB's textual rendering or timestamps. For the minimal claim the canonical text is `{"data":{},"state":"active"}` with hash `43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5` (Appendix E).

## 6. Version counter, change log and epoch

### 6.1 What bumps the version

| Entity | Bump on |
|---|---|
| `users` | An active linked user is created, deleted or deactivated; an Entra binding is linked, unlinked or replaced |
| `agents` | An `AgentIdentity` transitions into or out of active |

**Never bump** for `last_seen_at`, heartbeat, inventory, metrics, events, computing-state snapshots, booking changes or any other business edit. Otherwise the Router refetches constantly. Credential rotation and public-key changes are not part of this stream.

### 6.2 Ordering, compaction and no-op suppression

- **VER-1** Each stream has an independent counter. Versions are gap-free and become visible in commit order (PUB-2). A reader never sees version *n+1* before *n*.
- **VER-2** A delta for `(since, head]` contains the **latest operation per key** whose event version lies in that interval, ordered by the winning event's version. Each event stores its immutable payload, so compaction never reads a newer `RoutingEntity` payload for an older event.
- **VER-3** A re-save that does not change `(state, data)` produces no version (PUB-3).
- **VER-4** Pagination applies a bounded, deterministic winner query. The cursor advances only through winners actually returned; the final page may advance to `head` once every winner has been returned.

### 6.3 Epoch

- **VER-5** `SyncState.epoch` is created with the row.
- **VER-6** Any database restore, point-in-time recovery, counter reset or cloning of a backend database MUST run `manage.py rotate_sync_epoch`. It is a mandatory step of the restore runbook (section 11).
- **VER-7** A changed epoch, or a head version lower than the Router's cursor, means "start over" (full snapshot). Head regression only catches some missed rotations; a restore can keep or exceed the Router's cursor while replacing history, so the epoch step is essential.

### 6.4 Retention (Proposed, X7)

- **VER-8** `RoutingChange` is pruned only as a **contiguous prefix** per stream, and the resulting oldest retained version is persisted. A `since` below that floor yields a `reset` response (section 8.5).
- **VER-9** Keep at least 14 days of change history. Alert on change-log growth without pruning. Time-based pruning is not implemented until O-R4 is closed.
- **VER-10** Snapshots read live rows only, so deleted projection rows are not needed for correctness. A tombstoned `RoutingEntity` row MAY be pruned once `deleted_at` is older than the change-log floor.
- **VER-11** The change log MUST always retain every event newer than the snapshot watermark of any in-progress scan. The 14-day floor guarantees this for any scan that completes within the sync SLO.

### 6.5 Rules that keep it reliable

- Route **all** writes of routing-relevant fields through the service layer. Django signals miss `bulk_create`, `bulk_update` and `queryset.update()`.
- CI fails if those bulk methods are called on routing models outside the service layer. Optional safety net: a database trigger that refuses direct writes to `RoutingEntity`.
- The counter is a monotonic integer, never a timestamp.
- `RoutingEntity` is rebuildable from domain data by `manage.py rebuild_routing_projection` (section 11).

## 7. Publisher

### 7.1 Rules

| ID | Rule |
|---|---|
| PUB-1 | **Transactional.** The publisher raises `RoutingPublishError` unless called inside `transaction.atomic`. The domain change, projection row, change-log row and version increment commit or roll back together |
| PUB-2 | **Lock order.** The producer locks its source aggregate first. Routing then ensures the `SyncState` row exists (conflict-safe insert), locks it with `SELECT ... FOR UPDATE`, and only then reads or creates the `RoutingEntity` row. The stream lock serializes first inserts and version allocation. Batch publishers lock streams in stable entity-type order and process keys deterministically. Keep transactions short and free of network I/O. Audit source-row lock order before adding callers |
| PUB-3 | **No-op suppression.** If the new `(state, data)` hash equals the current projection, return `changed=False` and do not bump the version |
| PUB-4 | **Validation.** Entity type, key format, state and data schema are checked against the entity registry in the routing feature's `contracts.py`. Unknown entities, states or fields are rejected |
| PUB-5 | **Wake-up is advisory.** Send `NOTIFY routing_<entity>` only for committed changes. A missed notification must never lose a change: a long-poll rechecks the head after subscribing and at its deadline, and readers recover from the durable log. A notification failure after commit is not a rollback of the domain mutation |
| PUB-6 | **Failure semantics.** A publish failure aborts the caller's transaction. A domain change never commits without its routing record |
| PUB-7 | **Single writer.** Only the routing feature writes the three tables. CI enforces it; a full writer inventory is required before the stream is advertised |
| PUB-8 | **Bulk operations.** Backfills use batch publishing in bounded batches and never write the tables directly |

### 7.2 Producers and the port

Producers depend on a port, not on routing internals (Appendix B). The routing feature imports no other feature. The users owner derives the key from locked persisted identity fields and passes the opaque key and eligibility state through `routing.public`; routing never imports or queries the users ORM.

| Producer event | Entity | Key | Result |
|---|---|---|---|
| Active Entra-bound user created, activated, bound or replaced | `users` | `user_key` | upsert |
| User deactivated, unlinked or deleted | `users` | prior `user_key` | delete |
| Agent identity enters active (successful enrollment) | `agents` | `agent_uid` | upsert |
| Agent identity leaves active (revoked, decommissioned, removed) | `agents` | `agent_uid` | delete |

Lock order for producers: users commands lock user, then identity, then the routing stream, and derive the prior key before unlink or delete. Agent enrollment locks the grant, then the identity, before routing; terminal transitions lock the identity before routing. Same-terminal transitions are no-ops.

### 7.3 Stream readiness gate

- **PUB-9** A stream MUST NOT be advertised by `GET /internal/info` until it is enabled, initialized, **completely backfilled and reconciled**, and every user or agent writer is covered (including bulk activity changes, login binding, operator binding, enrollment and terminal transitions). No-op stubs cannot be used once a stream is advertised.
- **PUB-10** Do not claim atomic synchronization while any write path can be missed.

## 8. Sync API

### 8.1 Conventions and GET-only guarantees

The API is mounted on a **separate private URL mount and listener** (not the public `/api/` aggregator) and has its own OpenAPI file (`openapi/routing-sync.yml`). Paths have no version segment and no trailing slash; changes are additive and discovered through `GET /internal/info` (backend API convention). The Router's own resolve API is versioned in its path (`/router/v1`) and the Gateway's agent API in `/v1`.

| ID | Requirement |
|---|---|
| GET-1 | Only `GET` is routed. Every other method (including `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`) returns `405 method_not_allowed` with `Allow: GET`. `HEAD` MAY be supported. Enforced at **both** the proxy (`limit_except GET`) and the application |
| GET-2 | **Safe and side-effect free.** A request performs no database writes (no counters, leases, audit rows or snapshot generations). Handlers run in a read-only transaction. In-memory long-poll registration and rate-limit counters are the only per-request state. Audit goes to logs and metrics |
| GET-3 | **Stateless with respect to the Router.** There is no server-side cursor, session, lease or retained generation. Everything needed is in the request, and repeating a request is harmless |
| GET-4 | No request body (a body or non-zero `Content-Length` returns `400 invalid_request`), no cookies, and no credentials in the URL |
| GET-5 | Every response carries `Cache-Control: no-store`, `Content-Type: application/json`, and `X-Request-ID` |
| GET-6 | The Router uses only `GET` against `/internal/*`, does not follow redirects, and sends no body. Verified by a client-side test |

**Envelopes.** Success: `{"data": {...}}`, with `meta` only when documented. Errors: `{"error": {"code": "...", "message": "...", "details": [], "request_id": "<32 lowercase hex>"}}`; `details` is always present. HTTP status is authoritative and is not repeated in the body. A valid inbound `X-Request-ID` is honored, otherwise one is generated; the same value is returned in the header and in `error.request_id` (platform standards ENV, ERR, TRC). Do not accept `X-Request-Id` as an alias.

**Query strictness.** Each endpoint has an allowlist. Unknown, duplicate, empty, malformed or inapplicable parameters return `400 invalid_query` with `details[].field` naming the parameter. Parameters are never silently ignored. Query keys are `snake_case`.

### 8.2 Endpoints

| Method and path | Purpose |
|---|---|
| `GET /internal/info` | Discover enabled, ready streams; their epoch and head; server limits |
| `GET /internal/snapshot/{entity}` | One page of the live claims of a stream, in key order (full sync) |
| `GET /internal/changes/{entity}` | Bounded changes after a version, optionally long-polled (catch-up and live) |
| `GET /internal/digest/{entity}` | Optional drift check: count and checksum at a version |

`{entity}` is `users` or `agents`. Any other value, or a stream that is not enabled and ready, returns `404 entity_not_supported`. Legacy labels are never advertised or served.

### 8.3 `GET /internal/info`

No query parameters. `data`:

```json
{
  "backend_id": "dept_a",
  "server_time": "2026-11-09T09:30:00Z",
  "entities": {
    "users":  { "version": 12, "epoch": "5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10" },
    "agents": { "version": 7,  "epoch": "c902a8b4-3f61-4e2b-8a0e-2d4f6b1c9e33" }
  },
  "limits": { "snapshot_max_limit": 5000, "changes_max_limit": 2000, "longpoll_max_wait_s": 30 }
}
```

Only streams that pass the readiness gate (PUB-9) appear. Used for liveness, lag calculation, epoch checks and limit discovery.

### 8.4 `GET /internal/snapshot/{entity}`

Query: `limit` (integer 1..5000, default 1000), `after` (the last key of the previous page, exclusive; omit for the first page).

`data`:

```json
{
  "backend_id": "dept_a",
  "entity_type": "users",
  "epoch": "5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10",
  "head_version": 12,
  "items": [
    { "key": "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001",
      "version": 9, "state": "active", "data": {} }
  ],
  "next_after": "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001"
}
```

`next_after` is `null` on the final page. Items are live claims only, ordered by key (bytewise UTF-8).

| ID | Rule |
|---|---|
| SNAP-1 | Each page is read in one read-only transaction at a consistent snapshot, and `head_version` and `epoch` are read in that same transaction as the items |
| SNAP-2 | Pages are keyset-paginated on `key > after`. Different pages MAY observe different moments; this is correct because of SNAP-3 |
| SNAP-3 | **Convergence rule.** The Router sets `snapshot_version` to the `head_version` of the **first** page, stages all pages, then replays `changes` from `snapshot_version` to a head read after the last page, and applies the scan plus the replay as one unit. A key that was untouched in that window is returned exactly once with its constant value; a key touched in that window is overwritten by its latest change. The result equals the stream state at the replay head |
| SNAP-4 | The Router MUST NOT publish scanned claims before the replay has caught up (the scanned set alone can be a mix of moments and is not a real historical state) |
| SNAP-5 | All pages of one scan MUST report the same `epoch` and `entity_type`. A different epoch mid-scan restarts the scan |
| SNAP-6 | The backend keeps no scan state. A lost response or restarted Router simply starts a new scan |

**Why not retained snapshot generations?** They need storage, retention, cleanup, cursor integrity and expiry, and they make a `GET` create server-side state, which breaks GET-2 and GET-3. Scan plus replay gives the same end state using only data the change log already retains (VER-9, VER-11). *Alternative considered:* an immutable generation per scan (previous draft). Choose it only if Architecture rejects X3; it requires GET-2 to be relaxed.

### 8.5 `GET /internal/changes/{entity}`

Query: `since` (required, integer >= 0), `epoch` (required, canonical UUID the Router holds), `limit` (1..2000, default 500), `wait` (0..`longpoll_max_wait_s`, default 0).

Delta (`data`):

```json
{
  "backend_id": "dept_a",
  "entity_type": "users",
  "epoch": "5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10",
  "mode": "delta",
  "version": 13,
  "head_version": 13,
  "has_more": false,
  "oldest_retained_version": 1,
  "changes": [
    { "version": 12, "op": "upsert", "key": "entra:11111111-2222-3333-4444-555555555555:bbbbbbbb-0000-0000-0000-000000000001", "state": "active", "data": {} },
    { "version": 13, "op": "delete", "key": "entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002" }
  ]
}
```

Reset (the Router must run a new snapshot scan; **status is still `200`** so a client can never be left stuck):

```json
{ "backend_id": "dept_a", "entity_type": "users", "epoch": "<current epoch>", "mode": "reset",
  "reason": "epoch_changed", "head_version": 13 }
```

`reason` is `epoch_changed`, `history_pruned` (`since` below the retained floor) or `cursor_ahead` (`since` above head).

| ID | Rule |
|---|---|
| CHG-1 | Changes are ordered by version and each key appears **at most once** (its latest operation in `(since, head]`) |
| CHG-2 | `version` is the cursor the Router stores: the last returned change version when `has_more` is true, otherwise `head_version`. `head_version` is read in the same transaction as the winners query |
| CHG-3 | `has_more` is true when further winners remain; the Router requests again immediately |
| CHG-4 | A no-change long-poll returns `200` `mode="delta"`, `changes=[]`, `version` equal to `since`, and the current `head_version`, after at most `wait` seconds. It is never `408`, and `304` is not used |
| CHG-5 | A `delete` carries `version`, `op`, `key` only. An `upsert` carries `state="active"` and `data={}` |
| CHG-6 | The backend honors `limit` and never returns more than `changes_max_limit` winners or a documented maximum response size |

### 8.6 `GET /internal/digest/{entity}` (optional)

No query parameters. `data`:

```json
{ "entity_type": "users", "epoch": "5f0c2d1e-0b57-4c1e-9d65-3a1e8f5d7a10", "version": 12, "count": 2,
  "checksum": "sha256:e55f21dda5b3742e8baa44eeadfb712312907f2226c940cdb9dc843b5dce5a13" }
```

| ID | Rule |
|---|---|
| DIG-1 | `checksum` is `sha256:` + lowercase hex SHA-256 over, for each **live** row in ascending bytewise key order: `u32be(len(key))`, `key`, `u32be(len(state))`, `state`, then the 64 ASCII hex characters of `data_hash`. Lengths are UTF-8 byte lengths. An empty stream hashes the empty input |
| DIG-2 | `count`, `checksum`, `version` and `epoch` come from one consistent database snapshot |
| DIG-3 | The result is cached per `(entity, version)`. Target latency p99 < 500 ms |
| DIG-4 | The Router compares only when `epoch` equals its cursor epoch and `version` equals its cursor version. A mismatch triggers a resync |
| DIG-5 | A backend that does not implement it returns `404 not_found`; the Router treats that as "not supported", not as a failure |

Appendix E holds test vectors that both sides MUST pass.

### 8.7 Errors

| Status | `code` | When |
|---|---|---|
| 200 | | Delta, reset, snapshot page, no-change long-poll, info, digest |
| 400 | `invalid_query` | Unknown, duplicate, empty, malformed or inapplicable parameter; `details[].field` names it |
| 400 | `invalid_request` | A request body was sent |
| 401 | `unauthorized` | Missing or invalid bearer token. `WWW-Authenticate: Bearer` |
| 403 | `forbidden` | Authenticated caller lacks the sync-read scope |
| 404 | `entity_not_supported` | Entity not enabled or not ready |
| 404 | `not_found` | Unknown path, or optional digest not implemented |
| 405 | `method_not_allowed` | Any method other than GET. `Allow: GET` |
| 429 | `rate_limited` | Per-credential rate or concurrency limit. `Retry-After` |
| 500 | `internal_error` | Unexpected failure |
| 503 | `unavailable` | Temporarily unavailable or draining. `Retry-After` when known |

### 8.8 Limits, long-poll and sizing

| Limit | Default |
|---|---|
| Snapshot page | 1000 items (max 5000) |
| Changes page | 500 winners (max 2000) |
| Long-poll wait | 0 to 30 s; proxy read timeout MUST be at least wait + 5 s |
| Concurrent held requests per credential | 8 |
| Requests per second per credential | 20 |
| Maximum response size | 5 MiB |

- Held requests MUST NOT exhaust workers: use async (ASGI) views or a dedicated worker pool for `changes`. Wake-ups come from `NOTIFY` (PUB-5), with one `LISTEN` connection per worker or a shared listener. Drop the request when the client disconnects. Cost is one open request per Router stream.
- Responses are bounded and `no-store`. `gzip` MAY be applied.
- **Reference sizing (assumption; measure to confirm, O7):** up to 100k users and 50k agents per backend is about 150k claims, roughly 20 MB over 150 snapshot pages. One Router instance syncs at a time, so steady load is two held requests per backend.

## 9. Router consumption contract

The Router is specified in its own repository. The backend relies on these behaviors, and contract tests run in both repositories.

| ID | Requirement |
|---|---|
| CNS-1 | Load a **provisioned** registry `backend_id -> private sync URL, public prefix, upstream`. Never accept these fields from a claim |
| CNS-2 | Call `info` for each backend. Verify `backend_id` against the registry entry. Treat a stream as routable only if it is advertised |
| CNS-3 | On first contact, epoch change, history loss or a `reset`: run a snapshot scan (SNAP-3), stage validated pages, drain `changes` from the watermark, and apply everything **atomically** with the cursor `(epoch, version)` for that backend and stream |
| CNS-4 | Otherwise pull `changes` from the stored version and long-poll. Apply upserts and deletes idempotently with per-key versions, and commit the cursor in the same transaction. Use backoff with jitter after errors |
| CNS-5 | Schema-validate every response (backend id, entity, epoch, key format, state, ordering) before writing anything |
| CNS-6 | Build the effective view from live claims: one owner resolves through its configured prefix, zero owners is unknown, **more than one owner is a conflict and resolves to nothing**. Alert on conflicts. Never silently choose one. A `delete` removes only that backend's claim. A user must not exist in two departments; operators fix the source |
| CNS-7 | Never purge a backend's claims because it is unreachable. Keep last-known claims, expose staleness as a metric, and apply the O-R8 policy |
| CNS-8 | Compare `digest` periodically when supported; a mismatch triggers a resync. A periodic full resync is a backstop |
| CNS-9 | Only one Router instance pulls at a time (leader election); other instances serve routes from the shared store |
| CNS-11 | Obtain the sync credential from its own configuration: for Method A a client-credentials token per backend audience (cached until shortly before expiry, refreshed on `401`); for Method B the token file. Send it only over verified TLS and only to the configured backend. The backend is never told the Router's address or identity |
| CNS-10 | Validate the Entra ID token (signature, `aud`, `iss`, `exp`, allowed `tid`) before deriving `user_key`. Agent resolution requires a separately authenticated discovery flow (O-R7) |

## 10. Security and privacy

### 10.1 Assets and threats

| Asset | Sensitivity |
|---|---|
| Stream contents: `user_key` (tenant + object ID) for every active user of a department, and every active `agent_uid` | Pseudonymous but linkable identity directory. **Confidentiality matters** |
| Routing integrity: which backend a key maps to | Misrouting is a denial of service and can leak a user's login attempt to the wrong backend; it does not grant access (P1) |
| Sync credential | Lets the holder read the directory of the backend it was issued for |

| Threat | Control |
|---|---|
| Unauthorized read from the internal network | Credential required on every request (AUTH-1); network segmentation (AUTH-6) |
| Eavesdropping or tampering on the wire | TLS 1.2+ (AUTH-5) |
| Rogue server impersonating a backend, collecting the credential or injecting claims | Router verifies the backend certificate (AUTH-4); claims accepted only for the registered `backend_id` |
| Stolen or leaked credential | Method A: short-lived token, the Router's Entra secret never leaves the Router. Method B: scoped per backend, hashed at rest, rotatable (AUTH-2, AUTH-8, AUTH-16) |
| A compromised backend replays the credential it received against another backend | Per-backend audience (AUTH-13) or per-backend token (AUTH-2) |
| Abuse of the API to change data | Impossible by construction: GET-only, read-only transaction, no writes (GET-1, GET-2) |
| Resource exhaustion through long-polls | Concurrency and rate limits (section 8.8) |
| Agent or user credentials used against sync | Separate credential class, role and verifier (AUTH-3, AUTH-15, C10) |

### 10.2 Principle: the backend does not know the Router

- **AUTH-11** A backend authorizes a **role**, never a named client. It MUST NOT be configured with the Router's address, hostname, IP, name, Entra client ID, certificate, key or registry entry. This is dependency rule 1 (section 2) applied to authentication.
  - Allowed backend configuration, and nothing more: for Method A, the Entra tenant ID(s), this backend's own audience and the required role name; for Method B, the SHA-256 digests of accepted tokens.
  - Who may hold the role is decided where the credential is issued (Entra, or whoever generates the static token), not in the backend.
  - Restricting who can reach `/internal/*` is done by platform network policy (segment, security group or ingress rule owned by the platform team), not by a Router address list inside the backend (AUTH-6).

### 10.3 Authentication method (Proposed, X2)

| | **A. Entra application token (preferred)** | **B. Static bearer token (fallback)** | **C. mTLS (optional, Appendix C)** |
|---|---|---|---|
| Backend must know the Router? | **No.** Knows tenant, audience and role name only | **No.** Knows only a digest of a secret | **Yes.** Needs a CA or certificate-identity allowlist that names the Router |
| Secret held by each backend | None | A digest per accepted token | CA bundle, allowlist |
| Credential lifetime | Up to 1 hour, issued on demand | Until rotated (at most 90 days) | Certificate lifetime |
| Who may call | Whoever Entra grants the role to | Whoever holds the token | Whoever holds a certificate on the allowlist |
| Revocation | Remove the role assignment or disable the app; existing tokens expire within the hour | Remove the digest (immediate) | CRL/OCSP or remove from allowlist |
| Extra infrastructure | Entra app registrations (one API per backend), backends reach Entra's key endpoint | Token generation and rotation procedure | Private CA, issuance, rotation, proxy attestation |
| Fits GET-only, read-only data | Yes | Yes | Yes, with the most operational cost |

**Selection rule.** Use **Method A** by default. Lab Mango already depends on Entra for user identity, it removes manual secret distribution to every backend, and it satisfies AUTH-11 completely. Use **Method B** where backends cannot reach Entra's key endpoint (restricted egress or air-gapped) or Entra app registrations per backend are not practical. Use Method C only if Security or the platform requires it. Backends implement the common checks plus A and/or B; the Router supports whichever each backend declares in its registry entry.

**Method A flow**

1. **Entra setup (once per backend).** Register an API application with App ID URI `api://labmango-<backend_id>`, access-token version 2.0, and an **application** app role `Routing.Sync.Read`.
2. **Authorization.** Register the Router as a client application and assign it that role on each backend API (admin consent). Entra, not the backend, holds "who is allowed".
3. **Router.** For each backend, request a token by the OAuth2 client-credentials grant with scope `api://labmango-<backend_id>/.default`. Authenticate to Entra with a certificate or secret read from a file, or with a managed identity or workload-identity federation where the hosting platform provides it. Cache the token until shortly before it expires.
4. **Backend.** Validate each request's token as in AUTH-12.

**Why mTLS is not the default.** GET-only removes the risk of unauthorized changes but not the risk of unauthorized reads, so authentication is still needed, and a verified-TLS bearer credential provides it. mTLS forces the backend (or the platform in front of it) to hold Router-specific trust configuration, which AUTH-11 forbids. It also needs a private CA, certificate issuance and rotation, revocation, and a proxy-to-application attestation to tell Django who the caller is. That attestation (header stripping, trusted-peer checks, replay binding, bypass tests) was the longest and riskiest part of the previous draft, and a mistake there silently disables authentication. The previous draft also still required the bearer token alongside mTLS, so it added a second factor rather than a replacement.

### 10.4 Authentication and transport requirements (Proposed, X2)

| ID | Requirement |
|---|---|
| AUTH-1 | Every request MUST carry `Authorization: Bearer <credential>`, an access token (Method A) or a static token (Method B). Missing or invalid returns `401`. Valid but not authorized returns `403`. Deny by default |
| AUTH-2 | **Method B token:** at least 256 bits from a CSPRNG, base64url. One token per backend (never shared across backends). The backend stores only a SHA-256 digest, compares in constant time, and accepts at most two tokens during rotation. The digest is not associated with a named client (AUTH-11) |
| AUTH-3 | The credential authorizes only `GET /internal/info`, `snapshot`, `changes` and `digest`. It is a separate credential class with its own verifier and auth class, and it is rejected by every other API. Agent tokens, user tokens and Gateway credentials MUST NOT be accepted on `/internal/*` |
| AUTH-4 | The Router MUST verify the backend's TLS certificate chain and hostname against a configured CA, MUST refuse `http://` in production, and MUST NOT follow redirects |
| AUTH-5 | TLS 1.2 or higher (1.3 preferred) on every hop that crosses a host boundary. A proxy-to-application hop on loopback or a Unix socket on the same host MAY be plain |
| AUTH-6 | `/internal/*` is served only on a dedicated private listener or vhost, blocked at the public Nginx, and reachable only from the platform's internal network segment through platform network policy. Segmentation is defense in depth and does not replace AUTH-1 |
| AUTH-7 | Secrets are files, Docker secrets or systemd secrets (mode 0400), never in the URL, image, repository or process arguments |
| AUTH-8 | Rotation: Method B tokens at least every 90 days and on any suspicion, with overlap and no downtime (section 11); Method A client secret or certificate per the platform's credential policy. Rotations and failures are audited |
| AUTH-9 | Failed authentication is rate-limited per source address. Logs record `request_id`, source and outcome, never the credential |
| AUTH-10 | Credential separation of C10 holds: provisioning needs no `AgentIdentity` or Lab Mango entity |
| AUTH-11 | The backend does not know the Router (section 10.2) |
| AUTH-12 | **Method A validation.** Verify the RS256 signature against the tenant's signing keys; `iss` equals `https://login.microsoftonline.com/<tenant>/v2.0` for a configured tenant; `aud` equals this backend's own audience; `exp` and `nbf` with at most 60 s skew; `roles` contains the required role; the token is **application-only** (`idtyp` is `app` where the claim is emitted, and no `scp` claim is present). Do **not** compare `azp`, `appid` or `oid` against a configured Router value (AUTH-11) |
| AUTH-13 | **Per-backend audience.** Each backend accepts only tokens whose `aud` is its own, so a token received by one backend is useless at another |
| AUTH-14 | **Key caching.** Cache the tenant's signing keys and refresh them on an unknown `kid` at most once per minute. If Entra is unreachable keep validating with cached keys. A cold backend with no keys and no Entra access returns `503 unavailable`, not `401` |
| AUTH-15 | **Role isolation.** The sync role is used for nothing else. A user token, an agent credential or a token with another role never satisfies it |
| AUTH-16 | **Revocation.** Removing the role assignment or disabling the app stops new tokens immediately; issued tokens expire within one hour. The data is read-only and minimal, so this window is accepted. Method B revocation is immediate (remove the digest) |

### 10.5 Authorization and audit

- The backend maps the verified credential to the minimum sync-read scope and audits failures.
- Audited events: epoch rotations, projection rebuilds, token issuance and rotation, authentication failures. Never log raw tokens.

### 10.6 Data minimization and logging

- Payloads contain only keys, active state, versions and `data={}` (P5, C6).
- Application logs record stream, entity, versions, counts and `request_id`. `user_key` and `agent_uid` values MUST NOT be logged at INFO or above.

### 10.7 Classification

`user_key` is internal identity-routing data: pseudonymous, stable and linkable to a person through Entra. Treat it as sensitive. Access, retention, logging and deletion controls follow the classification approved for the user directory. Deleting a user emits a tombstone; change-log events for that key age out with the retention floor (VER-9), and a data-subject deletion request that needs earlier removal requires a reviewed manual procedure.

## 11. Restore, disaster recovery and operations

These commands are **proposed tooling, not implemented**. R1/R2 must add a maintenance and readiness gate so an epoch rotation and rebuild cannot advertise partially reconciled claims.

| Situation | Required action | Router behavior |
|---|---|---|
| Database restored from backup or point-in-time recovery | Run `manage.py rotate_sync_epoch`, then `manage.py rebuild_routing_projection` (mandatory runbook steps) | Epoch change gives a `reset`; full scan and atomic replacement of that backend's claims |
| Restore without the epoch step | Not possible from the backend | `head_version < cursor` triggers a rescan (backstop only) |
| Projection suspected corrupt | `rebuild_routing_projection --verify` (rebuild into a shadow table, compare, then swap) | Digest mismatch triggers a resync |
| Backend cloned for staging or test | Rotate the clone's epoch. Never point a clone at the production Router | n/a |
| Sync token rotation | Add the new token, update the Router, remove the old token, confirm no `401` | No downtime |

`rebuild_routing_projection` recomputes `RoutingEntity` from domain data through the same entity contracts the producers use, assigns versions after the current head, and emits changes only for rows that differ.

## 12. Observability and SLOs

Metrics: `sync_requests_total{endpoint,entity,status}`, `sync_auth_failures_total{reason}`, `sync_method_rejected_total`, `sync_longpoll_waiters`, `sync_reset_responses_total{entity,reason}`, `sync_snapshot_pages_total{entity}`, `changelog_rows{entity}`, `changelog_oldest_age_seconds{entity}`, `routing_entity_rows{entity}`, `routing_publish_total{entity,changed}`, `routing_noop_suppressed_total{entity}`, `routing_publish_errors_total{reason}`, `projection_verify_mismatch_total`.

| SLO | Target |
|---|---|
| Change visible to a polling Router | 99% under 2 s (long-poll) |
| `changes` latency excluding the held wait | p99 under 200 ms |
| `snapshot` page latency | p99 under 500 ms |
| Full snapshot of the reference size (about 150k claims) | under 60 s |
| Router recovery after a backend restore | under 5 min |
| Sync API availability | 99.9% |

Alerts: change-log growth without pruning, oldest change older than the floor allows, sync 5xx, `401` or `403` spikes, reset responses, projection verification mismatch, publish errors.

## 13. Testing and acceptance

**Backend tests**

- Unit: versions bump only on routing-relevant changes and never on `last_seen_at`, heartbeat, inventory, metrics, events, state snapshots or bookings; no-op suppression; per-entity schema validation; transactional integrity of change, projection, log and version; CI guard against writes outside the routing feature.
- Concurrency: concurrent writers produce strictly increasing, gap-free, in-order visible versions; a reader never sees *n+1* before *n*.
- API contract: `info`, `snapshot` paging, `changes` delta, empty long-poll `200`, `limit` and `has_more`, compaction, `reset` for old `since`, wrong epoch and `since` above head, strict query allowlists, standard envelopes and request IDs, `404 entity_not_supported`, digest equals the Router's checksum (Appendix E vectors).
- **GET-only:** every non-GET method returns `405` with `Allow: GET` through both proxy and application; a request body returns `400`; **no handler performs a database write** (assert write-query count is zero and the transaction is read-only).
- **Authentication:** missing, malformed, wrong-class (agent, user, Gateway) and expired-rotation credentials return `401`/`403`; the credential is accepted on no other API and never appears in logs; per-credential concurrency and rate caps return `429`; the endpoints are unreachable through the public Nginx. Method A: wrong `aud`, wrong tenant or issuer, missing role, a user token (or one with `scp`), expired and not-yet-valid tokens are rejected; an unknown `kid` refreshes keys at most once a minute; cached keys keep working with Entra unreachable and a cold backend returns `503`. A test asserts the backend reads no Router-specific setting (AUTH-11).
- Snapshot correctness: scan plus replay equals live state **with concurrent writes, including deletes, during paging** (SNAP-3); a restart mid-scan, a lost response and an epoch change mid-scan all recover.
- Disaster recovery: restore, rotate epoch, rebuild behind the readiness gate, and verify the Router resyncs.

**Acceptance criteria (future phases)**

- [ ] Only the routing feature writes `SyncState`, `RoutingChange` and `RoutingEntity` (test).
- [ ] A domain change and its routing record commit or roll back together; publication outside a transaction fails.
- [ ] Re-saving unchanged data produces no version.
- [ ] Agent routing uses `agents` keyed by `agent_uid`; credential rotation, public keys and equipment ownership never alter the projection.
- [ ] `last_seen_at`, inventory, metrics, events, state snapshots and bookings never change `SyncState`.
- [ ] All GET-only, authentication and snapshot-correctness tests above pass.
- [ ] `since == head` returns an empty delta `200` after at most `wait`.
- [ ] Tombstones are delivered as `delete` changes; a projection rebuild equals the live projection.
- [ ] `/internal/*` is unreachable publicly and enforces AUTH-1..AUTH-16.
- [ ] Contract tests against `openapi/routing-sync.yml` pass in both repositories; the consumer tolerates additive fields and fails closed on unknown states.
- [ ] Revocation (a `delete`) propagates to a stub Router within the SLO.

## 14. Phased delivery

| Phase | Scope | Gate |
|---|---|---|
| **R0 Schema slice (authorized)** | `SyncState`, `RoutingChange`, `RoutingEntity` model choices and checks for `users` and `agents`; forward migration after 0011; model docs; constraint tests. No publisher or API behavior | Forward migration and model state agree; schema tests cover target and temporary legacy labels and reject unsupported labels |
| **R1 bounded lifecycle producer slice (approved; implemented in worktree)** | User activity and Entra binding lifecycle commands; source-specific publisher; login, operator and URS callers; admin mutation restrictions | Bounded command tests pass. Not full stream readiness |
| **R1 stream readiness (pending)** | Initialization, backfill and reconciliation; coverage of all user and agent writers; ordering and rebuild behavior | Full writer inventory (including direct ORM/SQL), review passes (PUB-9) |
| **R2 Sync API (not authorized here)** | The API of section 8, with approval of X2 and X3 | API, security and operations design approved; contract and security tests pass |
| **R3 Hardening** | Restore drill, SLO measurement, runbooks, penetration test | Acceptance criteria and SLOs met |

The R0 migration changes database checks and choices and needs a coordinated, explicitly approved rollout: the previous application version does not accept the new labels, so do not generate them until all deployed writers and readers are compatible. This document authorizes no migration application or production deployment.

## 15. Stubs and tooling

- **Stub router** (`tools/stub_router.py`): snapshot scan, replay, long-poll, epoch and digest checks for enabled entities; fault modes: lost response, restart mid-scan, epoch change, concurrent writes during a scan, `401` on rotation.
- **Stub producer** (`tools/stub_producer.py`): scripted publish sequences (enrollment, activation, revocation, binding replacement) to exercise ordering and no-op suppression.

---

## Appendix A. Implementation status (as reported; verify against the source)

Review finding of the worktree, 2026-11-08, carried over unchanged in substance:

- R0 routing models and migration 0011 exist. Source-specific publisher commands exist for agents (enrollment upsert, active-to-terminal tombstone, atomically with the agent mutation) and for the bounded user lifecycle (active flips, Entra bind, replace, unlink and delete, first-login binding, operator binding, URS activity changes), with rollback and idempotency tests.
- This does **not** establish a complete user stream. External and direct ORM/SQL writers are not comprehensively inventoried or blocked, and data reconciliation and backfill are missing. R1 must not be described as a ready user stream.
- No `/internal/*` endpoint or generated sync contract is mounted or verified. The browser-facing resource-mapping, equipment and user-profile APIs are not route-ownership feeds and cannot substitute for this API. `config/urls.py` mounts the public API under `/api/`; routing is not mounted there and must not be (section 8.1).
- Router and Gateway behavior in other repositories was not verified.

Baseline of what exists versus what this spec adds:

| Area | Current (as reported) | This spec |
|---|---|---|
| Routing persistence | R0 models and migration 0011 in the worktree; none in deployed behavior | `SyncState`, `RoutingChange`, `RoutingEntity` (section 5) |
| Internal sync endpoints | None | Section 8 (R2) |
| User key | `EntraIdentity` stores a unique tenant/object UUID pair; no generic per-user key | Derive `user_key`; users without an Entra binding are omitted |
| Agent identity | `AgentIdentity` and `EnrollmentGrant` exist: Ed25519, one public key plus digest, states pending/active/revoked/decommissioned, at most one pending-or-active identity per equipment | Source of the `agents` stream; only `agent_uid` and active state; public keys excluded |
| Layering | Labs model tree; features use `application/`, `queries/`, `public.py`, `contracts.py`, `exceptions.py` | Follow these conventions |

## Appendix B. Publisher port

```python
@dataclass(frozen=True)
class RoutingChangeInput:
    entity_type: str      # "users" or "agents"
    key: str              # user_key or agent_uid
    op: str               # "upsert" or "delete"
    state: str | None     # validated per entity; None for delete
    data: dict | None     # validated per entity; {} for upsert; None for delete

@dataclass(frozen=True)
class PublishResult:
    version: int | None   # version assigned, or the current version if nothing changed
    changed: bool

class RoutingPublisherPort(Protocol):
    def publish(self, change: RoutingChangeInput) -> PublishResult: ...
```

Illustrative only. It is not the callable Python API and does not approve a generic publisher. `routing.public` exposes the implemented source-specific commands.

```python
@transaction.atomic
def revoke_agent(agent_uid, actor):
    identity = AgentIdentity.objects.select_for_update().get(agent_uid=agent_uid)
    identity.state = "revoked"
    identity.save(update_fields=["state"])
    routing.publish(RoutingChangeInput("agents", key=str(identity.agent_uid), op="delete", state=None, data=None))
    audit(actor, "agent.revoke", identity)
```

## Appendix C. Optional mTLS profile (use only if X2 is overridden or the platform provides it)

mTLS is **in addition to** AUTH-1..AUTH-16, never instead of the bearer credential. It requires the backend or the platform in front of it to hold Router-specific trust configuration (a CA or certificate-identity allowlist), which conflicts with AUTH-11 unless the platform layer holds it outside the backend. Prefer the simplest trust path:

1. **Platform-native** (service mesh sidecar or ingress with client-certificate authentication): let the platform authenticate the Router and enforce a certificate-identity allowlist. The application still validates the bearer token and does not parse certificate headers.
2. **Direct termination in the application server**, if it exposes the verified peer identity to the application: no proxy attestation is needed.
3. **Reverse proxy terminating mTLS in front of Django** only if the following hold, otherwise block the API rather than fall back to bearer-only or source-IP-only:
   - the proxy requires and verifies client certificates on a dedicated listener (chain, validity, key usage/EKU, explicit identity allowlist) and fails closed on absent, invalid, expired or revoked certificates;
   - the proxy strips every inbound client-supplied identity or forwarding header (`X-Forwarded-*`, `X-SSL-*`, `X-Client-Cert` and equivalents) before setting its own attestation;
   - Django trusts the attestation only when the TCP peer is the configured proxy over an isolated, authenticated proxy-to-app boundary (private socket or network plus firewall, preferably a cryptographically verifiable assertion), and rejects missing, malformed or unrecognized attestation;
   - the attestation is bound to the request or connection and cannot be replayed from an untrusted path;
   - tests cover spoofed headers, direct-app bypass, missing, invalid, revoked and disallowed-identity certificates;
   - Security and Operations review the actual proxy product and configuration before deployment.

Router certificates are never Agent installation certificates (C10).

## Appendix D. Superseded designs (removed from the normative text)

The previous draft carried these as historical context. They are not part of the target and must not be implemented or copied into `openapi/routing-sync.yml`:

- The `equipment` ownership stream and the `agent_keys` stream (public keys, key status, revocation as `agent_keys` state). Replaced by `users` and `agents` (C2). The database labels remain temporarily (C7).
- `GET /internal/equipment/{equipment_uid}` (single ownership lookup).
- The equipment-move procedure between backends, including source/destination tombstones and `421` for stale callers. A move would need a separately approved ownership-transfer design.
- The single `GET /internal/sync/{entity}` endpoint with `full` and `delta` modes and retained snapshot generations (replaced by `snapshot` and `changes`; section 8.4).
- Mandatory bearer **and** mTLS with proxy attestation (replaced by X2; retained as Appendix C).

The previous revision remains in version control for traceability.

## Appendix E. Test vectors

Canonical claim payload and hash (section 5.3):

```text
canonical JSON : {"data":{},"state":"active"}
data_hash      : 43f154ed4a9512251f4b2bf1e0588c167a2ac83c224de4f4bcc28adf2d720fd5
```

Digest (DIG-1). Rows are listed in the order they are hashed (ascending key); every row has `state="active"` and the `data_hash` above.

| Stream | Live keys (ascending) | `checksum` |
|---|---|---|
| `users` | `entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000001`, `entra:11111111-2222-3333-4444-555555555555:aaaaaaaa-0000-0000-0000-000000000002` | `sha256:e55f21dda5b3742e8baa44eeadfb712312907f2226c940cdb9dc843b5dce5a13` |
| `agents` | `bbbbbbbb-1111-0000-0000-000000000001` | `sha256:2ce74e51f5d7cb73601acd527318a602672acf5cb3f712dcf1b18ac183f96e70` |
| either (empty) | none | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Reference implementation:

```python
import hashlib, struct
def digest(rows):                      # rows: iterable of (key, state, data_hash_hex)
    m = hashlib.sha256()
    for key, state, h in sorted(rows, key=lambda r: r[0].encode()):
        k, s = key.encode(), state.encode()
        m.update(struct.pack(">I", len(k)) + k + struct.pack(">I", len(s)) + s + h.encode())
    return "sha256:" + m.hexdigest()
```
