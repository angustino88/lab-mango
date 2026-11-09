# Inventory facets handoff

## Status
Reviewer fixes implemented; final focused suite **70 passed**, independently reproduced. Independent code review, Security, and QA **approve this scoped patch** with nonblocking limits. Human merge approval and resolution/acceptance of unrelated gate failures remain outstanding. No deployment, production data access, secrets inspection, migrations, dependencies, permission changes, or application writes were performed. Synthetic fixture writes occurred only in PostgreSQL tests.

### Final independent signoffs — supersedes earlier pending-review statements

- Independent code reviewer: approved; reproduced 70 focused passes and the wider 385 passes / two unchanged stale-signal failures. Inspected all 13 schema operations and in-memory regeneration parity for 29 artifacts. No attributable Blocker/Major findings.
- Security: approved; independently inspected pagination guards, allowlisted aggregation, authentication alternatives, all 13 persisted schemas, and whitespace. Relied on the independent reviewer's completed database run; did not rerun it.
- QA: approved after inspecting strengthened model/parent/CSV/schema coverage. Its own run was interrupted after 49 passes, not a completed run; approval also relies on the independent reviewer's completed 70-test evidence.
- Remaining limits: representative-volume profiling, broader feature rollout, exhaustive subtype/date/CSV combinations and high-cardinality pagination. Existing formatting, mypy, Spectral and stale computing-test failures remain outside the patch. No deployment or full-repository green claim.

## Reviewer-fix continuation — authoritative latest results
This section supersedes the original implementation gate counts and coverage limits below; the original gate table remains historical evidence.

### Changes and acceptance evidence
- `api/facets.py`: typed page minimum/default 1 and page_size minimum 1/default 25/maximum 100 for all 13 operations. Both controls and dimension are excluded before FilterSpec.apply. `test_all_facet_operations_document_pagination_and_api_key` covers all operations, both default/custom API-key headers; `test_pagination_controls_are_not_membership_filters` fails if controls leak into membership filters.
- `core/common/api/api_views.py`: shared conversion checks DRF IntegerField.MAX_STRING_LENGTH (1000), ASCII decimal syntax, and catches ValueError before any paginator/inventory work. `test_oversized_decimal_pagination_is_400_before_inventory_sql` covers generic/computing × page/page_size with 5000 digits, 400 invalid_query, correct details field, **zero total SQL queries** under authenticated fixtures.
- `api/facets.py`: schema-only subclass extends the already configured project schema without a feature-to-config import. Security registration follows the existing finance schema mechanism; documents API-key OR JWT OR cookie, never anonymous, and respects API_KEY_CUSTOM_HEADER. Runtime HasAPIKey | IsAuthenticated is unchanged.
- `test_every_category_generates_facets`: all 12 adapters now create a real category-subclass record, assert its exact list ID and positive category bucket; cannot pass from empty populations.
- `test_parent_only_siblings_crossed_relationships_and_csv_conjunction`: category-only sibling kinds/types/manufacturers/models, kind-only/type-only/manufacturer-only parents, department-only sibling/crossed groups, two CSV dimensions with OR within / AND across and a zero-result crossed selection. Historical crossed FKs are deliberately introduced with synthetic fixture updates after creating a valid record; no production integrity behavior changed.
- `test_individual_csv_or_on_every_dimension`: seven CSV dimensions, exact IDs and bucket counts, contrasting single selection. `assert_bucket_parity` checks against explicit expected list IDs and independently counted canonical FKs, not just equal totals.
- `test_inherited_filters_exact_bucket_parity`: generic/computing status (latest beats earlier status), active versus ended assignment, owner, inclusive-after/exclusive-before dates and their conjunction. `test_category_subtype_filter_bucket_parity`: populated display size filter with an excluded sibling. `test_maximum_page_size_duplicate_names_and_links`: maximum 100, duplicate type names ordered by ID, next/previous links preserve dimension/search/page_size and resolve to correct rows.
- Regenerated artifacts changed by this continuation: `openapi/labs-equipment.yml`, `openapi/components.yml`, `openapi/openapi-full.json`, `openapi/api-catalog.json`. Isolated generator comparison found only these four differences; other current dirty artifacts were byte-identical and retained. No URL edits or unrelated whole-file formatting.

