# Super-App Core Architecture

## 1. Decision and scope

**Target: a modular Django monolith with vertical business features, a small
shared kernel, explicit technical adapters, and deployment-time composition.**

A super-app is a product containing independently understandable business
applications on a common platform. It is not one universal CRUD engine, one
giant inheritance tree, or a microservice for every feature.

This document owns core/app ownership, deployment composition and rebuild
sequencing. The [feature template](feature-template.md) is authoritative for
feature layout, layer/import boundaries, public interfaces and test ownership.
Specialist documents describe business behavior without redefining that standard.

The requested rebuild permits intentional changes to code and future API/schema
design. It does **not** execute or authorize deletion of any deployed database.
Implement the clean target on an isolated database. Before production cutover,
explicitly choose data migration or an approved reset, document client/task
changes, and test deployment and recovery. After the first target release,
migrations and published contracts become compatibility surfaces again.

### Quality objectives

- **Extensible:** a feature or adapter can be added without editing unrelated
  business applications.
- **Maintainable:** each state change and business rule has one owner.
- **Flexible:** external providers and delivery mechanisms can change behind
  explicit interfaces.
- **Production-ready:** correctness, authorization, concurrent writes, retries,
  deployment, observability, and recovery are tested, not inferred from folders.
- **Proportionate:** functions and Django ORM are the default; add patterns only
  when they solve a demonstrated boundary or lifecycle problem.

## 2. Current project evidence

The repository uses Django, DRF/ADRF, PostgreSQL, Celery, Redis, WebSockets, and
drf-spectacular. Active installed applications are users, common, labs,
jira_integration, and websocket. Named infrastructure adapters already exist.

Benches and locations provide useful application/query/API separation. Labs
persistence covers more capabilities than its active routes expose. Equipment,
licenses, users, and Jira still have differing feature layouts.

Source inspection also found retired imports in task/signal registration,
suppressed startup ImportErrors, inconsistent migration/test wiring, and
competing equipment assignment/status write paths. These are implementation
risks to verify during rebuild; this document does not claim runtime failures
or successful production certification. Older findings about removed utilities,
charts, and old feature trees must not be treated as current inventory.

## 3. Four ownership zones

| Zone | Responsibility | Forbidden responsibility |
| --- | --- | --- |
| `config` | Runtime settings, installed apps, routes, queues, adapter bindings, deployment composition | Business workflows |
| `core.common` | Small domain-neutral kernel and reusable framework primitives | Labs/user/Jira orchestration or concrete external clients |
| `core.infrastructure` | Technical adapters: storage, email, cache, HTTP, messaging, telemetry | Business eligibility, resource ownership, feature transactions |
| Business apps | Models, policies, commands, queries, public interfaces, feature transports | Private internals of another app |

Do not add parallel `shared`, `utils`, `helpers`, `base`, and `platform` dumping
grounds. Keep `common` as the single kernel name. Platform capabilities with
persistent state and a lifecycle are named Django apps, not anonymous helpers.

### Shared-code placement rule

1. Used by one feature: keep it in that feature.
2. Shared by related features with the same business meaning: place it in a
   named app-owned module, such as `labs.resources`.
3. Domain-neutral logic shared by multiple apps: consider `common`.
4. Concrete provider or technical side effect: place it in infrastructure.
5. Stateful reusable business capability: give it an owning app and public API.

Before promoting code, require a named owner, stable semantics, tests, and at
least two real consumers, except foundational primitives required at bootstrap.
Similar-looking business rules are not necessarily the same abstraction.

## 4. Target repository structure

```text
config/
├── settings/
├── composition/                   # explicit module and adapter bindings
├── urls.py
├── api_router.py
├── asgi.py
└── celery_app.py
core/
├── common/                        # framework-neutral kernel + framework helpers
│   ├── contracts/                 # neutral actor, page, error, event, port types
│   ├── domain/                    # small value types and neutral invariants
│   ├── models/                    # opt-in abstract Django persistence primitives
│   ├── api/                       # DRF envelopes, exception mapping, pagination
│   └── testing/                   # neutral fixtures/helpers, no domain factories
├── infrastructure/
│   ├── email/
│   ├── teams/
│   ├── storage/
│   ├── http/
│   ├── cache/
│   ├── messaging/
│   ├── observability/
│   ├── exports/
│   └── remote_access/
├── users/                         # identity, authentication, group membership
├── labs/                          # laboratory operations
├── jira_integration/              # Jira request lifecycle and translation
└── notifications/                 # durable notifications and delivery orchestration
tests/
├── architecture/                  # import/registration constraints
├── integration/                   # genuinely cross-app behavior
└── deployment/                    # migrations, app/worker startup, recovery smoke
```

This tree is a target, not a request to create empty packages. Add messaging,
observability, or other adapter packages when an implementation needs them.
`common` need not remain an installed Django app if it owns only abstract
models/helpers. Existing persistent API logging must be assigned explicitly to
an operational capability before removing its app registration.

