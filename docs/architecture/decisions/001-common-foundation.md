# ADR 001 — Common foundation redesign

- Status: Accepted (owner decisions recorded 2026-10-21)
- Scope: `core/common`, `core/infrastructure`, cross-feature conventions, CI guardrails
- Tier: T2 overall; each phase below declares its own tier
- Related owner documents: `docs/feature-template.md`, `docs/django-model-conventions.md`,
  `docs/ai-team/api/response-standard.md`, `docs/ai-team/quality-gates.md`

Every finding cites `path:line`. Items marked **(not verified)** were not confirmed at runtime.

---

## 1. Owner decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Equipment endpoints accept API keys? | Yes. |
| Q2 | Which callers use API keys, and where? | Agent and API test client (Apidog). API keys are accepted on **all** endpoints. |
| Q2b | Map each API key to a technical user and role? | **No.** API-key callers stay anonymous (see accepted risk R-1). |
| Q3 | Error-code casing | Move to `snake_case` in one **breaking** release. The frontend adapts; there is no compatibility alias. |
| Q4 | Jira integration | No longer supported. Remove the app and **delete** its data. |
| Q5 | Optimistic-concurrency failure status | Return 409 with code `version_conflict`. No ETag or `If-Match`. |
| Q6 | API versioning | No `/api/v2/`. A single `/api/` contract; breaking changes ship as a coordinated release with a changelog. |
| Q7 | Forced async dispatch in `AppAPIView` | Keep as-is. There is no measurement justifying a change. |
| Q8 | Unused stamped bulk helpers | Remove `bulk_create_stamped`, `bulk_update_stamped`, `update_stamped`. **Keep** `all_objects` (used by bench_bookings, benches, stations). |
| Q9 | CI scope | Widen it (Phase P0). |
| Q10 | Owner of `drf-api-contracts` and `openapi/` | Backend maintains both and publishes the regenerated spec plus a changelog to the frontend. |

### Accepted risks
- **R-1 (API keys anonymous on all endpoints).** A request authenticated only by API key has no user. As a
  result, writes made with a key are not stamped (`creator`, `last_modified_by` stay empty), role checks
  that need a user cannot run, and one leaked key grants every endpoint, including finance and procurement.
  The owner accepted this. Mitigations: issue keys per caller and per environment, rotate them, never issue
  the Apidog key in production, and log key usage by key prefix (Phase P4).

---

## 2. Audit (Phase 1)

Severity: H = correctness, security or contract risk; M = duplication or drift that will spread; L = hygiene.