### Exact latest gate commands and outputs
All commands run at repository root with project Python. PostgreSQL tests use an isolated test DB because the reused shared test DB initially had a duplicate constraint and recreation was blocked by another connection. No other connection was terminated. The explicit in-process override below changes only the test DB name, never connection credentials.

**Focused — passed:**
`.\.venv\Scripts\python.exe -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.test'; from django.conf import settings; settings.DATABASES['default']['TEST']={'NAME':'test_labmango_facets_review'}; import pytest; raise SystemExit(pytest.main(['core/labs/features/equipment/tests/api/test_inventory_facets.py','-q','--reuse-db','-p','no:sugar','--tb=short']))"`
Output: `70 passed in 16.44s`; no skipped/xfail cases.

**Wider equipment + shared filters/transport + architecture — failed (pre-existing only):**
`.\.venv\Scripts\python.exe -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.test'; from django.conf import settings; settings.DATABASES['default']['TEST']={'NAME':'test_labmango_facets_review'}; import pytest; raise SystemExit(pytest.main(['core/labs/features/equipment/tests','core/labs/features/base/tests/test_resource_filters.py','tests/architecture','tests/unit/test_api_transport.py','-q','--reuse-db','-p','no:sugar','--tb=short']))"`
Output: `2 failed, 385 passed in 30.63s`; no skipped/xfail cases. Both failures are `test_status_change_notifies_after_commit` and `test_repeating_offline_status_does_not_emit_another_status_notification`, missing `core.labs.signals`. Independent QA verified both on unchanged HEAD before this continuation (requester-provided evidence). This run reproduced the same failures; `git diff --numstat -- core/labs/features/equipment/tests/categories/computing/test_computing_activity_application.py` produced no output. That file was not modified. This is the full equipment suite plus related checks, **not the full repository suite**.

| Check | Exact command | Latest output/result |
|---|---|---|
| Lint | `.\.venv\Scripts\python.exe -m ruff check core/common/api/api_views.py core/labs/features/equipment/api/facets.py core/labs/features/equipment/tests/api/test_inventory_facets.py` | passed: All checks passed! |
| New-module format | `.\.venv\Scripts\python.exe -m ruff format --check core/labs/features/equipment/api/facets.py core/labs/features/equipment/queries/facets.py core/labs/features/equipment/tests/api/test_inventory_facets.py` | passed: 3 files already formatted |
| Shared-module format inspection | `.\.venv\Scripts\python.exe -m ruff format --diff core/common/api/api_views.py core/labs/features/equipment/api/facets.py core/labs/features/equipment/tests/api/test_inventory_facets.py` | failed at inspection: pre-existing shared-module formatting remains; changed conversion hunk has no formatter diff. Initial test formatting was subsequently corrected. No unrelated shared/URL reformat applied |
| Types | `.\.venv\Scripts\python.exe -m mypy core/common/api/api_views.py core/labs/features/equipment/api/facets.py core/labs/features/equipment/tests/api/test_inventory_facets.py` | failed: Found 157 errors in 45 files (checked 3 source files); zero diagnostics in facet adapter/tests after fixing initial new diagnostics; transitive/shared backlog remains |
| Isolated regeneration | `.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir build/equipment-facets-review-openapi --no-clean --settings=config.settings.test` | passed: 25 modules plus master/components/full JSON/catalog generated |
| Regeneration | `.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi --no-clean --settings=config.settings.test` | passed: 25 modules plus master/components/full JSON/catalog generated; existing enum naming warning |
| Bundle | `npx --yes @redocly/cli@1.34.21 bundle openapi/openapi.yml -o build/equipment-facets-bundled.yml` | passed: Created a bundle, 1026ms |
| Spectral | `npx --yes @stoplight/spectral-cli@6.17.0 lint build/equipment-facets-bundled.yml --ruleset .spectral.yaml --fail-severity=error` | failed: 1399 problems (11 errors, 1388 warnings, 0 infos, 0 hints); same existing ProblemDetail, expense/procurement types/timestamps and admin default/example issues |
| Django | `.\.venv\Scripts\python.exe manage.py check --settings=config.settings.test` | passed: System check identified no issues (0 silenced) |
| Whitespace | `git diff --check -- core/common/api/api_views.py core/labs/features/equipment openapi` | passed: no output |

