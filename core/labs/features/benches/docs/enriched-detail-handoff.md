# Handoff: approved enriched bench detail

> **Superseded public contract:** the approved implementation history below records
> an earlier enriched ordinary bench GET. On 2026-10-20 the user approved moving
> operational enrichment to the dashboard click endpoint and making ordinary bench
> GET lean. Use [bench-station-apis.md](bench-station-apis.md) for the current API
> contract. Prior commands/results below describe the earlier implementation, not
> verification of the superseding lean endpoint or dashboard detail privacy change.

**Role:** Backend Engineer · **Tier:** T2 · **Status:** implemented; broader gates
and independent review remain open. No merge or release performed.

## Scoped independent-review corrections (2026-10-20)

This section supersedes the earlier evidence qualifications below. Historical
results are retained, not represented as normal/full integration success.

### Files and behavior changed

- Bench serializers/views and the benches OpenAPI module: GET-specific
  `BenchDetailErrorEnvelope` and nested error/item components document
  `{error: {code, message, details, request_id}}` for 400 and 404. Shared
  `ProblemDetail` and unrelated operations/components are preserved.
- A newly added runtime schema test reproduced an extra mismatch: out-of-range
  equipment pages returned DRF `{detail: ...}`. Only that GET branch now calls
  the existing `respond_problem` envelope responder; missing benches and invalid
  queries also validate against the committed schema.
- Scoped generator explicitly retains `labs_benches_retrieve_by_bench_id`.
  `--check` compares the stored GET plus all reachable component definitions to
  the generated candidate and fails on semantic drift, without writing.
- Permanent generator tests cover operation ID, operation/component drift and
  unrelated-change isolation. Permanent API edge tests cover 100 of 101 computers
  and the final page within seven queries each, exactly five current bookings
  being complete, cancelled/expired current and future exclusion, and cross-bench
  equipment/activity/current/next isolation.
- Formatter-suggested output was applied through patches to new modules and only
  enriched-detail hunks in existing files. No unrelated whole-file rewrites.

No migration, dependency, permission, global exception handler or unrelated URL
operation ID changed. No deployment or merge performed. Existing dirty work retained.

### Observed commands and results

All executions used `D:/02_tools/prj.labmango_backend.v2/.venv/Scripts/python.exe`
(Python 3.12.12); `VIRTUAL_ENV` and terminal PATH were explicitly configured.
Pylance environment configuration tools were unavailable; no claim is made about
the editor-selected interpreter.

- `P -m scripts.openapi.generate_bench_detail`: generated only benches module.
- `P -m scripts.openapi.generate_bench_detail --check`: passed, 16 reachable
  components, no files written. Check before regeneration failed on drift.
- `P -m pytest scripts/openapi/tests/test_generate_bench_detail.py --ds=config.settings.test -q --tb=line -p no:sugar`:
  **5 passed in 10.86s**, without database setup.
- Isolated invocation of `pytest.main` with enriched-detail, API serializer and
  generator tests, `--ds=config.settings.feature_test -p no:sugar -q --tb=line`:
  **41 passed in 30.12s**. This is API-only synthetic PostgreSQL evidence, NOT
  the ordinary pytest command or full migration/root-route integration.
- `P -m ruff check` on bench serializers/views/detail query/enriched tests,
  generator and generator tests, computing query and booking query: **all checks passed**.
- `P -m mypy core/labs/features/benches/queries/detail.py scripts/openapi/generate_bench_detail.py core/labs/features/equipment/categories/computing/queries.py core/labs/features/bench_bookings/queries/bench_bookings.py --follow-imports=silent`:
  **success, four source files**. Full API typing was not recertified.
- `P -m ruff format --check` on serializers, new query/tests/generator and owner
  queries: six files formatted; enriched test file still reports trailing blank
  lines after patch application. Substantive test formatting is applied; that
  EOF-only gate remains open. Whole view format still flags unrelated old hunks,
  intentionally not rewritten.
- Scoped `git diff --check`: passed. Generator preservation assertions passed.
- Under `config.settings.test`, `django.setup()` and
  `resolve('/api/labs/benches/1')`: **BenchDetailAPIView resolved**. No earlier
  analytics syntax failure reproduced. That earlier failure was transient in
  the dirty tree, not a currently demonstrated root-routing blocker.

### Exact isolation methodology and limitations

The dedicated synthetic loopback cluster was initially stopped; early attempts
timed out. Its existing temporary feature cluster was started with PostgreSQL 18
`pg_ctl start -D <existing labmango-feature-pg directory> -l <directory>/server.log
-o '-h 127.0.0.1 -p 55439' -w`; observed `server started`.

