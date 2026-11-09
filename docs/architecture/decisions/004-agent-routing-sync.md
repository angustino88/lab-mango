# ADR 004: Agent routing and backend sync decisions

- **Status:** Approved constraints; implementation phases authorized separately in sync design review; architecture/security/operations review and runtime gates remain pending
- **Date:** 2026-11-07
- **Scope:** Lab Mango backend routing projection and Edge-facing sync contract
- **Related specs:** [Backend Routing and Sync Spec](../../backend-routing-sync-spec.md), [Backend Agent API Design](../../backend-agent-api-spec.md)

## Context

The backend routing-sync and agent-platform documents define a conceptual cross-repository target. This worktree contains R0 routing projection **models** and migrations 0011/0012; it has no routing publisher, populated-stream guarantee, or mounted internal sync API. Applied/deployed migration status is not independently verified. It has an `EntraIdentity` binding with tenant/object UUIDs, an enrollment-only agent foundation, existing MonitoringEvent ingestion, computing activity state, and booking feature-owned commands. Migrations, API changes, cross-feature publication, authentication, and booking changes are T2 work.

The proposed routing design originally left `user_key` ambiguous and contemplated a separate `UserRoutingKey`. The product discussion established that Edge needs a stable key for mapping a signed-in identity to its owning backend, not a user display directory. Usernames/names are not required for routing and must not be sent to Edge.

## Decision and owner-confirmed constraints

These identity constraints were confirmed by the human owner during design review:

1. Derive an opaque routing key from the existing Entra identity pair: `entra:<lowercase-tenant-uuid>:<lowercase-object-uuid>`.
2. Use existing `EntraIdentity(tenant_id, object_id)` as the identity source; do not add a separate `UserRoutingKey` table solely to duplicate it.
3. Omit users without a linked Entra identity from Edge user routing.
4. Publish the key and routing state only. Do not publish username, display name, email, local user ID, or any other profile data.
5. On explicit unlink/deactivation/deletion, tombstone the previous key. An identity replacement is a new routing key, never an implicit ownership/history transfer. Transient lookup failures must not cause tombstones.

The above decisions settle the identifier source and data-minimization intent, but do not by themselves approve an implementation or close lifecycle transaction details.

## Agent booking capability boundary

The owner-approved Agent capability direction is that an Agent may, after body-based booking-code check-in binds the booking delegation to that Agent's backend session:

1. Read only the eligible booking authorized by that code and the server-resolved Computing-to-bench assignment.
2. Update only that booking's `ends_at`, subject to booking-owner policy, eligibility checks, concurrency preconditions and durable retry semantics.
3. Explicitly complete that same eligible booking through a dedicated action delegated to the bench-bookings owner command.

The booking code is a booking-scoped credential, not proof of the named user's identity. Agent mTLS proves device identity; it does not grant user or general booking authority. The backend rechecks Agent, session, assignment and booking eligibility on each write. Session end, OS logoff, timeout, Agent deactivation or an ingested event must not implicitly complete a booking. The Agent cannot otherwise create, approve, cancel, reassign, change ownership or start time, rewrite the code, or arbitrarily set booking status.

This records the capability boundary and does **not** approve endpoint exposure, schema, mTLS deployment, or implementation. On 2026-11-09 the owner confirmed booking belongs in the eventual full Agent target, requested a design package before PKI/TLS implementation, and selected `GET /agent/bookings/code/{booking_code}` for read-only eligible-booking lookup, separate from body-based check-in. This backend is responsible for booking authorization/session actions only; it does not claim to enforce workstation or desktop access. The credential-in-URL endpoint remains a T2 security/API release gate; it requires an explicit reviewed exception and verified redaction/throttling/no-store/no-echo controls. Booking API/session work requires the design, security/QA reviews and implementation approval. See [Section 7 of the Backend Agent API Design](../../backend-agent-api-spec.md#7-booking-reads-and-additional-session-gates) for the current proposed contract and gates.

## Consequences

- The revised target includes active Entra-bound users. LDAP/URS/local accounts without an `EntraIdentity` remain outside that target unless a stable identity strategy is separately approved.
- The key serializer must have stable canonical UUID formatting and the `entra:` namespace prefix; it is not an API/version prefix. It is a stable, linkable pseudonymous identity datum, not anonymous data; consumers must treat it as opaque and protect it as sensitive identity data. R2 must approve access, logging, and retention controls before any key is emitted.
- User identity mutations and routing publications must be atomic or use an approved durable mechanism; all relevant mutation paths must be inventoried before enabling the stream.
- No profile/name synchronization to Edge is part of this ADR. Any user-directory/profile synchronization is a separate feature and data-purpose decision.

## Not decided here

This ADR does not define or decide:

- Equipment routing eligibility or mapping from current resource lifecycle statuses to routing ownership state.
- Agent/key cardinality or the final mapping of current identity/key states to `agent_keys`.
- Routing table schema, publisher implementation, all relevant write-path coverage, lock ordering, version stream semantics, rebuild/backfill, retention, epoch rotation, restore, or rollback.
- Internal API authentication, token rotation, network allowlists, API error-envelope adaptation, pagination, long-poll runtime, or `LISTEN/NOTIFY` deployment.
- Agent assertion/token/key policy, nonce store, telemetry ownership/retention, and booking session/code implementation details, including endpoint schemas, OS-session enforcement, online/offline policy, issuance/storage/rotation of booking codes, and terminal/unapproved-booking behavior.

These identity constraints remain applicable to the revised `users` target. The owner revised the stream scope on 2026-11-07 to `users` and `agents` and authorized design + R0 schema work only; R1 publisher and R2 API implementation require separate approval as recorded in the companion sync spec. This ADR does not authorize runtime behavior or deployment.

## Alternatives considered

- **Username or email as `user_key`:** rejected for routing because these are mutable/profile identifiers and may be ambiguous across departments; also conflicts with routing payload minimization.
- **General `UserRoutingKey` field/table:** not selected because the existing verified Entra pair already supplies a unique identity for the approved supported population. A separate key may be reconsidered only if non-Entra accounts must be routed.
- **Send display names to Edge:** rejected for routing; Edge needs an identity key, not user profile data.

## Approval

- Human owner: **Confirmed** (identity key source and data-minimization constraints; revised target includes users; design + R0 only)
- Human owner: **Confirmed** (Agent booking capability boundary: scoped end-time update and explicit completion after Agent-bound backend check-in; no OS access-gate enforcement claim; booking implementation remains gated)
- Architecture review: **Pending**
- Security/privacy review: **Pending**
- Routing implementation authorization: **Not granted by this ADR**; booking API/session implementation authorization: **Not granted by this ADR**