Initial regression run: schema failed on missing page; DB cases had 4 setup errors from the reused duplicate constraint, so oversized runtime reproduction was initially blocked (not a claimed observed 500). A recreation attempt had 37 passed/11 setup errors from an occupied test database. Isolated runs exposed synthetic fixture mistakes (catalog registration, nonexistent status enum, save-time cross-FK validation), corrected without modifying production models. One attempted wider command referenced nonexistent `tests/unit/test_api_contract_views.py`: no tests ran; corrected to the verified transport test path. No flaky-test retries or gate weakening.

### API classification, drift and remaining limits
Pagination/schema fixes document existing normal behavior, not a new default or maximum. The 1000-character pagination guard rejects pathological previously accepted inputs and therefore is **tighter validation under VER-2**; it is explicitly requested in this authorized continuation. Human approval before merge remains required. No new migrations/dependencies/permission changes; rollback reverts adapter/shared-conversion changes and regenerates schemas, no data rollback. Query budget remains two SQL reads for valid facets; writes/race guards/idempotency are not applicable to these GET operations.

DOC-1, QRY-8/12, COL-1/2/4/5 and ERR-1: covered by runtime/schema regressions. DOC-2 authentication alternatives: fixed for all facets only. Wider auth-schema drift: `openapi/openapi-full.json` generic equipment list has only jwtAuth/cookieAuth although its runtime permission accepts API keys; facets now have the additional equipmentFacetsApiKey alternative. Shared ProjectAutoSchema does not infer API-key permissions; broader repair is intentionally out of scope. No change to target object-scoped visibility drift or global read policy.

Independent QA baseline evidence does not replace final independent review. Full repository tests, exhaustive subtype/filter Cartesian combinations, representative-volume EXPLAIN/latency, >10k-bucket behavior, and deployment check are **not run**. No model/settings/auth middleware changes; migration gate is not applicable. Pylance-specific runtime/type tools are unavailable; editor-selected interpreter is not verified. Unconfigured security/import/breaking-diff gates remain not run as in the historical table.

## Exact changes
- `api/resource_filters.py`: optional CSV department_id/product_model_id on equipment_filter_spec only; existing names unchanged.
- `queries/facets.py` (new): frozen explicit RelationshipDimension configuration, dependency descriptions, membership subquery and SQL distinct equipment aggregation.
- `api/facets.py` (new): required dimension allowlist; list membership/search composition without ordering; standard paginated bucket serializer; explicit HasAPIKey | IsAuthenticated; all query validation failures normalize to invalid_query.
- `api/categories.py`: declaratively generate facet adapters using each category list's actual provider/spec, schema, registration and route.
- `api/urls.py`: generic equipment/facets route.
- `tests/api/test_inventory_facets.py` (new): 43 parameterized regression cases.
- `docs/inventory-facets-task.md` (new): authorized T2 brief/design and frontend contract.
- `docs/architecture.md`: equipment facet ownership, dependencies and semantics.
- Regenerated `openapi/labs-equipment.yml`, `components.yml`, `openapi.yml`, `openapi-full.json`, `api-catalog.json`. Isolated regeneration comparison identified only these five changed artifacts before generating into openapi; other dirty feature artifacts were byte-identical to generator output.

Recent edits to `queries/equipment.py` and `tests/api/test_equipment_options.py` were read but not modified. No unrelated dirty source was overwritten.

## Behavior and API impact
New GET `/api/labs/equipment/facets` and `/api/labs/equipment/{category}/facets` for every existing category. Required dimension: category, kind, type, manufacturer, product_model_id, department_id, group_id. Same list membership/search filters, AND between filters / OR inside CSV; includes own-dimension selection. No include_ids, client ordering, ORM paths, catalog-active eligibility, or zero-count catalog values.