Before importing pytest, set `DJANGO_SETTINGS_MODULE=config.settings.feature_test`
and `LABMANGO_FEATURE_TEST_PORT=55439`, then run `django.setup()`. Load
`tests/feature_db.py` into an in-memory module after adding `BenchBooking` and
`ComputingActivity` both to its imports and initial pending models. Register its
fixture plugin from a `pytest_configure(trylast=True)` bootstrap so it overrides
pytest-django setup. No feature_db file changes were persisted. The API fixture
sets isolated bench URL patterns and excludes allauth middleware while using
`force_authenticate`; this exclusion is explicit in the permanent test fixture.

Prior QA's successful independent runs used equivalent in-memory model additions
and allauth exclusion. The earlier 109-pass command in this document omitted those
qualifications and must not be read as a normal invocation result. Standard
invocations can still fail on `gin_trgm_ops`/legacy schema setup; they were not
certified here. Initial failed harness attempts used the wrong fixture selection;
the final bootstrap fixed selection. The new schema test first failed on page-404
(`1 failed, 29 passed`), then passed after the local responder correction.

Full repository, normal migration integration, real authentication middleware,
full root-route HTTP integration, production checks and independent re-review of
these corrections are not run. User-supplied review found safe read behavior and
booking/data-minimization boundaries sound, but owner approval/re-review is still
required before T2 merge. The temporary synthetic cluster remains running for
further QA; no production database was accessed.

## Summary and files changed

The following earlier implementation summary is historical; it is not the current
public GET response shape.

- Bench API serializers/views: separate GET detail serializer, strict equipment
  pagination query contract, canonical detail-only equipment URL, bounded nested
  equipment page and booking summary. Existing list/write serializers preserved.
- New `queries/detail.py`: deliberate bounded read composition through owner public
  facades; one timestamp injected from the view. Existing selectors unchanged.
- Equipment computing queries/public: safe batch subtype/activity projection,
  minimal selected columns, no stored-default creation or freshness reconciliation.
- Booking queries/public: minimal bounded reserving schedule projection; deterministic
  half-open current and strictly future next selection, total count/completeness.
- New `tests/test_enriched_detail.py` and `tests/detail_urls.py`: 23 focused cases,
  synthetic PostgreSQL data, isolated canonical bench URLs, OpenAPI response
  validation and public-boundary assertion. Updated equipment export expectation
  for the new public query only.
- Bench API/architecture docs and approved task/design updated.
- New `scripts/openapi/generate_bench_detail.py`: scoped generation, validation and
  preservation assertions. Only `openapi/labs-benches.yml` regenerated; existing
  unrelated operations/components retained. Other schemas not written.

## Migrations / API / schema impact

Historical implementation impact (superseded by the decision above):

No models, migrations, dependencies, permissions, application write commands or
production data changed. Public GET adds equipment/booking fields and the two
approved query parameters. REL-8 inline and GET-only write-shape exceptions are
documented. Pagination stays on the detail route; equipment subresource unchanged.

## Evidence ledger

| Acceptance criterion | Code | Test | Result |
|---|---|---|---|
| Retain bench fields; GET-only additions | API serializers/views | empty detail; list/write unchanged | passed |
| Equipment default 20/max 100, pages and strict allowlist | detail query, query serializer | bounds, repeated/unknown/invalid input, pagination | passed |
| Safe computing projection, nullable default and strict stale cutoff | equipment owner query | noncomputing/missing/multiple computers/freshness/no writes | passed |
| Active/approval and temporal booking boundaries; minimal references | booking owner query | temporal/approval/minimal projection/cap/determinism | passed |
| Existing authenticated visibility, anonymous denial | unchanged IsAuthenticated | anonymous/other-owner reads | passed |
| Deleted/unassigned equipment excluded | existing selector | deleted/unassigned/missing bench | passed |
| No GET writes or N+1 | detail composition | SQL capture and seven-query maximum with 20 computers/six bookings | passed |
| Schema matches runtime; no private composition imports | generated module / composition | committed OpenAPI validator / AST boundary | passed |

## Commands run and outcomes

