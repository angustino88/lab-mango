# API Error Details Audit and Remediation Tracker

**Status:** Audit (step 1) done 2026-11-27 at `main` `8e3a619`; findings F1–F10 below. No fix approved yet (owner, 2026-11-27: report only)  
**Risk tier:** T2 — shared/public API error-contract behavior  
**Scope:** Active API code under `core/` and shared response-contract code; exclude `features_old_do_not_edit_only_ref/`.

## Objective

Audit and, where approved, fix API error details so failures use the repository's canonical error envelope and provide useful, safe, correctly scoped field details. Do not mark the audit complete until every active API error path is inspected and accounted for.

## Required reading and workflow

- [ ] Read `AGENTS.md`, applicable `.github/instructions/`, `docs/ai-team/team.md`, and `docs/ai-team/quality-gates.md`.
- [ ] Read `.github/instructions/api-design.instructions.md`, `docs/api/response-standard.md`, and `docs/api/response-golden-examples.md`.
- [ ] Identify the Engineering Lead and relevant specialists; follow the repository's T2 design/review workflow before merge.
- [ ] Check applicable ADRs and existing API/schema conventions.
- [ ] Keep active implementation scope to `core/`; do not modify `features_old_do_not_edit_only_ref/`.

## Contract invariants

- [ ] Every API error uses `{"error":{"code","message","details","request_id"}}`.
- [ ] `details` is always an array. Each field error is one `{ "field", "code", "message" }` object.
- [ ] Error codes remain stable snake_case; preserve DRF `ErrorDetail.code` values.
- [ ] A structured detail `{field, code, message}` is atomic. Never recursively reinterpret its keys as field paths (e.g. `0.field`, `0.code`, `0.message`).
- [ ] Use dotted paths for nested objects and `[n]` only for actual request-array elements (e.g. `items[0].quantity`).
- [ ] Do not add an index solely because DRF represents validation failures as a list. Scalar missing relation: `setup_location_id`, not `setup_location_id[0]` or `0.setup_location_id`.
- [ ] Keep generic not-found, permission-denied, malformed-body, and sanitized server errors appropriately generic; empty details can be correct.
- [ ] Do not expose stack traces, SQL, paths, internal identifiers, secrets, raw unsafe exception text, or sensitive resource existence.

## Work plan

### 1. Inventory and trace

- [x] Trace global exception handlers, shared response helpers and `ResponseContract` serialization.
- [x] Trace request serializer validation and strict/unknown-field validation.
- [x] Trace command/application exception mapping and endpoint-specific `respond_problem()` calls.
- [x] Include non-`AppAPIView` endpoints, auth endpoints, support-desk/Jira integrations, and framework-generated failures.
- [x] Record each active API/error path, current output shape, applicable contract, and whether its details are safe and useful.

Inventory (2026-11-27): 402 API routes resolved from the URL configuration (admin excluded): 379 on the
shared contract views (`AppAPIView`), 15 agents views with their own envelope (`core/agents/api/views.py`),
4 routing sync views (`core/routing/api/views.py`), 4 notification views on DRF generics
(`core/websocket/features/list_notifications/`). The per-route table is in the audit pull request (working
artifact, `docs/ai-team/documentation-map.md`). Every finding marked "endpoint" was reproduced with a request
through the test client; "unit" was reproduced by calling the normalizer with real DRF serializer errors.

