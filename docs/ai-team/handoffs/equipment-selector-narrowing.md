# Handoff: Equipment selector narrowing

**Role**: Backend Engineering · **Tier**: T2 · **Status**: blocked

## Summary
Implemented an initial Equipment large-selector narrowing pilot. Large selectors now require at least one configured `required_any` value; `include_ids` alone no longer satisfies that requirement. Equipment, subtype equipment, type, manufacturer, and product-model selectors have declarative per-view allowlists. This tightens an existing public contract and is not ready for release or merge.

No true result-set facets or `/facets` endpoint were implemented; this remains separate from the all-feature faceted-filtering plan.

## Files and contracts changed
- `core/common/api/options.py`: removed the `include_ids` exception from the shared large-selector check.
- `core/labs/features/equipment/api/views.py`: declared `required_any` for large Equipment selectors.
- `core/labs/features/equipment/tests/api/test_equipment_options.py`: added parameterized missing-filter and request acceptance tests plus some exact parent-filter result assertions.
- `openapi/api-catalog.json`: only generated date changed; this is unrelated generated churn and should be reverted or regenerated with the actual API documentation change.

## Migrations / API / schema impact
No migration. Existing requests without one of the newly required query filters now return `400 invalid_query` across large equipment, equipment subtype, type, manufacturer, and product-model selector routes. This is breaking under VER-2. Coordinate backend/frontend release and obtain human approval before merge/release. `lifecycle_status` and `assignable` currently qualify, although ADR 002 says `q` or a declared parent filter; owner confirmation/documentation is needed.

OpenAPI generation completed, but endpoint-spec YAML artifacts did not change. The conditional `required_any` rule is not represented in the current schema. Spectral failed against the full schema; details below.

## Evidence ledger
| Acceptance criterion | Code | Test | Result |
|---|---|---|---|
| Large selectors reject requests with no configured narrowing | Shared gate in `core/common/api/options.py`; declarations in Equipment views | Parameterized request checks | **Passed** for tested routes |
| `include_ids` alone does not satisfy narrowing | Shared gate excludes `include_ids` | Absent ID alone returns 400 | **Passed** for that case; valid-ID behavior remains uncovered |
| Declared parameters are accepted | Per-view `required_any` | Parameterized 200 checks, some exact parent results | **Partial**; status/assignable predicate effectiveness isn't asserted |
| Valid readable retired IDs are handled safely | Existing Equipment query OR behavior | No valid-ID/deleted/unreadable ID tests | **Not run / uncovered** |
| Cap behavior remains correct including IDs | Shared options cap logic | No changed-feature boundary test | **Not run / uncovered** |
| Query budget remains bounded | Query implementations | No PRF-2 assertion | **Not run / uncovered** |
| OpenAPI describes the contract | Generated schema | Selector endpoint spec unchanged | **Failed/incomplete** |

## Commands run and outcomes
- **Passed** — `.venv\Scripts\python.exe -m pytest --reuse-db core\labs\features\equipment\tests\api\test_equipment_options.py -q` — 14 passed.
- **Passed** — `.venv\Scripts\python.exe -m pytest --reuse-db tests\unit\test_options_base.py -q` — 10 passed.
- **Passed** — `.venv\Scripts\python.exe -m ruff check core\common\api\options.py core\labs\features\equipment\api\views.py core\labs\features\equipment\tests\api\test_equipment_options.py` — all checks passed.
- **Passed** — `.venv\Scripts\python.exe -m ruff format --check core\common\api\options.py core\labs\features\equipment\api\views.py core\labs\features\equipment\tests\api\test_equipment_options.py` — all 3 files formatted.
- **Passed** — `git diff --check` — clean at time run.
- **Passed** — VS Code diagnostics reported no errors in the three changed Python files.
- **Failed** — `.venv\Scripts\python.exe -m mypy core/common/api/options.py core/labs/features/equipment/api/views.py core/labs/features/equipment/tests/api/test_equipment_options.py` — 112 errors across 37 files; no baseline comparison was available and errors include changed paths.
- **Passed** — `.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi` — completed, but endpoint specifications were unchanged apart from generated catalog date.
- **Failed** — Redocly bundle then Spectral lint per API instructions — 1363 findings (7 errors, 1356 warnings). Errors include ProblemDetail structure, ExpensePayment.paid_at format, PurchaseItemRead.unit_price type, and three admin-code examples. No error was shown to be introduced by this selector change.
- **Failed (test DB setup)** — `DJANGO_SETTINGS_MODULE=config.settings.test .\.venv\Scripts\python.exe -m pytest --reuse-db core\labs\features\equipment\tests\api\test_equipment_options.py tests\unit\test_options_base.py -q` — duplicate `btree_gist` extension creation. Running each suite separately succeeded.
- **Not run** — full equipment suite, architecture tests, OpenAPI breaking-change diff, frontend compatibility tests, or production verification. Migration and deploy checks were not applicable (no models/settings/auth changes).

## Facts vs assumptions
- **Verified:** the shared `required_any` check no longer accepts `include_ids` as the required value.
- **Verified:** ADR 002 says large selectors require `q` or a declared parent filter; readable `include_ids` may ignore `q`/parent filters and still count toward cap.
- **Verified:** Equipment query functions OR `pk__in=include_ids` with ordinary predicates. They accept `actor` but do not use it; included soft-deleted rows may therefore bypass the normal soft-delete predicate.
- **Not verified:** intended actor-/tenant-level selector visibility, and whether lifecycle state/assignability are approved narrowing conditions.
- **Not verified:** any other documentation surface communicates the conditional narrowing requirement.

## Known risks and limitations
- **High security blocker:** security review found that `include_ids` can bypass soft-delete filtering and actor scope is unverified. No security sign-off is possible until authorization/readability is enforced and tested.
- **High contract blocker:** a qualifying filter plus `include_ids` can return included rows that ignore that filter. This is consistent with ADR 002 semantics only when readability is established; verify visibility and cap behavior.
- **High QA blocker:** missing valid include-ID, cap boundary and query-count tests; status/assignable filter effects are incompletely asserted.
- **High API-doc blocker:** OpenAPI artifacts do not communicate the new required-filter condition. Full schema lint fails.
- **Breaking change:** coordinate frontend/backend release and obtain human approval; this is not merge-ready.
- Independent reviewer: request changes. API Designer: blocked pending contract correction and owner confirmation. QA: not release-acceptable. Security: blocked.

## Decisions needed from the human owner
1. Confirm whether lifecycle status and assignability qualify as narrowing, or limit eligibility to `q` and declared parent filters per ADR 002.
2. Confirm the breaking validation change belongs in a coordinated backend/frontend release and approve the migration plan.
3. Resolve actor-scoped readability and soft-deleted `include_ids` behavior before security sign-off.
4. Decide/document how the conditional requirement will be represented in OpenAPI and regenerate the applicable artifacts.
5. Establish whether the pre-existing full-schema Spectral errors must be cleared for this change or tracked separately.
