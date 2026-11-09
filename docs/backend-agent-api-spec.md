# Backend Agent API Design

Status: Proposed protocol and routes · mTLS direction and six-phase core plan accepted by owner · 2026-11-08
Owner: backend team · Protocol, PKI, API, security and operations approval pending

This document owns backend-facing Agent design, not a deployed contract. Acceptance of the direction
does not approve final schemas, CA selection, migrations or deployment. The [device design](agent-design-spec.md)
owns client behavior; the [routing-sync design](backend-routing-sync-spec.md) remains sole routing authority
and is unchanged. Model definitions remain in the [Labs model architecture](../core/labs/models/docs/labs-model-architecture.md).

## 1. Repository facts and scope

**Verified — source inspection only, not runtime certification:**

| Foundation | Evidence | Limits |
| --- | --- | --- |
| Agent identity / hash-only grants | [models](../core/labs/models/agents/agent_identity.py#L13-L117), [public commands](../core/labs/features/agents/public.py#L3-L38) | Current `pending/active/revoked/decommissioned`, single Ed25519 key; not certificate generations |
| Enrollment commands | [grant creation](../core/labs/features/agents/application.py#L89-L139), [proof verification](../core/labs/features/agents/application.py#L203-L310) | Foundation only, not mounted CSR/challenge or mTLS API |
| Computing snapshot | [ComputingEquipment](../core/labs/models/resource/equipment/computing.py#L23-L43) | Owns `hostname`, `os_name`, `ip_address`, `disk_usage`, `system_info`; no snapshot ordering metadata established here |
| Separate live activity | [model](../core/labs/models/activity/computing_activity.py#L7-L38), [command](../core/labs/features/equipment/categories/computing/application.py#L69-L107) | Reports refresh activity `last_agent_report_at`, not identity liveness |
| Monitoring command | [public facade](../core/labs/features/monitoring/public.py#L1-L15), [persistence](../core/labs/features/monitoring/application/commands.py#L34-L98) | Duplicate insertion conflicts; no same-content replay acknowledgment, snapshot or liveness side effects |
| Narrow Agent booking end-time update | [command](../core/labs/features/bench_bookings/application/update_agent_booking_end_time.py#L29-L108) | Active identity → Computing assignment → bench → booking; no Agent session or durable request-key idempotency |
| Existing activity HTTP adapter | [routes](../core/labs/features/equipment/api/urls.py#L37-L41), [adapter](../core/labs/features/equipment/categories/computing/api.py#L61-L100) | SKU-based existing API, not the proposed installation-authenticated surface |

**Verified discovery limits:** scoped searches of backend models/features/routes found no `AgentInventory`,
`MetricSample`, separate hardware inventory domain, mounted new Agent lifecycle surface or dedicated raw-session
ingestion. This is a source-search result, not a deployment audit. External Agent implementations were not inspected.

**Proposed target scope:** operator lifecycle, bootstrap, installation mTLS, computing state, activity,
monitoring, heartbeat, and booking-code lookup/check-in with backend booking-session actions. The owner
selected booking for the eventual implementation scope, selected `GET /agent/bookings/code/{booking_code}`
for retrieving the eligible booking by code, selected a design package before PKI/TLS implementation, and
selected backend check-in/session authorization only: this backend does not claim to block desktop login
or enforce an OS access gate. These selections
authorize design work, not credential trust, API release, migration, infrastructure or production behavior.
The [device design](agent-design-spec.md) must treat OS access control as a separate approved device project.

## 2. Owner / consumer ledger and smallest design

**Verified consumers; Proposed ingestion decisions:** targeted review, not exhaustive reporting-feature certification.

| Data / owner | Actual consumer evidence | Proposed decision |
| --- | --- | --- |
| Computing snapshot / equipment | [category detail/list](../core/labs/features/equipment/api/category_definitions.py#L25-L50), [dashboard IP/OS](../core/labs/features/dashboard/api/serializers.py#L313-L351), [RDP host](../core/labs/models/resource/equipment/computing.py#L54-L57) | One bounded snapshot; hardware only in typed allowlisted `system_info`, disks in `disk_usage`; no duplicate inventory store |
| Live activity / equipment | [public projection](../core/labs/features/equipment/public.py#L8-L10), [dashboard status/freshness](../core/labs/features/dashboard/api/serializers.py#L313-L351), [stale sweep](../core/labs/features/equipment/categories/computing/application.py#L166-L191) | Separate route/state machine; expose command and DTO through equipment public/contracts facades before new adapter |
| Monitoring events / monitoring | [selectors](../core/labs/features/monitoring/queries/selectors.py#L12-L65), [public command](../core/labs/features/monitoring/public.py#L1-L15) | Reuse owner, explicitly extend retry contract; no parallel event persistence |
| Completed raw sessions / session persistence | [LabSessionLog](../core/labs/models/session/lab_session.py#L15-L38), [asset-utilization consumer](../core/labs/features/analytics/queries/utilization.py#L83-L110) | Consumers exist; defer ingestion until mapping, minimization, retention and corrections approved; events do not automatically populate logs |
| Bookings / bench-bookings | [Agent end-time use case](../core/labs/features/bench_bookings/application/update_agent_booking_end_time.py#L29-L108) | Reuse owner commands; separately approve scoped reads and sessions |
| Agent liveness / agents | [last_seen_at](../core/labs/models/agents/agent_identity.py#L44-L49) | Separate heartbeat policy, not activity/booking mutation |
| Hardware inventory / time series | No independent model or time-series consumer found in scoped search | No separate inventory/metrics route, rollups or telemetry database; reconsider only with named consumer, owner and retention case |
| Licenses, procurement, expenses | Scoped Python source search found no Agent ingestion requirement | No new Agent ingestion scope |

**Proposed decision:** smallest change extends existing owners through [public boundaries](feature-template.md#3-dependency-rules).
A separate inventory/event/time-series domain adds duplication and retention without demonstrated need.
Snapshot, live activity, monitoring observations, Agent liveness, resource lifecycle, assignments,
booking and booking-session status stay distinct; observations are not implicit commands to change them.

## 3. Identity and authorization

**Proposed — three independent identities:**

| Identity | Purpose / limit |
| --- | --- |
| `agent_uid` | Backend-generated logical Agent associated with one Computing resource; stable across renewal, not a credential or hostname |
| Agent installation certificate | Locally generated key plus issued X.509 credential; independently renewable/revocable generations |
| Router service certificate | Independent provisioning/trust/authorization; no Agent, equipment or entity registration |

Routing carries logical ownership/eligibility, never credentials or revocation authority. Heartbeat,
snapshot/activity/monitoring reports and renewal do not themselves churn routing versions. Lifecycle
routing effects follow the routing owner, not a second protocol here.

**Proposed authorization matrix:**

| Surface | Authentication | Authorization |
| --- | --- | --- |
| Operator `/api/labs/...` | Existing user authentication | Approved roles and object scope; recent reauthentication where required; cookie writes retain CSRF/origin checks |
| Bootstrap challenge/enrollment/recovery | Server TLS + bound grant/fresh installation-key proof | Context/challenge/operation/identity policy; no already-issued client certificate needed |
| Other `/agent/...` | Verified installation mTLS | Every request checks usable DB credential, active DB identity, operation permission and object scope |

Derive Computing from verified identity, never client-selected equipment ID/UID/SKU or header. Authorize
every booking/session/certificate reference. SAN text alone is not trust: verified chain/profile must
map to persisted issuer/serial/key binding. Operator and installation credentials are not interchangeable.

**Proposed denial baseline:** no positive authorization cache. After denial commits, subsequent checks
reject even on reused TLS connections/session resumption. Already-authorized in-flight work is not
retroactively canceled; define its completion policy and recheck sensitive writes under race guards.
Later caching needs approved invalidation, bounded freshness, fail-closed behavior and measured delay.
Handshake validation, short certificate life or CRL/OCSP alone cannot guarantee DB revocation.

**Proposed termination gate:** choose TLS terminator and authenticated private proxy-to-app evidence
transport; strip inbound identity headers and block direct-app/alternate-route bypass. Plain forwarded
certificate headers are not trusted by convention. Separate browser/bootstrap and installation trust
requirements. No infrastructure change is authorized here.

### 3.1 Installation authentication flow

Recommended deployment design: dedicated Nginx Agent TLS listener/virtual host with mandatory client
verification, separate from server-TLS-only bootstrap and browser traffic. TLS client-certificate
negotiation occurs before HTTP path selection; a location alone cannot supply a separate handshake
policy. If a shared listener is selected, explicitly design optional handshake verification plus
fail-closed per-route enforcement and test session resumption/bypass behavior. Use independent Agent and
Router trust/authorization policies. The exact listener topology and identity attestation mechanism
remain operations/security approval gates, not existing configuration.

1. Agent presents its issued client certificate and proves private-key possession during TLS.
2. Terminator verifies issuer chain, validity and approved client-auth profile. It removes all inbound
   identity headers and sends verified issuer/serial/key binding through an authenticated private
   channel to Django. Client-supplied identity evidence and direct app access are rejected.
3. Django resolves that binding to a persisted usable credential and active logical Agent. A certificate
   with no matching record is denied even if its chain is valid. Authorization uses authoritative DB
   reads on every request, including persistent TLS connections; failures deny access.
4. Agent identity derives Computing and operation permissions server-side. For booking login, the
   booking code supplies a separate booking-scoped delegation, as defined in section 7; the client
   certificate alone supplies no user authority and the code alone supplies no device authority.
5. Lifecycle-sensitive writes recheck credential, Agent and booking/session eligibility under the
   owner's transaction/race guards. Revocation after commit prevents subsequent authorization;
   already-authorized work follows the explicit in-flight completion policy.

Acceptance evidence: reject missing/expired/unknown/wrong-purpose/revoked certificates, forged proxy
headers, direct-app bypass and cross-Agent session use. Confirm next-request denial after revocation
on reused TLS connections, certificate-generation revocation during renewal overlap, and issuer outage
recovery without duplicate issuance. No shared API-key fallback is introduced.

## 4. Concrete proposed endpoint inventory

**Proposed naming only, not implemented or final schemas:** slashless, unversioned paths. `{id}` is
resource API `id`, with final type fixed by schema. Device paths are backend-local; deployment prefix
is owned elsewhere. All lists bounded/paginated; GET/HEAD never mutate state, audit or liveness.

### 4.1 Operator lifecycle — user authentication and object-scoped roles

| Method / path | Purpose / gate |
| --- | --- |
| `POST /api/labs/agents` | Idempotently create pending identity + initial grant for authorized Computing; no activation before durable valid issued credential |
| `GET /api/labs/agents` | Bounded identities, no grants/private material |
| `GET /api/labs/agents/{id}` | Scoped detail, strong ETag |
| `POST /api/labs/agents/{id}/enrollment-grants` | New/recovery grant atomically revokes outstanding grants; replacement/identity reuse policy required |
| `POST /api/labs/agents/{id}/actions/deactivate` | Disable eligibility; state/reactivation/credential consequences remain protocol gate |
| `POST /api/labs/agents/{id}/actions/revoke` | Commit identity denial, invalidate authority; repeated action safe |
| `POST /api/labs/agents/{id}/actions/decommission` | Retire identity under retention policy, not equipment deletion |
| `POST /api/labs/agent-certificates/{id}/actions/revoke` | Scoped credential-specific revocation; top-level collection avoids two-level nesting |
| `GET /api/labs/agents/{id}/certificates` | Optional bounded public credential metadata inventory, no private key export |

Grant creation returns generated secret only in authorized creation result, hash-only grant persistence,
`no-store`; replay must not mint another grant. **Open API/security gate:** original-response replay of
one-time secret conflicts with ordinary response storage. Approve protected short-lived replay handling
consistent with hash-only grant storage/minimization or a narrowly documented alternative; never silently
persist plaintext grants in a general idempotency table. No solved implementation is claimed.

### 4.2 Bootstrap and certificate lifecycle

| Method / path | Purpose / trust |
| --- | --- |
| `POST /agent/enrollment-challenges` | Fresh bounded nonce for bound enrollment/recovery; rate-limit/context non-enumeration |
| `POST /agent/enrollments` | Create issuance operation from CSR + grant + domain-bound fresh proof over server TLS |
| `POST /agent/enrollments/actions/recover` | Fresh proof + bound operation context return SAME issuance/result, not grant re-redemption |
| `POST /agent/certificates/actions/renew` | Currently usable mTLS credential + renewal CSR/new-key proof; idempotent issuance |
| `POST /agent/certificates/actions/confirm` | New credential proves usable through mTLS; retire old under overlap policy |

Bodies carry approved operation/certificate references, not standalone authority. Lost enrollment
response recovery requires no client certificate but fresh proof for the bound key. Expired/revoked/
disabled credential cannot renew; operator recovery is required.

### 4.3 Core reporting — mTLS and per-operation permission

| Method / path | Purpose |
| --- | --- |
| `GET /agent/info` | Capabilities/limits and canonical server identity; no separate ping required |
| `POST /agent/heartbeat` | Bounded Agent health/liveness, not activity freshness |
| `PATCH /agent/equipment/state` | Bounded computing snapshot; hardware only in allowlisted `system_info`, disks in `disk_usage` |
| `PATCH /agent/equipment/activity` | Separate live resource activity through equipment owner command |
| `POST /agent/events` | Bounded monitoring batch through monitoring public command; no snapshot/raw-session side effects |

**Implemented interim (2026-11-09, owner-selected until installation mTLS exists):** `POST /agent/heartbeat`
requires a request signed by the identity's enrolled Ed25519 key, not a client-supplied `agent_uid`.
Headers: `X-Agent-Id` (agent_uid), `X-Agent-Timestamp` (unix seconds), `X-Agent-Nonce` (base64url, at
least 16 random bytes) and `X-Agent-Signature` (base64url Ed25519 signature). The signed bytes are the
NUL-joined `labmango-agent-request-v1`, `backend_id`, `agent_uid`, upper-case method, path, timestamp,
nonce and the hex SHA-256 of the raw body (`core.agents.application.agent_request_message`). The server
reads the ACTIVE identity on every request (no positive cache, so revocation applies to the next request),
rejects timestamps outside `AGENT_REQUEST_MAX_SKEW_S` (default 300 s) and nonces seen within twice that
window (`cache.add` on the shared cache, after the signature verifies). Every failure is the same `401`
(`WWW-Authenticate: LabMango-Agent-Signature`). `/agent/info` advertises `request_signature_v1`. This is
not a shared API key; mTLS replaces it when phase 3 lands. Operator writes under `/api/agents` require the
Labs coordinator role (admin implies it); reads require authentication only.

### 4.4 Booking capability (design scope; implementation still gated)

| Method / path | Purpose / permission |
| --- | --- |
| `GET /agent/bookings` | Bounded scoped display list / `bookings:read` |
| `GET /agent/bookings/{id}` | Scoped ID detail / `bookings:read` |
| `GET /agent/bookings/code/{booking_code}` | Code-based eligible booking lookup only; does not create a session / `bookings:read`; credential-in-path risk requires Security/API gate |
| `POST /agent/bookings/actions/checkin` | Code in strict request body creates/resumes bound session / separately enabled `bookings:checkin` |
| `POST /agent/booking-sessions/{id}/actions/keepalive` | Lease reconciliation / `bookings:checkin` |
| `POST /agent/booking-sessions/{id}/actions/end` | End session only / `bookings:checkin` |
| `PATCH /agent/bookings/{id}` | Only `ends_at` mutation, session reference in body, preconditions / `bookings:end_time:write` |
| `POST /agent/bookings/{id}/actions/complete` | Explicit session-bound completion / separately approved `bookings:complete` |

Booking owner resolves Computing assignment to bench and eligible booking; no arbitrary shared-bench
authority. Multiple devices/session cardinality need product policy; ambiguity denies. Do not assume
one-Agent-per-bench constraint. Although included in the user's intended full scope, booking implementation
remains gated on the decisions and security/QA review in sections 7–9.

## 5. Enrollment, issuance and lifecycle reliability

**Proposed workflow:** trusted provisioning gives canonical backend identity/origin, pending `agent_uid`,
protocol and server trust. Deliver grant transiently via protected prompt/channel, never URL, CLI,
durable config or diagnostics. Windows/Linux use one protocol and platform key adapters. TPM-backed
non-exportable storage preferred, not mandatory; approved protected OS/software fallback allowed.
Claims are not attestation. Algorithm/provider compatibility with current Ed25519 is not established.

1. Journal non-secret operation context, CSR digest and key handle before sending; retain same key for
   recovery. Operation identifier is not client assignment of a resource primary ID.
2. Fresh proof binds protocol/domain, canonical backend/audience, logical identity, operation, grant
   digest, CSR/key digest and nonce. Encoding/lifetime/consumption/rate limits need approval; CSR
   signature alone does not bind grant/backend.
3. Validate grant scope/expiry/revocation, identity eligibility, CSR/proof and challenge. Construct
   permitted subject/SAN/EKU server-side; never copy arbitrary CSR extensions.
4. Reserve unique issuance operation with DB constraints/locked transitions. Sign externally using
   stable issuer operation identifier, outside DB locks.
5. External signing is not atomic with DB. Reconcile timeout via issuer lookup/deduplication or approved
   alternative, never blindly sign again. Record orphan issuance as revokable after failed completion.
6. Persist verified valid credential/result durably before activation. Pending denial/approval or
   revocation blocks signing completion/activation; enrollment-pending alone is not permission to activate.
7. Client verifies chain/profile/identity/validity/key match and installs crash-safely. Fresh-proof
   recovery returns same bound result, never reopens grant or revives revoked identity.

**Proposed distinct conflict layers:**

| Layer | Contract |
| --- | --- |
| HTTP `Idempotency-Key` | Credential + method + path; identical body → original status/body and `Idempotency-Replayed: true`; changed body/same key → `422 idempotency_key_reuse`; pending → `409 request_in_progress`; no stored `5xx` |
| Domain issuance operation | Unique grant/identity/context/CSR binding; competing/changed CSR binding → `409 enrollment_conflict` after header checks; fresh-proof recovery is new exchange for same operation/result |

Authentication/object checks precede replay; replay skips preconditions/execution, not authorization.
Approve retention and credential scoping across bootstrap/renewal, including bootstrap without issued
certificate. Fresh proof changes are not identical-body HTTP retries. Define issuance status/result
access before choosing asynchronous `202`; it needs durable status resource and authorized `Location`,
not a missing polling endpoint or an assumed deployed schema.

**Proposed renewal:** journal generations/phase; usable old credential plus new-key proof reserves
renewal; validate/install new; confirm through new mTLS; retire old under bounded overlap. Reconcile
loss/crash; never discard only usable key early. If neither works, operator recovery; no endless retry.

**Proposed lifecycle:** commit denial/invalidate grants and recovery authority first, then reconcile
issuer revocation and owner-defined routing effects. Define deactivate/revoke/decommission, replacement,
in-flight semantics and retention before new states. Heartbeat/renewal cannot revive disabled identity.
Key loss, expiry, TPM reset, reimage or compromise needs operator recovery, never private-key export
or automatic cross-backend adoption. Restore reconciles issuer inventory and preserves revoked denial.

**Required PKI gate:** issuer/custody owner, signing API/deduplication/audit, managed/HSM custody outside
Django/images/backups, algorithms/key sizes, clientAuth non-CA leaf, SAN encoding, serial/key binding,
lifetime/renewal/overlap, revocation/failure policy and Windows/Linux TLS fixtures. No CA/dependency
selected. Existing identities need reviewed additive migration/re-enrollment/cutover and rollback.

## 6. Reporting contracts and separation

**Proposed snapshot:** allowlisted `hostname`, `os_name`, `ip_address`, `disk_usage`, `system_info` plus
approved observation metadata. Typed nested hardware/OS facts, units and byte/string/array/depth/frequency
limits; no arbitrary blob. Additional OS version belongs in approved `system_info` schema unless a
separate model change is approved. Reject lifecycle, owner, SKU, RDP file/options and technical user.
Category CRUD remains read-only for Agent-owned fields; no manual-input bypass.

**Required ordering gate:** stable snapshot ID/content, untrusted `collected_at`, server `received_at`,
skew, ordered retry/tie/stale semantics and race guard are required work, not assumed current columns.
Define equal-time changed-content conflict, stale acknowledgment and no-op ETag before implementing.
Reported versus observed IP/interface selection must be explicit.

**Owner-selected direction (2026-11-09):** Agent does not update the operational hostname/RDP target.
The current [host selection](../core/labs/models/resource/equipment/computing.py#L54-L57) and
[save regeneration](../core/labs/models/resource/equipment/computing.py#L122-L145) affect RDP destination.
If reported hostname is retained, keep it distinct from the manually maintained target and define its
owner, freshness, validation and display semantics before schema/API implementation. Agent cannot
manipulate RDP files. No schema/behavior change is authorized here.

**Proposed activity:** preserve live state machine and owner timestamps. New adapter needs equipment
public command/contracts facade, not private category reach-through. Existing
[stale sweep](../core/labs/features/equipment/categories/computing/application.py#L166-L191) uses activity
`last_agent_report_at`; unrelated heartbeat must not keep stale activity alive without explicit owner
policy. Existing personal/session fields are not automatic collection allowlists. Activity is not check-in.

**Proposed heartbeat:** Agent liveness/health only. Decide explicitly if accepted snapshots refresh
identity liveness. Info/read/search never do. Activity freshness and booking lease deadlines are separate.

**Proposed monitoring:** adapter maps bounded typed events to monitoring public command, with server-
derived Computing/Agent identity, immutable IDs/content, timestamps, retention and DB retry guards.
Current duplicate conflicts must be extended before same-content replay acknowledgment is claimed;
changed content never overwrites. No snapshot/activity/liveness/booking/session-log side effects.
Dedicated raw-session ingestion deferred pending mapping/minimization/retention/corrections.

Atomic batch is smallest initial proposal: validate/commit all or none, then `200` standard result.
Explicit partial mode, if approved, returns `200` per-item outcomes under BLK-2, never undifferentiated
`4xx` after partial writes. Freeze batch schema against ACB/BLK before implementation. Future async
needs durable `202` and authorized status-resource Location/reconciliation, not volatile acceptance.

## 7. Booking reads and additional session gates

### 7.1 Booking-code login and delegated Agent access

**Owner-confirmed use case:** the user supplies their booking code to log in at the Agent. Possession
of a valid code is a booking-scoped credential, not proof that the presenter is the named employee or
a general user-login token. A shared/stolen code can be used by its holder; do not infer personal identity
from it. Stronger named-user authentication, if required, needs a separate user-authentication step.

The authorization decision combines two independent proofs:

- **Device proof:** verified mTLS → usable credential → active Agent → server-derived Computing.
- **Booking proof:** code → eligible booking on that Computing's applicable bench → permitted window
  and approval/status. Successful check-in records the user's booking delegation in an Agent-bound session.

Thus the Agent may read the eligible booking using the code and update that booking after successful
check-in. It need not independently authenticate as the user, but cannot use a code for another bench,
another Agent's session or an expired/canceled/unapproved booking. Backend-owned assignment resolution
remains necessary to connect a bench booking to the machine; code possession does not authorize any machine.

Check-in sequence:

1. User enters code into the local UI; the Agent may request the eligible booking using
   `GET /agent/bookings/code/{booking_code}`. This read does not check in or create a session. To start
   the booking session, the client separately submits the code in the strict body of
   `POST /agent/bookings/actions/checkin` using mTLS.
2. Bench-bookings validates eligibility under transaction/race guards, creates or resumes the permitted
   Agent/booking-bound backend session idempotently, and returns only a minimal booking/session result.
   Code submission is not irreversibly consumed on a lost response; retries reconcile the same session.
3. The client discards the transient code after confirmed check-in. This backend authorization does not
   enable or enforce workstation/desktop access. Follow-up keepalive/end/end-time/completion calls use the
   bound session reference plus mTLS, not repeated codes.

Permitted booking updates are `ends_at` and separately enabled completion through existing owner commands.
They do **not** include rewriting `booking_code`, ownership, approval, start time or arbitrary status.
Here "update by booking code" means updating the booking identified by the login code, not rotating that
credential. If code replacement is required, design a separate operator/booking-owner action that issues
a server-generated replacement and defines invalidation of old code and active sessions.

Every follow-up request checks the same active Agent/session and current booking eligibility; cancellation,
session termination or credential denial stops subsequent actions. Session reference alone is not a user
or device credential. Lists/previews never return usable booking codes. Add tests for foreign code, copied
session reference, replay/conflicting login, canceled/expired booking and unauthorized field updates.

### 7.2 Read contract and credential handling

**Owner-selected access pattern (2026-11-09):** `GET /agent/bookings/code/{booking_code}` retrieves
the eligible booking using its code. This GET is read-only: it does not check in, consume the code,
create a session or establish the named user's identity. `POST /agent/bookings/actions/checkin`
separately accepts the code in its strict request body to create/resume a session. The GET path is a
deliberate credential-in-URL risk and remains gated on the security/API controls below; it is proposed,
not implemented or approved for release.

List/detail minimize to ID, times, approved status representation and necessary ETag metadata;
no code/creator/reason in Agent response schema. All `no-store`, scoped/throttled. ID and code lookup
return generic `404 booking_not_available` for invalid/foreign/unavailable bookings. Bound list windows,
pages and code length/format; never echo the supplied code in response details, logs, traces, metrics or
diagnostics. Before code-in-path GET release, approve the credential-URL exception and verify redaction
in proxy access logs, application logs, traces/APM, errors and diagnostics; redaction does not remove
URL disclosure risk.

**Verified baseline:** existing command permits eligible approved reserved/in-progress end-time update
after assignment resolution; request ID is not durable idempotency/audit. Current booking code
format/storage unchanged; no HMAC/rotation/length migration claimed.

**Proposed gated actions:** check-in verifies code/assignment/approval/time under booking owner guards
and creates/resumes Agent/booking-bound backend session. Owner public commands alone transition bookings.
Approve code protection/migration, shared-device/session cardinality, early/resume windows and policies.
Session references in body are authorization context, not a custom header or authority on their own.
Keepalive reports bounded lease/termination; end changes session only; stale expiry does not complete
booking or refresh activity. PATCH mutates only `ends_at`, with session reference, strong If-Match and
retry key; missing/stale → `428/412`. Atomically recheck active same-Agent session, booking eligibility,
assignment, duration/overlap/extension limits; notify/audit without code. Stricter session/status rules
require approval rather than silently narrowing existing command. Completion separately enabled, not
status field or implicit event/logoff consequence. Writes off pending independent approval; cached reads
never grant access. Backend sessions confer no OS access and no offline authority; workstation access
control is explicitly outside this backend feature.

## 8. Scoped API standards review and compatibility

**Proposed design review only:** pass is design alignment, not runtime test result; violation is blocking
unresolved work. Canonical [request](ai-team/api/request-standard.md) and
[response](ai-team/api/response-standard.md) standards own rules, final OpenAPI owns schemas/examples.

| Rule ID | Status (pass/violation) | Fix / consequence |
| --- | --- | --- |
| MTH-1, WRT-10; HTTP-2 | pass | Bodyless side-effect-free GET/HEAD; ID/code detail and bounded list; GET does not mutate |
| PTH-5–7; TRN-4, ACT-1 | pass | Slashless unversioned resource/actions, credential revoke top-level, one-level nesting |
| HDR-5, PTH-6, QRY-10; SEC-1 | violation | Owner requires code-in-path GET; approve and threat-model credential-URL exception, redaction, throttling, no-store and no-echo before release; check-in remains a separate body-based POST |
| QRY, BDY, TYP, VAL; GEN-3, RW-3 | pass | Strict bounded typed request allowlists; tolerant response clients |
| WRT-3–5/9; RW-5 | pass | Merge Patch/no-op, strong ETag/If-Match where concurrency-controlled |
| WRT-7/8, CHK-1–4; RW-6 | pass | Original status/body replay, replay header, 422 mismatch/409 pending; auth before replay; domain conflict separate |
| AUT-1/3/5, HDR-1; SEC-1/16 | violation | Approve explicit installation-mTLS/bootstrap grant-proof extension, principal mapping and HTTP/TLS challenge/failure semantics |
| WRT-8; SEC-4 | violation | Resolve one-time secret-bearing creation replay versus hash-only storage; no plaintext general replay store |
| ENV, ERR, ENU-1, REL-1, STR-8 | pass | Standard envelopes/error details/request ID/enums; minimized read projections |
| HTTP-4, ACT-2, ASY; ACB/BLK | pass | 201 Location; async requires authorized status resource; atomic batch initially, explicit partial semantics |
| SEC-2/5/10–15, SAF-1/8/9, CCH-1, COL, PRF | pass | Object/property denial, operator CSRF, no-store, redaction/throttles/pages/query budgets |
| TRC-1–3; OBS-1 | pass | X-Request-ID 32 lowercase hex, distinct from operation/retry key |
| TST; DOC | violation | Final schemas/examples/contract tests/OpenAPI not produced here; required with implementation |

**Proposed classification:** every section 4 endpoint is future additive new API (CMP-1/VER-2), not
rename of a mounted legacy route. Cleaning obsolete proposal text has no production compatibility impact.
Mounted routes/payloads/Ed25519 foundation unchanged. Tightening existing behavior, code/state changes or
existing-client mTLS cutover are breaking (CMP-2/VER-2): owner approval and migration/deprecation/rollback
required. Capabilities list only implemented approved operations, never proposals. No generated OpenAPI edit.

## 9. Six-phase core plan and acceptance evidence

**Accepted direction; Proposed evidence, not completed work:**

| Phase | Scope | Required exit evidence |
| --- | --- | --- |
| 1 | Finalize enrollment protocol, CA and profile | Proof/challenge/recovery, issuer reconciliation/custody, Windows/Linux fixtures, trust termination, privacy/migration approval |
| 2 | Agent creation and enrollment APIs | Operator role/object tests, hash-only grants/approved replay, strict schemas, expiry/lockout, PostgreSQL races, pending issuance |
| 3 | Issuance and mTLS authentication | Durable binding/same-result recovery, no premature activation, orphan reconciliation, per-request DB denial, spoof/cross-identity/TLS-reuse tests |
| 4 | Computing state, activity, monitoring and heartbeat | Public boundaries, bounds/order/retry/ties, atomic monitoring/replay, liveness separation and hostname/RDP decision |
| 5 | Renewal, revocation and recovery | Confirm/overlap/crash/race/outage tests, credential denial, operator replacement, retention and restore drill |
| 6 | Nginx configuration and end-to-end staging | Real Windows/Linux, invalid/expired/revoked rejection, header/direct-app bypass tests, measured denial, CA rotation/rollback |

Phase 2 reserves but cannot activate/report issuance success before Phase 3. Minimum DB denial ships
Phase 3, not delayed to Phase 5. Non-production TLS harness first; fleet waits for Phase 6/human approval.
After core phases, add a separately reviewable booking phase: code protection/rotation decision, scoped
code-in-path lookup and strict body-only check-in contracts, DB-enforced session cardinality/idempotency,
booking-owner commands, permission matrix, and contract/concurrency/security tests. Backend-only session
semantics explicitly do not enforce OS access. No fresh runtime certification.

**Proposed enforcement:** architecture/public-boundary tests for new adapters; DB command race/retry
tests for every write; bounded query budgets; negative schema/code-secrecy tests; issuance/outbox/renewal
fault injection. Implementation requires generated OpenAPI/model-owner docs and API/security/QA/operations/
independent review. No central Agent service importing private owners, no new dependency selected.

**Owner-selected design directions (2026-11-09):** eventual scope includes Agent mTLS + booking; prepare
PKI/TLS design before implementation; provide `GET /agent/bookings/code/{booking_code}` for read-only
booking lookup (separate from body-based check-in); backend check-in/session authorization only (no OS
access gate claim); Agent does not automatically update the
operational hostname/RDP target (reported hostname must be handled separately from manual target).

**Still open / approvals required:** API/security: auth-standard extension, grant replay, final schemas,
error/status matrices, numeric throttles and async status access; data: credential/operation constraints,
state/retention/migrations and snapshot ordering; equipment: exact reported-hostname storage and freshness;
monitoring/integration: batch mapping/replay; booking/security/QA: code entropy/storage/hash migration,
rotation, code validity windows, session cardinality, idempotency, check-in timing, completion eligibility,
and role/permission matrix; operations/security: issuer and key custody, signing API/deduplication,
TLS termination/attestation, certificate profile/lifetime/revocation, proxy bypass prevention, restore,
and real-platform evidence. No production implementation or deployment is authorized until decisions,
T2 reviews, human approval and migration/rollout gates are complete.