| Feature/module | Endpoint/error path | Current behavior | Finding (severity) | Fix/test needed | Status |
|---|---|---|---|---|---|
| Shared contracts | `drf_api_contracts.responses._error_details()` | Treats `{field, code, message}` as atomic; otherwise same flattening as the global handler | F1, F2, F3, F4 (Medium) | One canonical normalizer (F5) | Audited |
| Global exception handler | `core/common/api/exceptions.py` `_validation_details()` | Envelope, 401 challenge, generic 5xx are correct; second copy of the flattening without the atomic-detail rule | F1–F5 (Medium) | Same | Audited |
| Shared API views | `AppAPIView.validate_request()`, strict unknown fields | Unknown/read-only fields and serializer errors go through `_error_details()`; codes preserved | Inherits F1/F2 | Unit tests per shape | Audited |
| Labs shared bases | `core/labs/features/base/retrieve_update_delete.py:145`, `equipment/api/list_create.py:149`, `equipment/api/retrieve_update_by_key.py:62` | Django `ValidationError.message_dict` / `.messages` passed as `errors` | F4 (Medium), up to 157 routes | Convert with codes, no index | Audited |
| Labs features | license checks, resource mappings, benches, resource audit, analytics, leaderboard (19 routes) | Plain-string `errors` / `details` | F3 (Medium) | Real codes per message | Audited (endpoint) |
| Agents | `core/agents/api/views.py` `_error_response`, `_validation_details` | Own envelope; details lack `code`; first message per field only | F6 (Medium) | Use shared normalizer | Audited |
| Routing sync | `core/routing/api/views.py` `error_response` | Own envelope, `X-Request-ID` set; details lack `code` | F6 (Medium, Router contract) | Additive `code`, agree with Router repo | Audited |
| Notifications | `list_notifications/api.py`, `inbox.py` | Uses `ResponseContract.respond_problem()` with `ErrorDetail` codes | None | — | Audited |
| Users/auth/profile | `core/users/features/auth/**`, `profile/avatar` | Fixed, generic messages; no token or claim text echoed | None | — | Audited |
| Support desk | `core/support_desk/**` (no Jira code in this repository) | Domain errors through the global mapper | Inherits F1 | — | Audited (endpoint) |
| Framework failures | unknown route, 405, parse, 415, CSRF, 5xx | 404 for unknown routes is Django HTML; 405 code `api_error`; others correct | F7 (High), F9 (Low) | `handler404`/`handler500` for API prefixes | Audited (endpoint) |
| Correlation | `core/common/api/correlation.py` | `RequestCorrelationMiddleware` is not in `MIDDLEWARE` | F8 (High) | Install it | Audited (endpoint) |

### Findings

Severity used here: High = a MUST rule broken on many routes; Medium = wrong or less useful details;
Low = cosmetic or documentation. Rules are in `docs/api/response-standard.md`.

- **F1 (Medium, unit + endpoint).** `ListField` child errors render as `labels.1`, not `labels[1]` (ERR-6). DRF
  reports them as a mapping with integer keys. Reproduced: `POST /api/support/tickets` with a 60-character label.
- **F2 (Medium, unit).** A top-level error list (`raise ValidationError("msg")` in a view, Django
  `ValidationError(...).messages` at `base/retrieve_update_delete.py:145`) renders `field: "0"`, an artificial
  numeric prefix. Expected `field: null`.
- **F3 (Medium, endpoint).** Plain strings in an error list gain an index and lose their code: `key[0]` with
  code `invalid` for "This field is required." Reproduced on `POST /api/labs/license-checks` (`api/views.py:86`),
  `GET /api/labs/resource-mappings?bogus=1` (`api/views.py:59`), `GET /api/labs/leaderboard/lab?start_date=nope`
  (`leaderboard/api/views.py:51`, `date[0]`). Also `benches/api/views.py:114`, `resource_audit/api/views.py:264`,
  `analytics/api/utilization/views.py`, plain-string `DomainError(details=...)` in `procurement`, `license_checks`
  and `lab_sessions` (codes `invalid` only; `lab_sessions` keeps the first message per field, ERR-7).
- **F4 (Medium, unit).** Django `ValidationError` is rendered from `message_dict`, which drops the error codes
  and yields `name[0]` (`core/common/api/exceptions.py:85`, and the three labs call sites above).
- **F5 (Medium, unit).** Two normalizers: the global handler does not treat `{field, code, message}` as one
  detail and explodes it into `0.field`, `0.code`, `0.message`; the package copy does. No caller passes that
  shape to a `DomainError` today, so it is latent.
- **F6 (Medium).** Agents (15 routes) and routing (4 routes) build details as `{field, message}` without `code`
  (ERR-2/ERR-6); agents keep only the first message per field (ERR-7). Their OpenAPI `ErrorDetailItem` has no
  `code`. Routing is a contract with the Router repository: adding `code` is additive but must be agreed there.
- **F7 (High, endpoint).** `GET /api/<unknown>` and `/agent/<unknown>` return Django's HTML 404 without
  `X-Request-ID` (ERR-8). No `handler404` or `handler500` is configured, so an exception outside DRF also
  renders HTML.
- **F8 (High, endpoint).** `RequestCorrelationMiddleware` is defined but never installed. Responses built by
  `ResponseContract.respond_problem()` and all success responses carry no `X-Request-ID` (ERR-4, OBS-1), and the
  production log format `[%(request_id)s]` (`config/settings/production.py:124`) always prints `-`, so a 5xx
  cannot be correlated from its `request_id` (ERR-9). The global handler and routing set the header themselves.
