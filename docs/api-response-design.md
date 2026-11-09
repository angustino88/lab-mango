# API Response Redesign — Audit Status

## Status

The in-place API redesign is **in progress**, not complete. The response standard is the target contract; active endpoint coverage still requires a complete audit. This is a breaking public API redesign and must not be merged or released until the repository owner approves it and required independent review is complete.

## Verified work

- The target success and error envelopes, pagination shape, query-control policy, and error status semantics are defined in [the response standard](ai-team/api/response-standard.md) and [golden examples](ai-team/api/response-golden-examples.md).
- The common API transport implements request correlation, standardized errors, shared pagination, request validation, and query-key validation in selected API paths.
- Selected user endpoints, representative Labs endpoints, and common API unit tests were aligned to the target envelope.
- Focused unit validation most recently observed: **47 passed** across `tests/unit/test_api_errors.py`, `tests/unit/test_api_transport.py`, and `tests/unit/test_api_response_schema.py`.
- OpenAPI dry-run most recently validated 21 documents without writing generated files. It emitted a duplicate `NamedReference` component warning, two status-enum naming collision warnings, and a database URL configuration warning.

## Incomplete audit and validation

- A complete active-endpoint inventory has not been verified. In particular, collection endpoints without declared query serializers may not enforce the unknown-query-key policy, and the Jira proxy API still requires explicit review.
- The complete `respond_problem()` versus declared-error-response audit and response-envelope versus schema audit remain unfinished.
- The package-level `ResponseContract.respond_page()` generates a legacy pagination payload shape rather than the canonical public shape. Its tests assert that legacy shape. Migration needs to update package runtime, schema behavior, package tests, settings, and all call sites together.
- User profile/auth database-backed test results after recent fixes were not observable from the command output and therefore are **not claimed as passing**. Database-backed integration/booking tests remain outstanding.
- Ruff lint and formatting checks passed on the most recent checked Python files. OpenAPI warnings have not been resolved.
- No independent code review or owner approval has been completed.

## Targeted endpoint audit update — 2026-10-16

The following is a targeted inspection of active source files, not an exhaustive endpoint inventory. Reference-only code under `core/labs/features_old_do_not_edit_only_ref/` was excluded.

### Verified findings

- Location primary room/station lists and bench list/select operations declare query serializers and call `validate_query()`. Room slots/history/observations, station slots/history/types, and bench reference lists declare `many=True` without query contracts. The shared location `operation()` helper paginates only selected `many=True` contracts according to its `query`/`request` arguments. Classify bounded nested/reference data separately from resource collections; true collections need standard pagination and allowlisted query validation.
- License inventory and agreement lists declare paginated responses and use `AppListAPIView`, but do not declare query serializers or call `validate_query()`.
- Procurement purchase, purchase-item, allocation, and transaction lists declare paginated responses and use `AppListAPIView`, but do not declare query serializers or call `validate_query()`.
- Jira issue search directly parses `startAt` and `maxResults` (clamped to 0+ and 1–100) and accepts `search`; it has a declared 400 response but no query serializer, so unknown keys are not rejected. Preserve the upstream offset semantics unless the API owner approves a change.
- Jira issue-request ViewSet list and custom actions return raw DRF response bodies rather than the shared success/error envelope. Its list schema declares a bare serializer array. The queryset does scope non-admin/coordinator users to their own reporter records. Reconcile action schemas, pagination, allowlisted search/order keys, and error mapping together without weakening that scoping.
- Shared transport changes in the working tree supply the request correlation ID for explicit 5xx problems and raise an explicit configuration error if unknown query keys arrive at an operation lacking a `bad_request` contract. Regression tests for both cases are in `tests/unit/test_api_transport.py`.

### Validation update

- Ruff lint and format check passed for `core/common/api/api_views.py` and `tests/unit/test_api_transport.py`.
- The focused database-backed pytest run did not complete successfully: PostgreSQL reported that `test_labmango_local` already existed and was in use by another session. No test-pass result for the latest transport changes is claimed. Do not terminate sessions or drop that database without explicit authorization; rerun against an isolated test database.
- Editor diagnostics report unresolved `drf_api_contracts` imports in those two files; runtime import resolution was not established in this check.

## Incomplete implementation areas

1. Inventory active collection endpoints and require explicit allowlisted query serializers, pagination contracts, and runtime pagination behavior.
2. Fix the package-level pagination helper and its tests to use the documented `data` and `meta.pagination` shape, with the standard page, size limit, and next/previous links; eliminate legacy `total_count`/`results` input conventions after caller review.
3. Audit every call to `respond_problem()` against its declared response name and status, and audit every runtime response against its generated schema.
4. Review Jira pagination/query behavior as an upstream integration; do not blindly apply local page-number pagination if its upstream cursor/offset contract must remain visible.
5. Rerun focused unit tests, user DB-backed tests, relevant database-backed integration tests, Ruff lint/format, and OpenAPI preview; report unavailable database checks as blocked.
6. Review generated schema changes against the breaking-change plan and resolve or explicitly accept remaining schema warnings.
7. Obtain security/QA and independent code review, then explicit repository-owner approval before merge or release.

## Compatibility and release constraint

This redesign changes public response contracts in place. It is intentionally not a parallel versioned API. Consumers require a coordinated migration; do not merge or release until the owner approves the compatibility and rollout plan.