Project-wide management commands need an installed owning app or an explicitly
installed operational app. Do not rely on an uninstalled command directory.
Keep one canonical schema-generation command with a clear owner.

### Business capability ownership

| App | Initial features | Boundary |
| --- | --- | --- |
| Users | auth, profiles, groups, directory_sync | Identity and memberships; resource-specific access policy stays in resource owners |
| Labs | resources, locations, benches, equipment, licenses, bookings, monitoring, activities, audits, analytics, procurement, finance | Laboratory truth and operational workflows |
| Jira integration | issues, requests, service_info | Jira translation, remote reconciliation, request lifecycle |
| Notifications | inbox, preferences, delivery | Notification state, audience, read/dismiss state, delivery attempts |

Rename `websocket` to `notifications` only for notification-owned behavior.
Monitoring streams and task progress remain transports owned by their source
features; not every WebSocket message is a notification.

Keep Labs as one Django app initially. Procurement/finance become independent
apps only if their business meaning, ownership, and lifecycle become independent.
Do not flatten equipment categories into global applications.

Future capabilities such as documents, workflows, or search receive their own
apps only when requirements establish that ownership. Generic technical storage
does not automatically imply a universal business attachment model.

## 5. Standard business app

```text
core/<app>/
├── __init__.py                     # no registration side effects
├── apps.py                        # deterministic required handler registration
├── admin.py                       # presentation/administration, not workflows
├── models/                        # app-owned persistent truth, grouped by feature
│   ├── __init__.py                 # explicit Django model discovery
│   └── <feature>/
├── migrations/                    # numbered immutable migrations after release
├── public.py                      # intentionally exported app-level commands/queries
├── contracts.py                   # app-level DTOs/events/protocols if needed
├── urls.py                        # includes enabled feature URL facades
├── tasks.py                       # explicit Celery discovery facade
├── resources/                     # example of a named app-owned shared concept
├── features/
│   └── <feature>/
└── tests/                         # model integrity and app wiring
```

`resources/` is a Labs example, not a mandatory folder in every app. An app
shared concept must have a meaningful business name; avoid `features/_shared`.
Django models are pragmatically grouped under the app for discovery and
migrations. Each model group has one feature owner even when other features
reference it. Do not duplicate the same entity under a second domain model tree.

## 6. Canonical vertical feature

