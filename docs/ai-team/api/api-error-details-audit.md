# API Error Details Audit and Remediation Tracker

**Status:** Not started — tracking brief for a future session  
**Risk tier:** T2 — shared/public API error-contract behavior  
**Scope:** Active API code under `core/` and shared response-contract code; exclude `features_old_do_not_edit_only_ref/`.

## Objective

Audit and, where approved, fix API error details so failures use the repository's canonical error envelope and provide useful, safe, correctly scoped field details. Do not mark the audit complete until every active API error path is inspected and accounted for.

## Required reading and workflow

- [ ] Read `AGENTS.md`, applicable `.github/instructions/`, `docs/ai-team/team.md`, and `docs/ai-team/quality-gates.md`.
- [ ] Read `.github/instructions/api-design.instructions.md`, `docs/ai-team/api/response-standard.md`, and `docs/ai-team/api/response-golden-examples.md`.
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

- [ ] Trace global exception handlers, shared response helpers and `ResponseContract` serialization.
- [ ] Trace request serializer validation and strict/unknown-field validation.
- [ ] Trace command/application exception mapping and endpoint-specific `respond_problem()` calls.
- [ ] Include non-`AppAPIView` endpoints, auth endpoints, support-desk/Jira integrations, and framework-generated failures.
- [ ] Record each active API/error path, current output shape, applicable contract, and whether its details are safe and useful.

Inventory table (complete during audit):

| Feature/module | Endpoint/error path | Current behavior | Finding (severity) | Fix/test needed | Status |
|---|---|---|---|---|---|
| Shared contracts | `ResponseContract.respond_problem()` / `_error_details()` | Bench case fixed previously; broader audit pending | TBD | Add coverage for canonical and nested shapes | Not audited |
| Shared API views | Request and query validation | TBD | TBD | TBD | Not audited |
| Global exception handler | `core/common/api/exceptions.py` | TBD | TBD | Generic/safe failures and envelope | Not audited |
| Labs features | All active API modules | TBD | TBD | Endpoint inventory required | Not audited |
| Users/auth/profile | All active API modules | TBD | TBD | Safe details, auth behavior | Not audited |
| Support desk/integrations | All active API modules | TBD | TBD | Sanitization and error mapping | Not audited |

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