| # | Area | Issue (evidence) | Sev | Fix |
|---|---|---|---|---|
| A1 | Permissions | Two classes named `EquipmentAPIView` with different authentication: `core/labs/features/equipment/api/common.py:24` (`IsAuthenticated`) and `core/labs/features/equipment/api/views.py:67` (inherits `HasAPIKey \| IsAuthenticated` from `core/labs/features/base/common.py:13`). | H | One equipment base; API key allowed (Q1). P4. |
| A2 | Actor | `HasAPIKey` is combined ad hoc into about 12 views; API-key callers have no actor. | H | Accepted risk R-1; single declared API-key policy in the app base. P4. |
| A3 | Errors | Three exception-to-HTTP mappers: `core/labs/features/base/command.py:84`, `core/support_desk/features/tickets/api/base.py:128`, and ad hoc try/except. Leaderboard catches bare `Exception` and returns 400 (`core/labs/features/leaderboard/api/views.py:54`). | H | `DomainError` hierarchy and one mapper. P2. |
| A4 | Error codes | Mixed casing: `MessageCode` and equipment/licenses codes are SCREAMING_CASE (`core/labs/features/equipment/exceptions.py:7`); benches/locations are snake_case. `validate_request` emits `VALIDATION_ERROR` (`core/common/api/api_views.py:301`) while other paths emit `validation_failed`. ERR-2 requires snake_case. | H | Breaking rename to snake_case (Q3). P2. |
| A5 | Coupling | `MessageCode` in common holds business vocabulary (`BOOKING_*`, `COMPUTER_*`, `LAB_*`, `SKU_*`) — `core/common/api/message_code.py`. | M | Codes move to each feature's `exceptions.py`. P2. |
| A6 | Response format | Two error formats: `{"error": …}` envelope and RFC 9457 helpers in `core/common/api/responses.py`, which only `tests/unit/test_api_response_schema.py:19` imports. ERR-11 allows one. | M | Delete `responses.py`. P7. |
| A7 | Pagination | DRF default is `PageNumberPagination` with `PAGE_SIZE 10` (`config/settings/base.py:323`); `ResultsSetPagination` is 25/100 with `meta.pagination`; `responses.paging` uses `meta.total_count`. | M | `ResultsSetPagination` as the default. P3. |
| A8 | Query validation | page/page_size, unknown-key and repeated-key checks exist in four places: `AppAPIView.validate_query`, `AppListAPIView.list_response_sync` (`core/common/api/api_views.py:436`), `ResultsSetPagination.get_page_size`, `FilterQuerySerializer.to_internal_value`. | M | One validation path. P3. |
| A9 | API foundation | Three `operation()` factories (`core/labs/features/base/command.py:17`, `core/labs/features/locations/api/schema.py:7`, `core/support_desk/features/tickets/api/base.py:41`) and three copies of the `__init_subclass__` schema hook. | M | One factory and hook in common. P3. |
| A10 | Placement | Domain-neutral `FeatureAPIView`, `CommandAPIView`, `ListCreateAPIView` live in `core/labs/features/base`; Support Desk rebuilt them. | M | Promote neutral parts to `core.common.api`. P3. |
| A11 | Coupling | Labs imports `core.users.access` and `core.users.models` directly (`core/labs/features/bench_bookings/application/update_booking.py:15`, `core/labs/features/expense/api/views.py:22`, `core/labs/features/base/serializers.py:12`). No `core/users/public.py`. | M | `core.users.public`. P6. |
| A12 | Events | `core/labs/signals.py:16-73` runs workflow in `pre_save`/`post_save`, imports `core.websocket` internals, swallows `Exception`. | M | Explicit handler via `on_commit`. P6. |
| A13 | Drift bug (not verified) | Support Desk adapters read `getattr(bench, "is_delete", False)` (`core/support_desk/features/tickets/application/adapters.py:153`); resources use `deleted_at`, so `is_active` is likely always `True`. | M | Failing test, then fix. P6. |
| A14 | Soft delete | Legacy `BaseModelManager` (`is_delete`) has no production model user. | L | Delete. P5. |
| A15 | Timestamps | `created`/`modified` (model_utils) vs `created_at`/`updated_at` (Support Desk, users); `AppModelSerializer` remaps at runtime (`core/common/api/__init__.py:11`). | L | Keep both; new models use one rule. P5. |
| A16 | Transactions | "catch `IntegrityError` → conflict" copied in 8 application modules; `atomic_command` exists in `core/labs/features/locations/application/services.py:10` but catches every `IntegrityError`. | M | Common `atomic_command` with classified constraint names. P3. |
| A17 | Idempotency | `create_ticket` checks then creates (`core/support_desk/features/tickets/application/create_ticket.py:46`); the unique constraint exists, concurrent behavior not verified. | M | Concurrency test, then D2 pattern. P6. |
| A18 | Observability | `RequestCorrelationMiddleware` is defined but not installed (`config/settings/base.py:128`); log format has no request id. | M | Install and add logging filter. P1. |
| A19 | Docs drift | `UserStampedModel` docstring references nonexistent `core.api.mixins.UserStampedViewMixin` (`core/common/models/base_models.py:200`). | L | Fix. P5. |
| A20 | Enforcement | CI lints/tests only `core/users` and `tests/architecture` (`.github/workflows/ci.yml`); Spectral workflow sits in `.github/workflow/` (not run); no import-linter. | H | P0. |
| A21 | Tests | Two `UserFactory` (`tests/factories.py:42`, `core/users/tests/factories.py:15`); common tests import `core.users` and `core.websocket` (`core/common/tests/test_base_models.py:15`). | L | One owner per factory. P5. |
| A22 | Shims | `core/utils/email.py` re-exports infrastructure email; `core/contrib/sites` is cookiecutter leftover. | L | Remove. P7. |
| A23 | Outbox | Two outboxes: `core/support_desk/models/outbox.py` and `BookingNotification` in bench_bookings. | L | Document the pattern; no shared model (2 cases). |
| A24 | Jira | `core.jira_integration` is unsupported (Q4) but still installed (`config/settings/base.py:66`) and routed (`config/api_router.py:14`). | M | Phase P-J. |