Buckets: `{value: {id, name} | null, equipment_count}` in project collection envelope. Pagination counts buckets, not equipment. Name/ID order, null last; default page size 25, max 100. Complete pre-pagination inventory determines distinct counts. Retired references remain visible. All existing metadata payload shapes remain unchanged; dependency configuration is documented rather than exposed as new response keys. Frontend must send **all selections and search with every dimension request**.

VER-2 / CMP-1: new routes and optional equipment filters are non-breaking. No existing parameter/default/status/payload removal or renaming. Rollback removes additive endpoints/filters and regenerates schema; no database rollback. Race guards and idempotency for writes: not applicable, GET-only.

## Acceptance evidence and mutation sensitivity
| Criterion | Tests | Change that would break tests |
|---|---|---|
| Taxonomy/organization dependencies, conjunctive selections, CSV OR | test_taxonomy_and_organization_dependencies | Ignore an applied filter, omit own dimension filter, or replace IN with equality |
| Distinct counts before equipment pagination | test_counts_match_filtered_inventory, test_category_m2m_search_is_distinct | Aggregate a paginated queryset or count joined search rows |
| Null, retired, deleted, unknown IDs, bucket pagination | test_null_retired_buckets_pagination_and_unknown_ids | Add active-only predicate, remove deletion exclusion, remove null-last ordering or paginate inventory |
| Strict dimension/query/CSV validation | test_invalid_queries, test_repeated_parameters_and_search_parity | Allow arbitrary paths, ordering/include_ids, duplicate/blank CSV, or repeated query keys |
| Generic/category search parity | test_repeated_parameters_and_search_parity, test_category_m2m_search_is_distinct | Use generic search fields for category facets or omit search |
| Every generated category route | test_every_category_generates_facets (12 categories) | Remove builder route/provider registration |
| Authentication parity | test_authorization | Remove permission requirement or reject valid API-key reads |
| Bounded SQL reads | test_bounded_queries (generic/computing) | Add per-bucket queries or serialize unloaded ORM relations |

Read authorization matrix: anonymous/revoked API key denied; authenticated user and valid API key allowed. Existing global read population is preserved, not newly object-scoped. Budget: two SQL queries (bucket count and page) after warm-up. At least three related inventory records created in budget fixture. No write/concurrency/retry/dependency-failure scenarios apply; representative-volume execution plans and exhaustive inherited status/date/assignment filter combinations were not run.

## Gate evidence
Commands below run from repository root. Changed Python paths means these six literal paths: `core/labs/features/equipment/api/facets.py core/labs/features/equipment/api/resource_filters.py core/labs/features/equipment/api/categories.py core/labs/features/equipment/api/urls.py core/labs/features/equipment/queries/facets.py core/labs/features/equipment/tests/api/test_inventory_facets.py`.

