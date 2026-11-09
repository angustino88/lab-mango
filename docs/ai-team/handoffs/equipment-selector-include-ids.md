# Handoff: Equipment selector include_ids safety

**Role**: Backend Engineering · **Tier**: T2 · **Status**: needs decision

## Summary
Equipment option queries preserve the active-equipment queryset when merging `include_ids`. Included IDs bypass ordinary search and parent/status/assignment predicates, but soft-deleted equipment cannot be returned. Large Equipment selectors require `q` or declared parent filters; lifecycle status and assignability remain optional predicates but do not satisfy `required_any`. This tighter validation is a breaking request-contract change and is not approved for release.

## Files and contracts changed
- `core/labs/features/equipment/queries/equipment.py`: constrain generic and category selectors to non-deleted rows and compose included IDs as an OR branch that repeats the active-row predicate.
- `core/labs/features/equipment/api/views.py`: narrow `required_any` for generic and category Equipment selectors to `q` and declared parent filters.
- `core/labs/features/equipment/api/serializers.py`: document on the equipment parent-filter query parameters that a large selector requires `q` or a declared parent filter.
- `core/common/api/options.py`: document selector `400` responses and expose optional operation descriptions to generated OpenAPI.
- `openapi/`: regenerate checked-in schemas and API catalog from the updated serializer and view metadata.
- `core/labs/features/equipment/tests/api/test_equipment_options.py`: cover required narrowing, valid nonmatching inclusion, deleted-ID exclusion, included IDs counting toward the result cap, and bounded generic-selector query count.

## Migrations / API / schema impact
No migrations. The runtime request contract is tighter: large selectors without `q` or a declared parent filter return `400 invalid_query`. VER-2 / CMP-2 classify tighter validation as breaking; ADR 002 D12 calls for a coordinated backend/frontend release. Human approval and a consumer migration plan are pending. Generated OpenAPI now includes selector-level conditional-rule descriptions and `400` responses. Schema generation validates, but Spectral reports existing global errors; see checks below. No ADR change was made.

### API rule table

| Rule ID | Status | Fix or evidence |
| --- | --- | --- |
| OPT-10 | Partial / unresolved | `include_ids` bypasses ordinary filters and counts toward the cap; soft-deleted Equipment is excluded. Caller-specific readability is not established. Resolve policy and add unreadable-ID tests before security sign-off. |
| OPT-11 | Pass in runtime | Large selector `required_any` excludes `include_ids`, lifecycle status, and assignability; requires `q` or a declared parent filter. |
| SEC-2 | Not verified | No actor-/tenant-scoped Equipment read policy was found in the inspected canonical paths; this change does not invent one. |
| COL-4 / ERR-3 | Pass in runtime | Missing required narrowing returns the established `400 invalid_query` response. |
| VER-2 / CMP-2 / CMP-4 | Breaking / approval pending | Coordinate consumer migration and obtain owner approval before release. |
| DOC-1 / DOC-2 | Partial | Generated docs describe the condition and include the runtime `400`; Spectral still fails globally and requires review of its findings. |

## Evidence ledger
| Acceptance criterion | Code | Test | Result (passed / failed / not run) |
|---|---|---|---|
| `include_ids` cannot bypass canonical non-deleted Equipment queryset | Both query functions keep the base queryset active and apply the active predicate in the include branch | `test_include_ids_include_nonmatching_active_but_exclude_soft_deleted` on generic and computing-category routes | Passed |
| Valid active nonmatching IDs still bypass ordinary search | OR-composed include branch | Same parameterized test asserts the active selected ID is returned despite nonmatching `q` | Passed |
| Included IDs count toward the total cap | Shared `OptionsAPIView` applies cap after the combined query; Equipment test lowers cap to one | `test_include_ids_count_toward_selector_result_cap` | Passed |
| Large Equipment `required_any` is only `q` or declared parents | Generic and category view declarations | Existing parameterized large selector test updated | Passed |
| Generic selector query count remains bounded as results grow | Query remains one SQL statement independent of returned result count | `test_equipment_options_query_count_is_bounded_as_results_grow` (1 and 100 results) | Passed: one query at each volume |
| Actor/tenant visibility not invented | No new policy or filtering assumption | Query contract inspected; unresolved scope is documented | Passed as scope control; not a security pass |