### Over-engineered or premature
- `UserStampedQuerySet.*_stamped` — no callers (Q8). Remove.
- `core/common/api/responses.py` — dead RFC 9457 path. Remove.
- `MessageCode` legacy aliases — obsolete after the snake_case release. Remove.
- `FeatureAPIView.validate_configuration()` runs on every request (`core/labs/features/base/list_create.py:77`) — move to class creation.
- `_strict_input_errors` (about 100 lines) — keep and test; do not extend.

---

## 3. Target design (Phase 2)

Scores: 1 (worst) to 5 (best). "MigCost" 5 = cheap. "OE" 5 = low over-engineering risk.

### D1. Base models and mixins
Composable mixins, no universal base class. `model_utils.TimeStampedModel` stays for existing models; new models
use `TimestampsMixin` (`created_at`, `updated_at`). `UserStampedModel` with `actor=` only. `TimestampedSoftDeleteMixin`
only for delete-with-restore; retirement of reference data is `is_active`. Seeded rows use `ProtectedReferenceMixin`
in `core.reference_data`. IDs stay `BigAutoField` plus a natural key where the domain has one.
Rejected: universal `BaseModel`; UUID primary keys; generic `OwnedModel`.
Score: Maint 4, Ext 4, Reuse 4, Simple 5, Test 4, Perf 5, MigCost 5, Django 5, OE 5 — removes dead code, no migration.

### D2. Application layer
One command per file, frozen input, keyword-only `actor`, `@atomic_command(conflicts={"<constraint>": FeatureConflict})`
in `core.common.db`. Only listed constraint names map to `Conflict`; everything else is re-raised. Idempotency
via unique key plus re-read on `IntegrityError`. Side effects via `transaction.on_commit` (best effort) or a
feature-owned outbox row (required delivery).
Rejected: command bus; generic repositories; shared outbox model.
Score: 5, 4, 5, 4, 5, 5, 4, 4, 4 — eight real copies; tightens failure classification.

### D3. Query layer
Selectors return querysets or DTOs, take `actor` for visibility, use `FilterSpec` (ordering always ends in `pk`);
pagination only at the API layer; `<Entity>NotFound` for required singles; list tests assert a query budget.
Rejected: django-filter as a second filter system; cursor pagination everywhere.
Score: 4, 4, 5, 4, 5, 5, 5, 4, 5 — already proven by four features.

### D4. Cross-feature communication
`public.py` / `contracts.py` only. Add `core/users/public.py`. Acyclic calls go through `public`; cyclic or
non-blocking work uses `on_commit` or an outbox. Django signals only for framework integration, not business workflow.
Rejected: domain-event bus; signals as the event mechanism.
Score: 4, 4, 3, 4, 5, 4, 3, 4, 4 — explicit flow; moving the signal is T2.

### D5. Authorization
Three layers: coarse DRF `RolePermission` subclasses per app; object-level pure `can_*`/`ensure_*` policies;
queryset visibility in selectors. API keys accepted on every endpoint through **one** declared policy in each
app's base view (`HasAPIKey | <role permission>`), never ad hoc (Q1, Q2, R-1). Support Desk permissions move
onto `RolePermission`.
Rejected: django-guardian; django-rules; Django model permissions.
Score: 4, 4, 5, 4, 5, 4, 4, 4, 4 — one declared policy replaces scattered combinations.

### D6. Errors
`core/common/domain/errors.py`: `DomainError(code, message, details)` with `NotFound` (404), `Conflict` (409),
`PermissionDenied` (403), `ValidationFailed` (422). Optimistic-lock failures raise `Conflict` with code
`version_conflict` (Q5). Feature `exceptions.py` subclass these with snake_case codes (Q3). One mapper in
`api_exception_handler`; views do not catch feature errors.
Rejected: HTTP status on feature exceptions; code registry in common; RFC 9457.
Score: 5, 5, 5, 4, 5, 5, 3, 4, 4 — three mappers become one; codes become consistent.