| Check | Exact command | Result |
|---|---|---|
| Python runtime | `.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version); import django, pytest; print('Django', django.get_version())"` | passed: project Python 3.12.12, Django 5.2.13; editor-selected interpreter not verified (configuration tool unavailable) |
| Facets | `.\.venv\Scripts\python.exe -m pytest core/labs/features/equipment/tests/api/test_inventory_facets.py -q --reuse-db -p no:sugar` | passed: 43; initial fixture-required definition error corrected |
| API compatibility | `.\.venv\Scripts\python.exe -m pytest core/labs/features/equipment/tests/api/test_inventory_facets.py core/labs/features/equipment/tests/api/test_equipment_options.py core/labs/features/equipment/tests/api/test_category_contracts.py -q --reuse-db -p no:sugar --tb=short` | passed: 170 |
| Full equipment | `.\.venv\Scripts\python.exe -m pytest core/labs/features/equipment/tests -q --reuse-db -p no:sugar --tb=short` | failed: 289 passed / 2 failed; pre-existing computing tests monkeypatch missing core.labs.signals; untouched |
| Architecture | `.\.venv\Scripts\python.exe -m pytest tests/architecture -q --reuse-db -p no:sugar --tb=short` | passed: 36 |
| Ruff lint | `.\.venv\Scripts\python.exe -m ruff check` followed by the six literal changed Python paths above | passed |
| Ruff format | `.\.venv\Scripts\python.exe -m ruff format --check` followed by the six literal changed Python paths above | failed: only pre-existing formatting in api/urls.py; five other files formatted; no unrelated reformat applied |
| mypy | `.\.venv\Scripts\python.exe -m mypy` followed by the six literal changed Python paths above | failed: 157 diagnostics in 45 files; no remaining diagnostics in new facet query, adapter, or test modules; inherited/transitive backlog untouched |
| Schema regenerate | `.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi --no-clean --settings=config.settings.test` | passed; isolated build/equipment-facets-openapi generation/comparison performed first |
| Schema bundle | `npx --yes @redocly/cli@1.34.21 bundle openapi/openapi.yml -o build/equipment-facets-bundled.yml` | passed: bundle exists and Spectral parsed it |
| Spectral | `npx --yes @stoplight/spectral-cli@6.17.0 lint build/equipment-facets-bundled.yml --ruleset .spectral.yaml --fail-severity=error` | failed: 11 errors / 1388 warnings; existing ProblemDetail, expense/procurement money/timestamp and schema-example issues; stale media-type warnings contradict current ERR-1 |
| Django | `.\.venv\Scripts\python.exe manage.py check --settings=config.settings.test` | passed: no issues |
| Whitespace | `git diff --check -- core/labs/features/equipment/api/categories.py core/labs/features/equipment/api/resource_filters.py core/labs/features/equipment/api/urls.py core/labs/features/equipment/docs/architecture.md openapi` | passed |
| Editor diagnostics | Changed facet adapter/query/category builder/test files | passed: no errors reported |
| Migrations / deploy check | not run | no models/settings/auth middleware changed |
| Independent review / volume EXPLAIN | not run | no independent reviewer or representative-volume profile available |
| lint-imports, pip-audit, bandit/semgrep, gitleaks, breaking diff | not run | not configured; no tooling added |

No tests skipped or marked xfail in focused runs. No retries of flaky tests; unrelated failures left intact.

## API rule review
| Rule IDs | Status | Fix/qualification |
|---|---|---|
| TRN-4, PTH-5 | pass | slashless generic/generated routes; no aliases |
| ENV-1..4, COL-1..4, COL-8, QRY-1..4/8/12 | pass | collection envelope, strict query errors, bounded standard bucket pagination |
| REL-3/5, NUL-1..3 | pass | fixed nullable id/name reference buckets |
| COL-5, PRF-1..3 | pass | SQL grouped projections, distinct IDs, deterministic fixed ordering, tested two-query budget |
| HTTP-2, WRT-10 | pass | read-only; no writes |
| SEC-1/4/5/13 | pass | explicit existing read permission, no secret/personal facet dimensions, server allowlist |
| SEC-2/15 | violation (existing population) | target object-scoped policy not established; task explicitly preserves current global read population |
| VER-2, CMP-1 | pass | additive routes/optional filters only |
| DOC-1 | pass | regenerated schema |
| DOC-2..4, COL-9 | violation / incomplete evidence | exhaustive schema validation/auth-failure examples and >10k-bucket behavior not verified; standard page style is explicitly approved by task |

## Drift and residual risks
- `api/list_create.py:143`: existing HTTP transaction boundary; not copied by facets.
- `api/common.py:12`: existing ORM SKU lookup in API module; untouched.
- `core/common/api/api_views.py:323`: shared typed query failures use validation_failed; new facets normalize only their own error code to invalid_query.
- Existing api/urls.py formatting, mypy backlog, missing computing signal import and schema lint failures remain outside this task.
- Search uses existing icontains; aggregate cost and response latency on representative PostgreSQL inventory are **not verified**. No new index recommendation is asserted.
- Facets reflect stored relationships exactly like list filters, not catalog eligibility: invalid historical relationships are not silently repaired or suppressed. Retired references intentionally remain visible.
- Specialist Security/QA and independent review plus human approval before merge remain required. No claim of full API/repository compliance or production readiness.