- **F9 (Low, endpoint).** 405 renders code `api_error` (no 405 entry in `_ERRORS`); routing uses
  `method_not_allowed`. Changing a released code needs approval (ERR-2).
- **F10 (Low).** `ProblemDetail.details` is documented as untyped objects, not `{field, code, message}`.

Checked and safe: every `str(exc)` returned to clients carries a fixed message (visual models, workbook import,
analytics observations, agents enrollment); `IntegrityError` text is never returned; 5xx is generic; auth
failures are generic. The prior bench `setup_location_id` / `does_not_exist` case passes
(`core/labs/features/benches/tests/test_bench_detail_contract.py`).

Not in scope of this audit, found on the way: `packages/drf-api-contracts/tests` is not collected by CI
(`pyproject.toml` `testpaths`) and fails when run (2 failures from the repository root, 15 from the package
directory); not investigated.

### 2. Design and implement

- [ ] Define one canonical normalization point for error details; prevent double-flattening across view and response-contract layers.
- [ ] Preserve DRF codes/messages when safe; normalize plain Django/ordinary errors without inventing field paths.
- [ ] Keep top-level domain error code/message behavior stable unless an approved contract change explicitly says otherwise.
- [ ] Fix only verified issues; avoid unrelated refactors and blanket replacement of empty details.
- [ ] Document any public contract changes, compatibility/deprecation considerations, and required human approval.

### 3. Tests

- [ ] Unit test scalar field validation, including missing relation code `does_not_exist`.
- [ ] Unit test nested object paths (`parent.child`).
- [ ] Unit test actual array-item paths (`items[0].quantity`).
- [ ] Unit test a list of ordinary field errors does not gain an artificial numeric prefix.
- [ ] Unit test structured `{field, code, message}` detail is preserved atomically.
- [ ] Test unknown/read-only fields and stable error codes.
- [ ] Test generic 404/403/parse/5xx behavior remains appropriately empty or sanitized.
- [ ] Add endpoint-level contract tests across representative active features, including auth and integration paths where applicable.
- [ ] Ensure all acceptance criteria map to a test.

### 4. OpenAPI and quality verification

- [ ] Review error schema definitions and representative generated OpenAPI artifacts for compatibility.
- [ ] Regenerate OpenAPI only via the repository's documented command/process; inspect and summarize the diff.
- [ ] Run focused tests, broader relevant API tests, Ruff check/format, and applicable quality gates.
- [ ] Run Spectral if configured and report its findings/baseline accurately.
- [ ] Run `git diff --check` and inspect the final diff for scope creep.
- [ ] Report every command with its observed result; label unrun checks explicitly as **not run**.

### 5. Review and closeout

- [ ] Independent reviewer examines implementation and tests without relying on author summary.
- [ ] Security and QA review completed as required by T2 workflow.
- [ ] Human approval obtained before merge for public API-contract changes.
- [ ] Handoff report records inventory coverage, changed paths, tests, OpenAPI impact, unresolved items, and residual risk.

## Acceptance criteria

- [ ] An endpoint-by-endpoint inventory accounts for every active API error path in scope.
- [ ] Error details are structurally correct and follow the field-path rules above.
- [ ] Error messages/details are useful without leaking sensitive/internal information.
- [ ] No existing endpoint is claimed fixed without a relevant passing test or documented verification.
- [ ] API/OpenAPI compatibility implications are reviewed and disclosed.
- [ ] Review, approval, quality gates, and remaining gaps are explicit in the handoff.

## Known prior-session evidence (not a complete audit)

- A bench missing-reference case was changed to return one detail with `field: "setup_location_id"`, `code: "does_not_exist"`, and message `Select an existing setup location.`
- Shared contract handling was adjusted to treat `{field, code, message}` as an atomic detail and to retain indexes for real nested arrays.
- At that point, a focused run reported 26 tests passed and Ruff passed. A subsequent small change to `_error_details()` list handling was made but was **not rerun** in that session. Reverify it.
- Prior selective sanitization work and Spectral changes were not an exhaustive endpoint-by-endpoint review. Do not treat them as audit completion.

## Handoff

Use `docs/ai-team/templates/handoff-report.md`. State the audited scope, inventory coverage, modified files, exact commands and outputs, OpenAPI/Spectral results, independent review status, unrun checks, open questions, and residual risks.