### D7. API foundation
Keep `AppAPIView`, `drf-api-contracts`, the envelope, and the forced async dispatch (Q7). Promote one
`operation()` factory, one schema hook, and `CommandAPIView` to `core.common.api`. Query validation only in
query serializers. `ResultsSetPagination` as `DEFAULT_PAGINATION_CLASS`. No path versioning (Q6). OpenAPI is
generated by `spectacular_modules`, drift-checked and Spectral-linted in CI; backend publishes it to the frontend (Q10).
Rejected: DRF generic viewsets everywhere; django-ninja; `/api/v2/`.
Score: 4, 4, 5, 3, 4, 3, 4, 2, 3 — cheap compared with a rewrite; still a custom stack.

### D8. Cross-cutting
| Concern | Decision |
|---|---|
| Logging | Install correlation middleware; `RequestIdFilter`; JSON in production; no PII. |
| Audit trail | Domain history tables stay with their owner (`ResourceChangeLog`, `TicketActivity`). No generic audit table. |
| Notifications | Infrastructure sends; features own outbox rows and delivery tasks. |
| Background tasks | `@shared_task(name="<app>.<feature>.<verb>")`, IDs in, idempotent, call commands. |
| Caching | Per-request role cache only, until a measured hotspot. |
| Configuration | django-environ in `config/settings`; features read settings only via config wiring or infrastructure. |
| Feature flags | None until a second real toggle exists. |
Score: 4, 3, 4, 5, 4, 4, 5, 5, 5 — wires what exists; adds nothing speculative.

### D9. Testing foundation
`core/common/testing/` (`assert_max_queries`, `assert_error`, API client fixtures; no business imports).
One owner per factory. import-linter contracts (report-only in P0, blocking in P6) plus the existing AST
architecture tests. OpenAPI drift check and Spectral in CI.
Score: 5, 4, 5, 4, 5, 5, 4, 5, 4 — makes agent rules machine-checkable.

### D10. Extensibility and migration
New features come from the scaffolder and inherit only from `core.common.*`. Base changes are additive with a
deprecation period, except the owner-approved breaking error-code release (Q3). Every structural phase keeps
the OpenAPI diff empty unless it is the approved contract change.
Score: 5, 5, 4, 4, 4, 5, 4, 5, 5.

---

## 4. Target structure

```text
core/common/                      # neutral kernel: no business app, no infrastructure, no config imports
├── contracts.py                  # Actor, PrincipalKind
├── domain/errors.py              # DomainError hierarchy (D6)
├── db/transactions.py            # atomic_command, constraint classification (D2)
├── models/
│   ├── timestamps.py             # TimestampsMixin (new models)
│   ├── user_stamped.py           # UserStampedModel
│   └── soft_delete.py            # TimestampedSoftDeleteMixin and managers
├── api/
│   ├── views.py                  # AppAPIView, AppListAPIView, AppDetailAPIView, CommandAPIView
│   ├── operations.py             # single operation() factory and schema hook
│   ├── errors.py                 # api_exception_handler + DomainError mapping
│   ├── pagination.py  filtering.py  permissions.py  serializers.py  correlation.py
├── queries/status_summary.py
├── logging.py                    # RequestIdFilter
├── openapi/  management/
└── testing/                      # assert_max_queries, assert_error, fixtures
core/infrastructure/              # unchanged; technical adapters only
core/users/public.py              # roles, actor construction
core/labs/features/base/          # labs-specific only: ResourceChangeLogMixin, resource serializers, SKU
```

Removed at the end: `core/common/api/responses.py`, business members of `MessageCode`, `BaseModelManager`,
`UserStampedQuerySet.*_stamped`, `core/utils/email.py`, `core/jira_integration`.

---

## 5. Phased plan

Each phase: existing suites green, `makemigrations --check` clean, OpenAPI diff empty unless the phase is an
approved contract change.