All Python commands used the configured virtual environment executable, Python
3.12.12. Commands below are from the repository root; `P` denotes the exact
executable `.venv/Scripts/python.exe` (resolved to the user's specified venv).

Final regression command:

`P -m pytest core/labs/features/benches/tests/test_enriched_detail.py core/labs/features/benches/tests/test_api_serializers.py core/labs/features/bench_bookings/tests/application/test_bench_booking_commands.py core/labs/features/bench_bookings/tests/application/test_state_transitions.py core/labs/features/bench_bookings/tests/application/test_booking_status_transitions.py core/labs/features/bench_bookings/tests/application/test_booking_policies.py core/labs/features/equipment/tests/categories/computing/test_computing_activity_application.py -q --reuse-db --tb=short -p no:sugar`

**Output:** `109 passed in 9.09s`. PostgreSQL, configured test settings, synthetic
test records. Includes 23 enriched-detail cases. Previous focused iterations:
21 passed in 5.68s; 108 passed in 11.68s before the final boundary assertion.
Initial fixture failures were corrected (mandatory equipment kind/category
definition); UTC output was made explicit for new timestamp fields.

`P -m scripts.openapi.generate_bench_detail --check`:
**Output:** `Validated bench detail GET and 14 reachable components; no files written.`

`P -m scripts.openapi.generate_bench_detail`:
**Output:** `Validated bench detail GET and 14 reachable components; updated only openapi/labs-benches.yml.`
The existing spectacular_modules flags were inspected: no module selector exists,
so that all-module writer was not run. The new scoped generator uses only bench
URL patterns and checks unrelated operations/components for preservation.

`P -m ruff check core/labs/features/benches/api/serializers.py core/labs/features/benches/api/views.py core/labs/features/benches/queries/detail.py core/labs/features/benches/tests/test_enriched_detail.py core/labs/features/benches/tests/detail_urls.py core/labs/features/equipment/categories/computing/queries.py core/labs/features/equipment/public.py core/labs/features/equipment/tests/test_public_boundary.py core/labs/features/bench_bookings/queries/bench_bookings.py core/labs/features/bench_bookings/public.py scripts/openapi/generate_bench_detail.py`

**Output:** `All checks passed!`

`P -m mypy core/labs/features/benches/queries/detail.py core/labs/features/equipment/categories/computing/queries.py core/labs/features/bench_bookings/queries/bench_bookings.py --follow-imports=silent`

**Output:** `Success: no issues found in 3 source files`.

`P -m mypy core/labs/features/benches/queries/detail.py core/labs/features/benches/api/serializers.py core/labs/features/benches/api/views.py core/labs/features/equipment/categories/computing/queries.py core/labs/features/bench_bookings/queries/bench_bookings.py --follow-imports=silent`

**Outcome:** 11 errors remain in existing serializer/write/view portions (Meta
validators/extra_kwargs, existing field iteration, base permissions typing,
optional filter mappings, reference-view model typing). New nested data-property
and Meta inheritance typing errors found during implementation were removed.
Editor diagnostics reported no errors in the checked changed files.

`P -m ruff format --check core/labs/features/benches/api/serializers.py core/labs/features/benches/api/views.py core/labs/features/benches/queries/detail.py core/labs/features/benches/tests/test_enriched_detail.py core/labs/features/equipment/categories/computing/queries.py core/labs/features/equipment/public.py core/labs/features/bench_bookings/queries/bench_bookings.py core/labs/features/bench_bookings/public.py`

**Outcome:** six files would be reformatted, two already formatted. Whole-file
rewrites were not applied to this heavily dirty tree; formatting gate remains open.

Broader command:

`P -m pytest core/labs/features/benches/tests core/labs/features/bench_bookings/tests core/labs/features/equipment/tests/categories/computing core/labs/features/equipment/tests/test_public_boundary.py tests/architecture -q --reuse-db --tb=short -p no:sugar`

**Output:** `18 failed, 162 passed in 12.69s`. Failures outside enriched detail:
existing bench options ordering forwarded to a selector without that argument;
bench query-export test omits existing list_bench_equipment/list_bench_options;
14 booking API tests use old slash-terminated paths; two equipment static tests
flag existing API ORM/command transaction structure. Unrelated code left intact.

Subsequent broader command:

`P -m pytest core/labs/features/benches/tests/test_enriched_detail.py core/labs/features/benches/tests/test_api_serializers.py core/labs/features/bench_bookings/tests/application core/labs/features/equipment/tests/categories/computing tests/architecture -q --reuse-db --tb=short -p no:sugar`

**Output:** `39 failed, 98 passed in 53.45s`, all failures blocked by an unrelated
analytics API syntax error during root URL imports. This appeared in the changing
dirty tree during the session. Focused tests now use isolated bench URL patterns;
this does not certify root URL integration. The unrelated file was not edited.

## Not run / risks / decisions

- Full repository suite and release/production checks not run. Historical broad
  suites above did not pass; current root URL resolution succeeds as qualified
  in the scoped corrections section. Full HTTP integration remains unverified.
- import-linter not installed; AST boundary assertion and existing architecture
  tests were used, without adding dependencies or claiming full gate success.
- Independent reviewer/security/QA agent execution unavailable in this session.
  Self-review is not independent review. T2 approval before merge is still required.
- No migrations touched; migration checks/apply not run. No deployment or DB
  production changes. Secret scan and breaking-change comparison versus a clean
  approved base not run; the existing huge dirty diff includes others' changes.
- Read-committed projections are not a transactional snapshot or booking guard.
  Counts may change between read queries on concurrent writes. Page responses
  remain bounded; booking mutation invariants are unchanged.
- No shared clock helper was found; existing timezone.now is sampled once in the
  view and injected into queries. New live/schedule timestamps are UTC.
- EOF-only test formatting, unrelated view formatting and pre-existing API type
  errors remain visible gates. Human owner
  should arrange independent review and resolve unrelated integration blockers
  before merge/release. No unrelated cleanup or destructive operations performed.