## Commands run (exact) and outcomes
- **Passed** — `.\.venv\Scripts\python.exe -m pytest --reuse-db core\labs\features\equipment\tests\api\test_equipment_options.py -q` — 17 passed.
- **Passed** — `.\.venv\Scripts\python.exe -m pytest --reuse-db tests\unit\test_options_base.py -q` — 10 passed.
- **Passed** — `.\.venv\Scripts\python.exe -m pytest --reuse-db core\labs\features\equipment\tests\api\test_equipment_options.py core\labs\features\equipment\tests\queries.py -q` — 20 passed.
- **Passed** — `.\.venv\Scripts\ruff.exe check core\labs\features\equipment\queries\equipment.py core\labs\features\equipment\api\views.py core\labs\features\equipment\api\serializers.py core\labs\features\equipment\tests\api\test_equipment_options.py` — all checks passed.
- **Passed** — `.\.venv\Scripts\ruff.exe format --check core\labs\features\equipment\queries\equipment.py core\labs\features\equipment\api\views.py core\labs\features\equipment\api\serializers.py core\labs\features\equipment\tests\api\test_equipment_options.py` — 4 files already formatted.
- **Passed** — `.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi --no-clean` — generated master schema, components, full schema, API catalog, and 25 modules.
- **Passed** — `.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi --dry-run` — validated 27 OpenAPI documents and full JSON schema; no files written during preview.
- **Failed (pre-existing/global errors)** — `npx --yes @redocly/cli@1.34.21 bundle openapi/openapi.yml -o build/openapi.bundled.yml` followed by `npx --yes @stoplight/spectral-cli@6.17.0 lint build/openapi.bundled.yml --ruleset .spectral.yaml --fail-severity=error` — Spectral reported 7 errors and 1,356 warnings in global schema areas (ProblemDetail, ExpensePayment.paid_at, PurchaseItemRead.unit_price, and admin-code examples); no Equipment-specific error was reported in the review output.
- **Failed (incorrect path, then corrected)** — `.\.venv\Scripts\python.exe -m pytest --reuse-db core\common\tests\api\test_options.py -q` — path does not exist; actual shared test suite is `tests\unit\test_options_base.py`, which passed (above).
- **Passed** — `git diff --check` — no whitespace errors; Git emitted a line-ending warning for the already-dirty `pyproject.toml`.

## Not run, and why
- Mypy: not run; project-wide/transitive baseline is known to have errors.
- Category/subtype selector query-budget coverage: not run; the one-versus-100 assertion covers only the generic Equipment selector.
- Security matrix for caller-scoped/readable `include_ids`: not run; read visibility remains unresolved.
- Full API/equipment suite: not run; only focused options/query suites were run.

## Facts vs assumptions
- **Verified:** ADR 002 says included IDs ignore `q` and parent filters, count toward the result cap, and still require caller readability.
- **Verified:** query functions accept `actor` but no actor-specific or tenant-specific visibility policy was identified in the inspected Equipment selector path.
- **Verified:** OpenAPI regeneration now emits the conditional narrowing text and `400` operation response; Spectral still fails with the global findings above.
- **Unresolved:** actor-/tenant-scoped readability. This change does not invent such a policy; owning policy/security review is needed before claiming scoped visibility.

## Known risks and limitations
- Actor-/tenant-level readability remains unresolved; soft-delete protection alone does not establish caller authorization.
- API Designer review confirmed that the breaking behavior needs owner approval and a coordinated consumer plan before release.
- Independent review confirms the generic query-budget test passes, but requests category/subtype query-budget coverage and flags unreadable-ID visibility as unresolved. Review verdict: request changes; not merge-ready.
- Security review blocks sign-off pending an explicit read-visibility boundary and corresponding negative actor/scope tests.
- QA review recommends query-budget, exact cap-boundary, and more discriminating per-parent filter assertions.
- Unrelated selector functions were not modified.

## Decisions needed from the human owner
1. Confirm the intended Equipment selector actor/tenant visibility policy and owning boundary before security sign-off.
2. Approve or reject the VER-2 breaking narrowing change and agree on the frontend migration/release plan.
3. Confirm the intended read-visibility rule for users and API-key callers; add unreadable-ID and query-budget tests before security/QA sign-off.
4. Resolve the global Spectral errors and complete API schema lint before release.