| Phase | Tier | Change | Acceptance | Rollback |
|---|---|---|---|---|
| P0 Guardrails | T2 (CI) | Move `api-lint.yml` to `.github/workflows/`; OpenAPI drift check; widen CI tests to the whole repository; changed-files Ruff; import-linter report-only. | CI shows Spectral, drift, import-linter results; tests run for all apps. | Revert workflow files. |
| P1 Observability | T2 (middleware) | Install correlation middleware; `RequestIdFilter`. | `X-Request-ID` echoed; log lines carry `request_id`; deploy check passes. | Remove middleware line. |
| P2 Errors (breaking) | T2 (contract) | `domain/errors.py` + single mapper; rename all codes to snake_case; delete per-view catch blocks; fix leaderboard `except Exception`. Publish code-mapping table and regenerated OpenAPI. | Envelope tests updated to new codes; Spectral passes; frontend notified. | Revert release. |
| P3 API consolidation | T1 | One `operation()`, one schema hook, one query-validation path; `CommandAPIView` and `atomic_command` in common; default pagination. | OpenAPI byte-identical (except pagination default where noted); query validation tests pass. | Re-exports keep old imports working. |
| P4 Authorization | T2 (security) | Merge `EquipmentAPIView`; one API-key policy per app base on all endpoints; Support permissions on `RolePermission`; log API-key prefix. | Permission matrix tests (user, API key, anonymous) per changed endpoint; security review. | Per-endpoint revert. |
| P5 Model hygiene | T1 | Delete `BaseModelManager` and `*_stamped`; fix docstrings; `TimestampsMixin`; split `base_models.py` with re-exports; one `UserFactory` owner. | No migrations generated; model tests pass. | Revert. |
| P6 Coupling | T2 | Signals → explicit `on_commit` handler; `core.users.public`; fix A13 and A17 with tests first; import-linter blocking. | Websocket publish still fires once per status change; zero import-linter violations. | Restore `signals.py`. |
| P-J Jira removal | T2 (destructive) | Remove route, OpenAPI files, `INSTALLED_APPS` entry, enum override; migration dropping tables (data deleted, Q4). | App gone; deploy check passes; no remaining imports. | Restore from backup only (irreversible data deletion). |
| P7 Removal | T1 | Delete `responses.py`, `MessageCode` aliases, `core/utils/email.py`. | No importers; tests pass. | Revert. |

---

## 6. AI-team rules

| # | Rule | Check | Decision |
|---|---|---|---|
| R1 | Feature errors subclass `core.common.domain.errors.*` and declare a snake_case `code`. Code changes ship only in a coordinated release with a frontend changelog. | Unit test walking `exceptions.py` | D6 |
| R2 | Views never catch feature exceptions or bare `Exception`. | grep in `api/**` | D6 |
| R3 | Every write is an application command with keyword-only `actor` wrapped in `@atomic_command`; only named constraints map to `Conflict`. | Review; grep for bare `except IntegrityError` | D2 |
| R4 | No business workflow in Django signals. | grep `@receiver` outside framework wiring | D4 |
| R5 | Cross-feature and cross-app imports only via `public` or `contracts`, including `core.users`. | import-linter | D4 |
| R6 | Views inherit permissions from one named app base; never combine `HasAPIKey` ad hoc. | Architecture test | D5 |
| R7 | Lists use `ResultsSetPagination` and `FilterSpec`; no custom page parsing. | grep | D3, D7 |
| R8 | List selector tests assert a query budget. | Review | D3 |
| R9 | Use the single `operation()` factory from `core.common.api`. | grep `def operation(` outside common | D7 |
| R10 | API changes regenerate OpenAPI in the same change; drift check and Spectral pass. | CI | D7 |
| R11 | New models use `TimestampsMixin`; soft delete only for delete-with-restore. | Review | D1 |
| R12 | A new common abstraction cites three real call sites (`path:line`). | Review | Constraint |
| R13 | Fixtures and factories have one owner; common tests import no business app. | Architecture test | D9 |
| R14 | Optimistic-lock failures raise `Conflict` with code `version_conflict` (409). | Review | Q5 |

---

## 7. Regret in two years
1. **Keeping the custom `AppAPIView` / `drf-api-contracts` stack.** Diverges from DRF idioms; upgrades may break
   the schema hooks. Mitigation: freeze its surface; backend owns it (Q10).