Use the [canonical structure](feature-template.md#2-final-structure) and
[sizing rules](feature-template.md#5-layout-sizing-and-naming), rather than a
second tree here. Application commands own writes; queries own reads; API/tasks/
handlers adapt entry points. Small features use application/query modules;
larger ones split into named capability/use-case modules.

Tasks and handlers are optional feature-root modules. Feature-specific port
translation belongs in `application/adapters.py` with injected neutral clients.
Rooms/stations and equipment variants organize modules within canonical layers,
not parallel child feature trees or root `integrations`/`extensions` packages.

### Contracts versus public entry points

- `contracts.py` contains frozen DTOs, event schemas and public protocols only.
  Command inputs stay beside their use case; business errors live in
  `exceptions.py`. Explicit public error exports may appear in `public.py`.
- `public.py` explicitly exports supported application commands and read
  functions. It may depend on the owning feature's implementation.
- Existing command-exporting `contracts.py` modules move exports to `public.py`
  during their slice. The distinction prevents provider implementations from
  becoming a hidden dependency of their own interface.
- Cross-app results are DTOs or scalar identifiers, not Django QuerySets,
  serializers, or mutable foreign ORM instances.
- Within one app, selectors may return QuerySets. Cross-feature mutations still
  use public commands; reads of shared models require a documented owner.

## 7. Dependency direction and composition

```text
HTTP / WebSocket / Celery / management command / event adapter
                         |
                         v
                 application / queries
                    |           |
                    v           v
                 models       read models
                    |
           feature contracts / neutral kernel

external feature/app callers -> public command/query -> application / queries
infrastructure implements neutral ports
application adapters translate feature ports using injected neutral clients
config composition selects and binds implementations
```

1. Common imports no business app, concrete infrastructure, or project settings.
   Framework-specific helpers stay separate from framework-neutral contracts.
2. Models import no feature code, APIs, tasks, or concrete external clients.
   Abstract actor relations use Django's `AUTH_USER_MODEL`, not a hardcoded
   users import; business actor assignment remains explicit.
3. Application/query code imports no DRF views/serializers, request objects,
   task modules, or provider SDKs. ORM access is permitted in this pragmatic
   Django architecture; repositories are not mandatory wrappers around ORM.
4. Infrastructure imports neutral contracts, never business apps. Feature-specific
  adapters implement feature contracts using injected neutral ports/clients;
  config constructs technical providers. Domain code imports no infrastructure.
5. APIs serialize data and delegate workflows. Internal API/tasks/handlers import
  their own application/queries directly; only external callers use the leaf
  public facade. Queries do not mutate application state.
6. Only config composition knows the whole deployment graph. Use explicit
   factories or parameters where substitution is needed, not a global service
   locator or a compulsory DI framework.
7. Cross-app dependency graphs must be acyclic. If two apps need each other,
   identify the workflow owner or use events/read projections instead of
   mutual imports. An interface alone does not eliminate a runtime cycle.
8. Django string foreign keys express persistence coupling, not permission to
   update another app's state. Record permitted relations and extraction cost.
9. File fields may reference stable, neutral upload-path functions and Django
   configured storage. Those callables are migration-facing API, not workflow
   adapters; provider operations remain outside models.

Enforce these rules with import-boundary checks and targeted architecture tests.
Use import-linter for package/layer contracts where practical and explicit tests
for registration, dynamic imports, public exports, and model coupling that import
checks cannot prove. Add tooling in the implementation phase, not just prose.

## 8. Reusable platform and extension contract

### Kernel: deliberately small

- Typed actor/context values, stable error codes, page/projection types.
- Opt-in timestamp and identity primitives; actor stamps where required.
- DRF response envelope, exception mapping, pagination and schema utilities.
- Neutral testing helpers and technical port definitions.

Do not put soft deletion, SKU validation, resource status, ownership rules, audit
logging, locking, exports, and serializer generation into one universal base.
Soft deletion is a business lifecycle decision. A Labs resource base can own
Labs semantics; a generic view cannot silently impose them on every app.

### Technical infrastructure

Adapters expose typed results or classified failures: validation/permanent,
temporary/retryable, and timeout. Avoid swallowing failures into `False` or
catching broad exceptions without a deliberate policy. Each integration needs
timeouts, bounded retries, resource cleanup, and an observable failure path.

Business email content, audience, and delivery eligibility belong to features.
SMTP/provider execution belongs to infrastructure. Export field selection belongs
to its owner; spreadsheet encoding belongs to infrastructure. Jira semantics
stay behind Jira's anti-corruption layer, not a generic HTTP selector.

### Deployment-selected module registration

Use Django AppConfig and explicit config composition first. If multiple product
deployments require selectable modules, introduce a small typed module descriptor:

| Descriptor field | Meaning |
| --- | --- |
| key | Stable application/capability identity |
| requires | Explicit module dependencies validated at startup |
| routes | Named HTTP/WebSocket registration |
| tasks/handlers | Explicit discoverable background entry points |
| checks | Configuration and dependency checks |
| permissions | Published capability names; actual rules stay with owners |

Never discover arbitrary plugins by importing every file, load Django models
at runtime, or suppress missing required handlers. Deployment configuration
chooses installed apps; runtime feature flags choose behavior only. Disabling
a feature must account for workers, dependencies, existing data, and in-flight
work, not just hide its URLs.

Equipment's category/capability registry is a **feature-local strategy registry**.
Definitions describe validated capabilities and field allowlists. Specialized
rules use named strategies, not dynamic inheritance or arbitrary dotted imports.
Use a test that verifies a new category can be added without changing unrelated
features. A registry must not become a second module system for the entire app.

## 9. Production behavior contract

### Transactions, invariants, and concurrency

- One application command owns each state transition. Equipment assignment and
  status changes share one assignment mutation authority, not parallel logic.
- Commands accept an explicit actor and typed input; validate eligibility and
  permissions even when invoked from tasks or another feature.
- Use `transaction.atomic` for multi-row changes, database constraints for
  race-sensitive invariants, and a documented consistent lock order.
- Model methods express intrinsic invariants. Serializer validation improves
  input feedback but cannot be the only protection against invalid writes.
- Bulk updates, admin actions, and scripts must not bypass critical invariants.
  Business admin actions call commands; routine persistence tooling is reviewed.
- External network calls do not hold database locks. Use recorded workflow state,
  idempotent jobs, and compensating behavior for multi-step remote operations.
- Test contention with real PostgreSQL connections, not SQLite/mock-only suites.

### Reliable asynchronous work

- `on_commit` prevents pre-commit dispatch but does not guarantee publication.
  Use it for explicitly best-effort work only.
- When event loss is unacceptable, store an outbox record in the same database
  transaction. A dispatcher claims batches, publishes with retries, and records
  progress. A crash can cause duplicate publication: consumers are idempotent.
- Persistent outbox/dispatch state belongs to a named messaging Django app when
  introduced; broker clients alone belong in infrastructure.
- Events carry event ID, schema version, aggregate ID, occurrence time, and
  correlation ID. Ordering guarantees are documented per aggregate, not assumed
  globally. Support deduplication, retry limits, dead-letter/replay handling.
- Task payloads use identifiers/DTOs, not requests or ORM instances. Explicit
  task names, execution limits, retry policy, and queues are part of the contract.
- Distinguish a durable notification inbox from transient Redis/WebSocket
  delivery. Reconnect clients recover from persisted state/cursors; Pub/Sub
  is not the source of truth.

### Security and access boundaries

- Authentication is centralized; object/action authorization belongs to the
  app owning that object. Filter read queries as well as protecting writes.
- A background system actor has explicit scope; it is not an implicit bypass.
- If multi-tenancy is required, decide isolation before implementing models.
  Propagate tenant scope through reads, commands, constraints, caches, jobs,
  storage, and tests. A multi-app product is not automatically multi-tenant.
- Validate upload size/type, authorized download access, and processing policy.
  Use configured secret providers; never put credentials in events or logs.
- Log allowlisted metadata by default. Redact sensitive fields in bodies as well
  as headers, apply retention, and separate operational logs from business audit.

### API and operations

- Publish versioning, slash policy, pagination, filtering, error-code and
  authentication conventions. Input and read serializers have explicit fields.
- Runtime responses and generated OpenAPI must agree. Review intentional
  contract diffs; feature URL facades keep schema ownership deterministic.
- Keep the ORM/transaction boundary synchronous unless a use case demonstrates
  async benefit. An async view wrapping sync ORM is not an async domain engine.
- Provide structured logs, correlation across jobs, latency/error metrics,
  external dependency timeouts, and useful traces without sensitive payloads.
- Separate liveness from readiness. Define dependency health behavior and avoid
  restarting every worker solely because a remote provider is temporarily down.
- Set workload-specific latency/availability objectives, query budgets and
  capacity targets before calling the system production-ready.
- Test backups/restores, graceful worker shutdown, schema rollout, queue draining,
  and recovery. External calls and long exports need bounded resource usage.

## 10. Patterns: use deliberately

| Pattern | Appropriate use | Avoid |
| --- | --- | --- |
| Modular monolith | Local transactions and explicit business ownership | Splitting services before boundaries are stable |
| Vertical slice | Complete capability from use case to transport/tests | A new slice for every HTTP method |
| Application service | One transaction/workflow owner | Rules duplicated in views/signals/tasks |
| CQRS-lite | Separate write commands and read selectors | Mandatory event sourcing or separate databases |
| Ports/adapters | External provider or cross-app substitution | An interface for every internal helper |
| Strategy/registry | Equipment variants with stable capabilities | Universal reflection-based CRUD |
| Outbox/idempotent consumer | Durable cross-boundary side effects | Claims of exactly-once broker delivery |
| Repository | Complex persistence boundary needing substitution | Wrapping every QuerySet without value |
| Domain events | Facts consumed by independent capabilities | Hidden signal chains for core invariants |

## 11. Test ownership and acceptance

Feature tests live with their feature; model constraints and app registration
tests live with the app. Top-level suites contain cross-app, architecture, and
deployment tests only. Neutral fixtures belong in common.testing; domain
factories stay with their app. Configure pytest to collect both feature-local
and top-level tests deliberately.

Each implemented slice must demonstrate:

1. Policy tests for permitted/denied reads and writes, including non-HTTP callers.
2. Command/model invariants, rollback, database constraints, and relevant races.
3. Selector correctness and bounded query behavior.
4. Runtime API/schema agreement and intentional contract changes.
5. Idempotent task/event handling and provider failure behavior when applicable.
6. No forbidden imports or duplicate workflow owner.

Full-release gates additionally require test collection, full Django checks,
fresh PostgreSQL migrations, migration drift checks, HTTP/ASGI startup, Celery
worker/Beat startup, schema generation, linting, and deployment/recovery smoke.
An isolated feature database bypassing migrations is useful for focused tests,
but cannot replace these release gates. Deferred broken apps are excluded via
explicit slice settings, not silently tolerated in the full production config.

## 12. Rebuild sequence

### Phase 0 — Baseline and design agreement

- Inventory currently active routes, models, imports, tasks, clients, and tests.
- Separate intended future capabilities from working endpoints.
- Choose the isolated rebuild database and production data/cutover strategy.
- Record allowed model relations, feature owners, and compatibility decisions.
- Resolve obsolete docs/imports based on the actual filesystem, not old findings.

Exit: approved boundary map and repeatable baseline; no database deletion required.

### Phase 1 — Kernel and bootable foundations

- Classify existing common API primitives versus Labs resource behavior.
- Establish neutral contracts, explicit infrastructure ports, and config wiring.
- Repair required app/signal/task discovery; stop suppressing required imports.
- Establish fresh migration reproducibility and import/test-collection guardrails.
- Keep the implementation slice focused on common, infrastructure, and active
  Labs features with explicit test settings. Track other apps as deferred, not
  production-certified.

Exit: the selected slice boots/tests deterministically; target full-app blockers
are documented. Do not perform broad domain rewrites in this foundation phase.

### Phase 2 — Reference vertical slices

- First migrate **benches**: retain the existing app/feature folders, keep
  `contracts.py` to types, move business errors to `exceptions.py`, publish
  external commands/queries through `public.py`, and make HTTP import its own
  application/queries. Update tests enforcing the former internal-public rule.
  Keep the combined
  bench/location behavior suite at top level while the feature gains focused
  tests under `features/benches/tests/`.
- Next migrate **locations** as the first multi-capability feature: split stable
  types from its command facade, then organize room/station modules within
  application/queries/API and use direct internal imports. Remove duplicate
  implementations after accounting for all references. Preserve the
  explicit locations URL facade.
- Then align equipment and licenses. Equipment owns stable workflow errors in
  exceptions and exports supported commands/queries from public.py; status records are
  written only by its status command. Licenses use the same boundary and expose
  agreement reads through named selectors.
- Split interface types from public command exports.
- Centralize assignment mutation and lock order; enforce actor policies.
- Move feature tests with their owner; rebuild schema contracts alongside APIs.
- Prove extension behavior with one additional equipment category or adapter test.

Exit: benches, locations, equipment, and licenses follow the template; feature
boundary tests enforce each public surface. Database behavior suites can run
when the configured test database and app registry are ready. During the rebuild,
use focused static/unit tests where broader startup is incomplete.

### Phase 3 — Complete Labs capabilities

Implement bookings, monitoring, activities, audits/analytics, then procurement
and finance in business-priority order. Register routes/tasks only when their
implementation exists. Add durability infrastructure when a real workflow
requires it. Remove retired source only after all consumers are accounted for.

Exit: every enabled Labs capability has one owner and passes slice acceptance.

### Phase 4 — Remaining apps and platform capabilities

Align users and Jira, rebuild notification-owned WebSocket behavior under
notifications, and implement durable delivery where required. Reassess common's
persistent logging/command ownership. Introduce deployment module descriptors
only if product composition needs more than normal Django app registration.

Exit: full configured application, workers, migrations, and test collection work.

### Phase 5 — Production certification and cutover

Run release gates, concurrency/load/security tests, backup/restore rehearsals,
and client/queue migration exercises. Drain incompatible jobs or version their
payloads. Approve any destructive reset separately. Use additive schema changes
and contract transition periods when old/new deployments coexist.

Exit: measured objectives, operational ownership, documented rollout/recovery,
and explicit acceptance of any remaining limitations.

## 13. Definition of done

- Every capability and persisted model has an owning business or platform app.
- Common remains domain-neutral; infrastructure contains no business policy.
- Every feature uses the same optional-layer vocabulary and public boundary.
- One authoritative command owns each state transition and permission check.
- No required registration failure is silently ignored.
- Enabled features, generated schemas, migrations, and collected tests agree.
- Required side effects have documented durability and idempotency semantics.
- New modules/providers can be added through explicit composition, not edits
  across unrelated features or a universal base class.
- Full startup, migrations, worker behavior, authorization, concurrency, and
  recovery are verified before claiming production readiness.

## 14. Core architecture review and improvement backlog (2026-10-26)

**Status: review findings and proposals, not implementation certification.**
This section records a sampled, read-only review of the current repository. The
feature template remains authoritative for feature boundaries. Findings describe
the inspected code at review time; proposed corrections require the owners and
gates listed below. Do not interpret a proposal or a green architecture test as
evidence that all of `core/` is production-ready.

### Review scope and verified baseline

Inspected repository instructions and architecture documents; searched active
`core/` imports and routes; sampled Labs booking persistence, analytics tasks,
resource-audit queries, Labs signals, WebSocket authentication/handlers, shared
outbox, production settings and task registration. The review was not a
line-by-line review of every feature, model, endpoint, migration, or deployment
file.

Verified positive foundations:

- PostgreSQL booking overlap constraints are implemented for reservable resources
  ([booking constraint](../../core/labs/models/booking/base.py#L38-L54),
  [equipment booking](../../core/labs/models/booking/equipment_booking.py#L6-L29)).
  Booking lifecycle and approval state are distinct.
- DRF defaults to authenticated access; production replaces authentication with
  Entra JWT. Explicit unauthenticated API views are limited in the inspected
  search to login endpoints ([REST settings](../../config/settings/base.py#L312-L323),
  [production authentication](../../config/settings/production.py#L10-L19)).
- The shared abstract outbox has delivery-state and lease constraints
  ([outbox](../../core/common/models/outbox.py#L12-L71)).
- `core.common` and `core.infrastructure` had no production imports from business
  apps in the inspected boundary search; the only matches were tests.
- Six existing architecture tests passed. These tests cover selected rules only;
  this is not a full test-suite or production-readiness result.

### Confirmed findings

#### ARCH-001 — High — WebSocket object-level authorization is absent

**Status:** Confirmed in inspected handlers. **Evidence:** JWT middleware puts a
user ID in the scope, but bench, monitoring, computing-activity, and task-progress
handlers subscribe using client-supplied IDs without an object/ownership policy.
The notification handler derives its user channel from the authenticated scope;
it is not included in this object-ID finding. See [middleware](../../core/websocket/middleware.py#L27-L33),
[task progress](../../core/websocket/features/task_progress/handler.py#L18-L24),
[computing activity](../../core/websocket/features/computing_activity/handler.py#L17-L23),
[equipment status](../../core/websocket/features/equipment_status/handler.py#L17-L24),
[monitoring dashboard](../../core/websocket/features/monitoring_dashboard/handler.py#L17-L29),
and [user notifications](../../core/websocket/features/user_notifications/handler.py#L52-L68).

**Impact:** An authenticated user can attempt to subscribe to another user's
task stream or resource stream. Authentication alone does not establish
resource-level permission. **Recommendation:** Add route-owned authorization
before accepting/subscribing; derive resource visibility from the owning
feature's policy and bind task IDs to their initiating actor. Add denied-access
tests for each route family and verify no data is sent before authorization.
Align the exact permission policy with the equivalent REST operation rather
than inventing a broader WebSocket rule. **Owner:** backend engineer and security
engineer. **Tier:** T2; access-control change needs human approval.

#### ARCH-002 — High — URS TLS certificate verification defaults off

**Status:** Confirmed. `URS_API_VERIFY_SSL` defaults to `False`
([base settings](../../config/settings/base.py#L228-L233)); the URS client passes
that value to `requests.post(..., verify=...)`
([URS sync](../../core/users/features/urs_sync/sync_group/service.py#L19-L43)).
Production globally suppresses `InsecureRequestWarning`
([production settings](../../config/settings/production.py#L20-L24)).

**Impact:** If the default is used, the client does not validate the URS server
certificate while transmitting its access token. **Recommendation:** Default
verification on, configure a trusted internal CA bundle where necessary, and
remove global warning suppression or scope it to the specific client that needs
it. Add a settings/client test for the production default. **Owner:** security
engineer and integration engineer. **Tier:** T2.

#### ARCH-003 — Medium — Analytics task layer reaches across owners and imports config

**Status:** Confirmed. [Analytics tasks](../../core/labs/features/analytics/application/tasks.py#L12-L26)
import `config.celery_app`, Labs models owned by other capabilities, and
`core.users.models.LabManagementEmail`. **Impact:** The task/application layer
couples features through their persistence and deployment composition, contrary
to the feature template. **Recommendation:** Make task entry points thin,
explicitly named feature-root tasks; keep use-case work in commands/queries;
replace cross-feature model access with owner-published queries/DTOs and put
provider bindings in config. **Owner:** integration engineer and backend
engineer. **Tier:** T2 (background jobs and cross-feature edges).

#### ARCH-004 — Medium — A Labs model signal performs a cross-app WebSocket side effect

**Status:** Confirmed. Labs signals (`core/labs/signals.py`, since removed) import
WebSocket publishers; the `pre_save` receiver performs a query and suppresses
all exceptions (receiver (`core/labs/signals.py`, since removed)); `post_save` schedules
publishing after commit (receiver (`core/labs/signals.py`, since removed)). Bulk updates
do not emit these model signals. **Impact:** A business side effect is hidden
from the command that owns the state transition, can be lost on bulk writes, and
crosses into a transport app. **Recommendation:** Emit the status-change intent
from the owning application command after a successful transition. Use an
outbox when losing the update is unacceptable; keep best-effort `on_commit`
only if that loss policy is explicit. **Owner:** architecture and integration
engineers. **Tier:** T2.

#### ARCH-005 — Medium — Resource-audit query imports application code

**Status:** Confirmed. [Audit selectors](../../core/labs/features/resource_audit/queries/selectors.py#L9-L10)
import `resolve_resource` from application commands and call it from a query
([usage](../../core/labs/features/resource_audit/queries/selectors.py#L52-L58)).
**Impact:** Reverses the required query/application dependency direction and
can create cycles. **Recommendation:** Move the read-only resolution behavior
to a selector; keep writes and workflow decisions in commands. **Owner:**
backend engineer. **Tier:** T1 unless its cross-feature contract changes.

#### ARCH-006 — Medium — Task discovery and names are not consistently explicit

**Status:** Confirmed configuration drift; runtime task availability is
**Potential**, not established by this review. [Labs task facade](../../core/labs/tasks.py#L1-L31)
is commented out; [Celery config](../../config/celery_app.py#L17-L21) manually imports
two nested modules; analytics tasks are decorated in an application module and
are re-exported through its package; [URS task](../../core/users/tasks.py#L1-L10)
uses the app-derived task name. **Impact:** A task may be omitted from worker
registration, or a module move may change a task name referenced by schedules
or callers. **Recommendation:** Use each app's explicit `tasks.py` facade,
assign stable task names and explicit retry/time limits, and test registered
names in a worker-like app startup. Before moving any task, inventory persisted
Beat schedules and deployed producers. Preserve existing names unless an
approved compatibility plan says otherwise. **Owner:** integration engineer
and independent reviewer. **Tier:** T2.

#### ARCH-007 — Medium — Existing architecture tests do not enforce the full target boundary

**Status:** Confirmed. `tests/architecture/test_import_boundaries.py` checks
common/infrastructure isolation; other tests cover the root URLconf and selected
users boundaries. They do not catch the confirmed Labs violations above.
**Recommendation:** Add AST-based checks for feature-to-feature imports
(`public.py`/`contracts.py` only), queries importing application, feature imports
of config, cross-app model reach-through, and registered task/route ownership.
Add a reviewed baseline/allowlist for existing violations that can only shrink.
Run checks in CI. **Owner:** backend engineer and QA engineer. **Tier:** T0/T1.

#### ARCH-008 — Medium — Production observability and workload controls are incomplete

**Status:** Confirmed gaps in inspected config, not a claim that no external
platform monitoring exists. Production settings retain a Sentry TODO
([production logging](../../config/settings/production.py#L95-L99)); base settings
show auth-specific throttle rates but no global throttle classes
([DRF settings](../../config/settings/base.py#L312-L324)); Celery uses the broker URL
as result backend and does not set workload reliability controls in the inspected
base settings ([Celery settings](../../config/settings/base.py#L263-L293)). Searches
of `config/` and `core/` did not find health/readiness endpoints. **Recommendation:**
Confirm platform-level metrics and alerting ownership; add structured error
tracking and service health endpoints if not supplied by deployment; define API
rate limits for sensitive/high-cost endpoints; set and test Celery acknowledgement,
prefetch, routing and result-retention policy based on workload semantics rather
than applying generic values. **Owner:** DevOps & reliability, API designer,
integration engineer. **Tier:** T2 for CI/infra or contract changes.

#### ARCH-009 — Medium — Initial notification query is unbounded

**Status:** Confirmed. [User notification handler](../../core/websocket/features/user_notifications/handler.py#L22-L41)
fetches all unexpired notifications for a user on connect. **Impact:** Large
backlogs can increase database work, memory, and connection setup time.
**Recommendation:** Define a delivery/cursor contract, bound initial replay, and
verify a supporting index from the model and migration before adding one. Add a
query-budget and replay test. **Owner:** backend engineer and API designer.
**Tier:** T1; T2 if persistence or public message contract changes.

#### ARCH-010 — Low — WebSocket authentication and settings consistency follow-ups

**Status:** Confirmed in inspected implementation. The JWT is read from the
query string ([middleware](../../core/websocket/middleware.py#L36-L38)), which may be
captured by proxy/access logs; the non-Entra validation path reads the token's
user ID without fetching/checking active-user state ([validation](../../core/websocket/middleware.py#L49-L50));
production config sets HSTS preload while `SECURE_HSTS_SECONDS` is only 60
([HSTS settings](../../config/settings/production.py#L48-L58)). **Recommendation:**
Prefer a short-lived, single-use WebSocket ticket or another design that avoids
long-lived bearer tokens in URLs; check `Origin` and active-user status; align
HSTS preload with its deployment requirements or disable preload until those
requirements are met. Add proxy-safe authentication tests. **Owner:** security
engineer and DevOps & reliability engineer. **Tier:** T2 for auth changes.

#### ARCH-011 — Low — API layer has remaining cross-app model imports and pagination defaults differ

**Status:** Confirmed. Two Labs serializers import `core.users.models.user.User`
directly ([shared resource serializers](../../core/labs/features/base/serializers.py#L11-L18),
[audit serializers](../../core/labs/features/resource_audit/api/serializers.py#L3-L16)).
Base DRF pagination is configured with a page size of 10
([base settings](../../config/settings/base.py#L315-L316)), while
`ResultsSetPagination` uses 25 and permits up to 100
([shared pagination](../../core/common/api/pagination.py#L12-L20)).
**Impact:** Cross-app identity imports increase coupling, and endpoints using
different pagination classes may expose inconsistent collection behavior.
**Recommendation:** Use the configured user model or a users-owned DTO boundary
as appropriate for serializers; inventory which endpoints use each pagination
class, then align intentionally without changing deployed contracts accidentally.
**Owner:** API designer and backend engineer. **Tier:** T1; public pagination
contract changes raise this to T2.

#### ARCH-012 — Low — Nested location features import parent private application modules

**Status:** Confirmed. The room application imports helpers directly from
`core.labs.features.locations.application.services`
([room services](../../core/labs/features/locations/rooms/application/services.py#L3-L9));
the station application does likewise. **Impact:** Child capabilities depend
on a private parent implementation, making later extraction or refactoring
harder. **Recommendation:** Because rooms and stations belong to the locations
feature, first confirm these are intentional same-feature internal modules;
prefer a canonical shared application module with explicit internal ownership,
or move the shared behavior to a named location capability. Do not create a
cross-feature `public.py` dependency solely to satisfy an import pattern.
**Owner:** architecture/backend engineer. **Tier:** T1.

### Potential risks requiring follow-up evidence

These were identified during sampling but not verified sufficiently to call
confirmed defects:

- **Support desk resource DTO boundary:** [resource adapters](../../core/support_desk/features/tickets/application/adapters.py#L13-L43)
  call Labs `public.py` getters and appear to read model attributes. The return
  types of those getters and whether ORM instances cross the app boundary were
  not established. Inspect signatures and change to explicit DTO projections if
  models cross the boundary. **Owner:** architecture/backend engineer.
- **WebSocket connection scaling and recovery:** handlers create one or more
  Redis Pub/Sub listeners per connected client; for example,
  [user notifications](../../core/websocket/features/user_notifications/handler.py#L64-L70).
  This may limit connection capacity, and Pub/Sub does not replay messages after
  disconnect. Load-test connection counts and confirm each stream has an
  appropriate persisted recovery/cursor path before selecting a replacement.
  **Owner:** DevOps & reliability and integration engineers.
- **External readiness/monitoring ownership:** no health/readiness implementation
  was found in searched `config/` and `core/` files, but deployment-level probes,
  metrics and alerts were not inspected. Confirm ownership before treating this
  as an operational gap.

### Proposed capability roadmap (not a statement that the platform lacks all related workflows)

The rows below distinguish inspected evidence from suggested discovery/design.
They are candidates for product-owner prioritization, not commitments or a
complete laboratory-domain requirements analysis.

| Capability | Verified evidence in this review | Proposal / next discovery |
| --- | --- | --- |
| Equipment booking | `EquipmentBooking` model and overlap constraint exist; no `core/labs/features/` consumer was found in the targeted search. | Define and implement an `equipment_bookings` vertical feature: actor policy, lifecycle, conflict handling, API, notifications and tests. Confirm whether an existing UI or legacy flow already owns the behavior. |
| Maintenance and calibration | `ResourceServiceRecord` model exists; a legacy maintenance reminder import is commented out in the Labs task file. | Define service/calibration schedules, due/overdue rules, evidence, reminders and audit history; reuse durable delivery where required. |
| Borrow and return | The legacy borrow/return reminder import is commented out. | Confirm business need and inventory semantics; if needed, define a loan lifecycle separate from equipment assignment and booking. |
| License expiry | Legacy expiry reminder/scan imports are commented out. | Confirm whether license status is updated automatically; add named idempotent jobs and owner-approved notification rules if missing. |
| Site/building/department access scope | URS group role mapping is documented in settings; per-resource scope was not established by this sample. | Map authorization needs with product/security; if required, propagate a typed scope into commands and filter all relevant reads. |
| Audit coverage | `ResourceAudit` and `ResourceChangeLog` models exist. | Inventory which commands write them and what retention/immutability is required before proposing a unified audit mechanism. |
| Monitoring agent identity | The computing API declares `HasAPIKey` or coordinator access ([computing API](../../core/labs/features/equipment/categories/computing/api.py#L56-L60)). | Review the existing key implementation, storage, rotation, scope, revocation, and rate limits before deciding whether per-agent identity work remains. |
| Calendar integration, recurring bookings, waitlists | Not assessed in this review. | Discover user demand and booking invariants before designing integration or schema. |
| Cost allocation / chargeback | Expense, procurement and license models are present in Labs model exports; end-to-end allocation behavior was not reviewed. | Define cost owner, source-of-truth and reporting semantics with Finance/product before adding workflows. |
| Retention and purge | Soft-delete primitives exist in common; a complete domain retention policy was not reviewed. | Inventory personal/business records, legal retention and restore needs, then specify per-model purge/archive behavior and tests. |

### Recommended sequence and decisions

1. **Security:** resolve ARCH-001 and ARCH-002 first, with security review and
   human approval where access control changes.
2. **Guardrails:** implement ARCH-007 and capture the current allowed-import
   baseline before boundary refactors.
3. **Feature/task ownership:** address ARCH-006, ARCH-003, ARCH-005 and ARCH-004;
   preserve external task names and state any newly approved dependency edge.
4. **Reliability and operations:** prioritize ARCH-008 and ARCH-009 from measured
   needs; test health semantics, delivery guarantees, query budgets and recovery.
5. **Product capability discovery:** prioritize roadmap candidates with the
   product owner and domain specialists. Schema, booking concurrency, job,
   integration and access-control work is T2 and requires the applicable review.

Open decisions: Which REST role/object rules should govern each WebSocket route?
Are error tracking, infrastructure health probes, metrics and alerts owned by
the deployment platform today? Which roadmap capabilities have confirmed
business requirements and owners?

### Validation record

| Check | Result |
| --- | --- |
| `uv run pytest tests/architecture -q` | **Passed** — 6 passed (review-time result). |
| `lint-imports` | **Not run** — not configured in the repository. |
| Full test suite, migration drift, query budgets, worker registration, security tests and deployment checks | **Not run** — outside this read-only review. |