2. **Anonymous API keys on every endpoint (R-1).** No audit trail for key writes; one leak exposes everything.
   Mitigation: per-caller keys, rotation, no test key in production, key-prefix logging. Revisit if an incident
   or audit requirement appears.
3. **Single unversioned contract with breaking releases (Q6, Q3).** Every breaking change needs frontend lockstep.
   Mitigation: OpenAPI drift check, changelog per release, breaking changes batched.

---

## 8. Implementation log

| Date | Phase | Change | Checks |
|---|---|---|---|
| 2026-10-22 | P1 | `core/common/api/correlation.py` middleware, `core/common/logging.py` `RequestIdFilter`, request-id log format in `base.py` and `production.py`. | `manage.py check` passed. |
| 2026-10-22 | P2 | `core/common/domain/errors.py` plus one global mapper in `core/common/api/exceptions.py`. All labs and Support Desk exceptions subclass it. Per-view catch blocks removed. Equipment duplicate-SKU is now `SkuAlreadyExists` (`sku_already_exists`, 409). | `pytest core` run after each step. |
| 2026-10-22 | P3 | One `operation()`, `FeatureAPIView` and `CommandAPIView` in `core/common/api`, shared `atomic_command` / `apply_fields`, `ResultsSetPagination` as `DEFAULT_PAGINATION_CLASS` (`PAGE_SIZE` removed). | `pytest core`: 936 passed. |
| 2026-10-22 | P7 | Deleted `core/common/api/responses.py`, `core/common/api/message_code.py` (`MessageCode`, `MessageError`) and `core/utils`. Codes are snake_case literals or feature exception classes. | `pytest core`: 935 passed, 1 stale boundary test fixed, equipment suite 226 passed. |

| 2026-10-22 | P4 | One `EquipmentAPIView` (`equipment/api/common.py`); equipment, monitoring, resource-audit, finance and bench-booking views inherit `HasAPIKey \| IsAuthenticated` from `FeatureAPIView`. Equipment endpoints that were user-only now also accept an API key; bench bookings accept either user or key, no longer requiring both (Q1). | Equipment, monitoring, resource-audit, analytics: 402 passed; bench bookings: 72 passed. |
| 2026-10-22 | P5 | `core/common/models/base_models.py` split into `user_stamped.py` and `soft_delete.py`; `BaseModelManager` and `UserStampedQuerySet` (`*_stamped`) removed. No model change detected. | `pytest core/common`: 92 passed; `makemigrations --check` shows only the pre-existing `labs` 0006. |
| 2026-10-22 | P6 | `core.users.public` exports `LabsRole`, `has_labs_role`, `effective_labs_roles`, `IsLab*`; labs and Support Desk import from it. Labs signals already publish through `transaction.on_commit`; no change needed. | `pytest core/users` passed. |
| 2026-10-22 | P-J | Jira app code deleted; `core/users/migrations/0004_drop_jira_integration.py` drops its two tables, content types and migration rows. Irreversible. | `migrate --plan` lists it; not applied to any database. |
| 2026-10-22 | Cleanup | Removed 24 uncollectable stale modules plus 6 additional tests tied to removed URLs, fields, or app modules. Removed `.github/workflow/` and `build/openapi-check/`. Fixed the live inactive-equipment status enum reference, enabled DB access in the websocket invalid-token test, and aligned bench-booking auth tests with the shared policy. | `pytest tests --collect-only`: 495 collected; combined suite before bench-booking auth change: 1,416 passed, 12 skipped. |

## 9. Status after the redesign

Done: P1 to P7 and the Jira removal.

Not done:
- P0 CI and OpenAPI work (deferred by the owner; regenerate OpenAPI before release).
- Apply `users.0004_drop_jira_integration` per environment after a database backup.

Wire changes (breaking, announce to the frontend): error codes are snake_case; `validation_error` responses use
`validation_failed`; Support Desk, equipment and licenses errors follow the mapping table in section 3; optimistic-lock
failure returns 409 `version_conflict`; list endpoints without their own pagination use `ResultsSetPagination`.

The Jira drop migration is intentionally irreversible. Back up each environment before applying it.
