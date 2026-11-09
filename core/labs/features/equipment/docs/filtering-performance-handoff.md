# Handoff: bounded filtering performance

**Role**: Backend Engineer / QA evidence followup · **Tier**: T1 · **Status**: QA code approve; verification hold.
Date: 2026-11-08. User authorized implementation. No production measurement or deployment.

## QA evidence followup (observed 2026-11-08)

This followup changes documentation and adds a QA-only launcher/raw logs below; **no production hunks
or regression tests changed**. Earlier implementation/benchmark results below remain **author-reported**
unless explicitly reproduced here. The original 589-item node-ID manifest/raw summary was not found
in the available repository or local terminal/session artifacts; do not present it as independently observed.

### Disposition and independence

- **Independent review: scoped APPROVE**, recorded as the disposition requested by the user for the
  three performance hunks only. No separate reviewer transcript or independent agent execution was
  available to this followup; this is **not** a newly performed independent review. Unrelated dirty
  changes are excluded; human owner must retain the independent review evidence before merge.
- **QA: code APPROVE; verification HOLD.** This followup observed the focused regression coverage
  and reviewed conditional DISTINCT, scalar/forward-join generic cardinality, and PK-IN facet membership.
  No attributable new blocker found in those hunks. Four broader failures and the failed type gate
  remain unresolved; code approval is not a green verification gate or merge/release approval.
- The reviewer and QA evidence are scoped, not an approval of the entire dirty workspace.

### Completed commands and exact raw summaries

From repository root, each command is
`.\.venv\Scripts\python.exe core/labs/features/equipment/docs/filtering-performance-qa/run_evidence.py MODE`.
[Launcher](filtering-performance-qa/run_evidence.py) pins the same five wider directories/four focused
files listed in the earlier commands, records combined stdout/stderr and exit code, and passes only
OS process necessities plus explicitly synthetic settings to children. No environment enumeration,
dotenv/credential-file read, production connection or production change. Normal test discovery excludes
the opt-in measurement helper; existing before/after benchmark JSON was not regenerated.

| MODE / gate | Observed raw final summary | Exit | Evidence |
| --- | --- | ---: | --- |
| collect / passed | `590 tests collected in 1.47s` | 0 | [node-ID manifest](filtering-performance-qa/collect.log) |
| focused / passed | `139 passed in 108.77s (0:01:48)` | 0 | [focused raw log](filtering-performance-qa/focused.log) |
| wider / failed | `4 failed, 586 passed in 78.78s (0:01:18)` | 1 | [wider raw log](filtering-performance-qa/wider.log) |
| tickets-current / failed | `2 failed in 5.11s` | 1 | [current ticket raw log](filtering-performance-qa/tickets-current.log) |
| tickets-replay / failed | `2 failed in 4.57s` | 1 | [shared-hunk replay raw log](filtering-performance-qa/tickets-replay.log) |
| types / failed | `Found 90 errors in 27 files (checked 6 source files)` | 1 | [type raw log](filtering-performance-qa/types.log) |
| collect-without-ticket / passed diagnostic only | `589/590 tests collected (1 deselected) in 1.50s` | 0 | [diagnostic node-ID manifest](filtering-performance-qa/collect-without-ticket.log) |

No skipped/xfail cases in the completed focused/wider runs. The one diagnostic deselection is **not**
a weakened test gate: the actual wider run ran all 590 items. `types` checks the original six-path
performance scope without narrowing imports; it is **failed**, not green. The new standalone launcher
has separate lint/format/type checks; they do not supersede that failure.

Followup-only static checks (repository root; final outcomes observed):

- **passed**: `.\.venv\Scripts\python.exe -m ruff check core/labs/features/equipment/docs/filtering-performance-qa/run_evidence.py`
  → `All checks passed!` (initial run failed import spacing/final newline, corrected only in launcher).
- **passed**: `.\.venv\Scripts\python.exe -m ruff format --check core/labs/features/equipment/docs/filtering-performance-qa/run_evidence.py`
  → `1 file already formatted` (initial run required formatting).
- **passed, launcher only**: `.\.venv\Scripts\python.exe -m mypy --follow-imports=skip core/labs/features/equipment/docs/filtering-performance-qa/run_evidence.py`
  → `Success: no issues found in 1 source file`. Not the six-path performance type gate.
- **passed**: `git diff --check -- core/labs/features/equipment/docs/filtering-performance-handoff.md core/labs/features/equipment/docs/filtering-performance-qa`
  → no output, exit 0. Editor diagnostics: no errors in the launcher.
- **not run**: new timing measurements, deploy/migration/schema/security gates (no production changes).

### Collection reconciliation: 589 reported → 590 observed

The current manifest includes the singleton
[ticket cardinality regression](../../../../support_desk/tests/test_filtering_performance.py),
`test_ticket_distinct_is_conditional_and_reverse_links_are_unique`. Excluding precisely that item
leaves 589 selected; all other current node IDs match between the two new manifests. This is the
concrete +1 candidate, consistent with the previous handoff's chronology (wider run before final
ticket-inclusive focused run). The earlier handoff's `585 passed/4 failed` totals 589; now the same
four named failures plus 586 passes total 590. **Historical exact identity is not verified without
the original manifest**: arithmetic and current diagnostic collection cannot prove there were no
offsetting workspace/parameterization changes. No historical full-suite baseline was reconstructed.

### Ticket replay: precise inference, not a full baseline

The launcher retrieves `FilterSpec.apply`, asserts exactly one matching accumulation line, parses
the replacement, and replaces only that method **in memory in a fresh process**. It restores the
old unconditional filter-DISTINCT accumulation, not generic-list DISTINCT, facet DISTINCT counting,
all three performance hunks, or any unrelated dirty workspace change. Source files remain untouched.
Both current and replay logs show:

- [test_ticket_list_filtering](../../../../support_desk/tests/test_api.py#L50): `assert 400 == 200`.
- [test_requester_cannot_list_or_read_foreign_tickets](../../../../support_desk/tests/test_api_helpdesk.py#L26):
  `KeyError: 'data'`, with a logged Bad Request for the list request.

Thus those failures also occur with old shared accumulation **in the current workspace**; they are
not explained solely by this shared performance hunk. Root cause remains not verified. Do not infer
that the entire pre-patch workspace failed identically. The wider log also reproduces the two stale
`core.labs.signals` monkeypatch import failures; neither was repaired. The replay emitted a warning
for the explicitly empty synthetic prod alias; no invalid logging-handle failure in this new replay.

### Isolated setup and cleanup (passed)

Used the prior documented PostgreSQL 18 setup: fresh temporary directory prefixed
`labmango-filtering-qa-`, `initdb -U filtering_test_actor --auth=trust --encoding=UTF8 --locale=C`,
then `pg_ctl -l <temporary server.log> -o '-h 127.0.0.1 -p 55439' -w start`.
Observed `server started`; focused pytest created/used its synthetic test database.
After the runs: `pg_ctl -D $qaCluster -m fast -w stop`, then guarded
`Remove-Item -LiteralPath $qaCluster -Recurse -Force` only for that newly owned temporary directory.
Observed stop success and `Synthetic cluster directory absent: True`. Existing running Django server
and other clusters/resources were not changed. No production credentials/settings were printed.

Remaining holds: obtain attributable independent-review evidence; owner resolution/acceptance of
broader failures and the type backlog; no new claim about production speedup or complete baseline.

## Summary / files and contracts
- [Shared filter](../../../../common/api/filtering.py): accumulate DISTINCT inside the supplied-filter branch only.
  False is still supplied; separate filter calls, ordering, search DISTINCT and incoming DISTINCT are unchanged.
- [Generic selector](../queries/equipment.py): return the forward-FK/scalar-annotation queryset without unconditional DISTINCT.
  Existing dirty imports, mapping/assignment logic and select_related changes were retained.
- [Facet selector](../queries/facets.py): Count(pk), retaining PK-IN membership and outer deletion guard.
  Existing untracked facet implementation was retained, not replaced.
- [Shared tests](../../../../common/tests/test_filtering.py), [equipment tests](../tests/test_filtering_performance.py),
  [ticket tests](../../../../support_desk/tests/test_filtering_performance.py).
- [Brief](filtering-performance-task.md), this handoff, [before SQL/plans](filtering-performance-before.json),
  [after SQL/plans](filtering-performance-after.json).

No migrations (rollback: revert only the three task-owned production hunks), model changes, dependencies,
schemas, routes, permissions or defaults. No new business dependency edge. No write paths in production.
Synthetic test fixtures use existing ORM/bulk_create patterns only in rollback-isolated tests.

## Evidence ledger
| Criterion | Evidence / test | Result | Mutation that would fail |
|---|---|---|---|
| Conditional DISTINCT and false | test_distinct_only_for_supplied_filter; test_search_distinct_only_for_nonempty_search | passed | hoist accumulation / remove search distinct |
| Reverse/M2M duplicates and incoming DISTINCT | test_reverse_filter_search_and_previous_distinct; test_m2m_filter_and_separate_reverse_filter_calls | passed | drop distinct / combine filter calls |
| Generic scalar projection and pagination parity | test_generic_list_count_page_annotation_parity (9 cases); test_generic_list_does_not_request_distinct | passed | add multiplying outer join / restore DISTINCT |
| Latest history, false assignment, reference filters | test_latest_history_and_false_assignment_membership | passed | use history joins or lose False predicate |
| Seven dimensions single-valued | test_all_dimension_paths_are_single_valued (includes rejecting real reverse path) | passed | register reverse/M2M dimension |
| Membership duplicates, null/deleted/retired | test_facet_membership_isolation (7 × 3); existing inventory facet API suite | passed | remove membership isolation or deletion guard |
| Ticket consumer | test_ticket_distinct_is_conditional_and_reverse_links_are_unique | passed | unconditional or missing reverse DISTINCT |
| SQL/count/page parity and timings | measure_synthetic_explain_capture; 13 captured cases and stable ordered page keys compared | passed | paginator cardinality/page changes |

Facet query budget: one selector SQL; unchanged API suite asserts two paginator SQLs. Generic list projection:
one bounded page SQL (count measured separately); no serializer query-budget claims. Existing API tests cover search aliases,
retired/null buckets, permissions and CSV validation. Write concurrency/idempotency/dependency failure cases do not apply
to these read-only changes; no new permission behavior requiring a new matrix.

## Measurements (milliseconds; PostgreSQL 18, Python 3.12.12, Django 5.2.13)

New temporary loopback-only trust-auth cluster, port 55439, test_filtering_perf; no dotenv or credential file read.
1,603 equipment rows (1,602 visible, one deleted), 1,600 bulk-created inventory rows, two status histories for each bulk row,
three matching interfaces on one display, three historical and one active bench assignment. Nullable references in one quarter
of bulk rows; retired manufacturer/department/group. 80 repeated synthetic inventory names; single kind/category.
ANALYZE after setup. Actual ResultsSetPagination count and LIMIT 25 page SQL captured, not reconstructed SQL.
One warm-up and seven measured count/page EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) executions per case.
Before and after are sequential runs, not interleaved A/B; medians are execution times, not end-to-end HTTP latencies.
JSON contains SQL, all seven timing samples, count, numeric IDs, stable page keys, final full plans and buffer metrics.
Numeric IDs vary across transactional runs; comparison uses synthetic SKUs/facet names and counts.

| Case | Count before → after | Page before → after |
|---|---:|---:|
| Generic | 21.158 → 0.370 | 40.237 → 12.095 |
| Generic search | 31.790 → 2.313 | 118.022 → 44.609 |
| Generic latest status | 27.061 → 4.096 | 64.499 → 22.358 |
| Generic assigned=false | 23.666 → 0.512 | 41.004 → 12.170 |
| Shared absent multiplying filter | 2.965 → 0.273 | 0.125 → 0.036 |
| Facet category | 1.983 → 0.850 | 2.380 → 0.851 |
| Facet kind | 2.034 → 0.862 | 2.478 → 0.871 |
| Facet type | 2.061 → 1.588 | 3.590 → 1.689 |
| Facet manufacturer | 2.073 → 1.654 | 3.620 → 1.759 |
| Facet product_model_id | 2.446 → 1.514 | 4.854 → 1.501 |
| Facet department_id | 2.341 → 1.525 | 4.085 → 1.606 |
| Facet group_id | 2.243 → 1.879 | 4.054 → 2.052 |
| Facet M2M population (one display) | 0.124 → 0.124 | 0.117 → 0.135 |

Observed generic count reduction 98.3%; page reduction 69.9%. The small M2M page regressed 0.018 ms (15.4%);
count unchanged. Do not claim universal improvement. Facet measurements combine membership-list DISTINCT removal
and aggregate DISTINCT removal; they do not isolate each optimization's contribution.
Final-plan generic count shared-buffer hits: 9,658 → 38; page: 9,665 → 198. Shared absent count: 38 → 38;
manufacturer facets: 77 → 77; M2M facets: 19 → 19. All these plans have zero shared reads: warm cache, not storage testing.
Before generic count SQL wraps a wide SELECT DISTINCT including scalar annotations; after uses direct COUNT(*).
Before page deduplicates the wide projection; after retains FK joins/subqueries and LIMIT without DISTINCT.
Facet SQL retains IN (SELECT population PK), and replaces COUNT(DISTINCT outer PK) with COUNT(outer PK).

## Exact commands / outcomes

All commands from repository root, using the venv. Shell process configured only with explicit synthetic/local values;
no environment enumeration, env-file read, container environment inspection or credential output.

### Setup (passed)
```powershell
Get-Location; git status --short; .\.venv\Scripts\python.exe --version
Get-Command docker, psql, postgres, initdb -ErrorAction SilentlyContinue | Select-Object Name, Source; if (Get-Command docker -ErrorAction SilentlyContinue) { docker ps --format '{{.Names}} {{.Image}} {{.Ports}}' }; Get-ChildItem 'C:\Program Files\PostgreSQL' -ErrorAction SilentlyContinue | Select-Object Name
$perfCluster = Join-Path ([System.IO.Path]::GetTempPath()) ('labmango-filtering-' + [guid]::NewGuid().ToString('N')); & 'C:\Program Files\PostgreSQL\18\bin\initdb.exe' -D $perfCluster -U filtering_test_actor --auth=trust --encoding=UTF8 --locale=C; if ($LASTEXITCODE -eq 0) { & 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D $perfCluster -l (Join-Path $perfCluster 'server.log') -o '-h 127.0.0.1 -p 55439' -w start }; $env:DJANGO_READ_DOT_ENV_FILE='False'; $env:DATABASE_URL='postgres://filtering_test_actor@127.0.0.1:55439/filtering_perf'; $env:PROD_DATABASE_URL=''; $env:DJANGO_SETTINGS_MODULE='config.settings.test'; $env:PGPASSFILE=Join-Path $perfCluster 'no-password-file'; $env:PGSERVICEFILE=Join-Path $perfCluster 'no-service-file'
$env:CELERY_BROKER_URL='memory://'
```
Trust authentication has no password; loopback address is enforced by postgres startup. Temporary cluster is stopped at handoff;
temporary files are retained for owner cleanup (not production resources).

Cleanup command: `& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D $perfCluster -m fast -w stop`.

### Test commands
```powershell
.\.venv\Scripts\python.exe -m pytest core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py --reuse-db -q -s
.\.venv\Scripts\python.exe -m pytest core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py --reuse-db -q -s --tb=short
.\.venv\Scripts\python.exe -m pytest core/labs/features/equipment/tests/test_filtering_performance.py -k 'synthetic_explain_capture or generic_list_count_page_annotation_parity or all_dimension_paths' --reuse-db -q -s --tb=short -p no:sugar
.\.venv\Scripts\python.exe -m pytest core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py --reuse-db -q -s --tb=line -p no:sugar -o 'python_functions=test_* measure_*'
.\.venv\Scripts\python.exe -m pytest core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py --reuse-db -q -s --tb=short -p no:sugar -o 'python_functions=test_* measure_*'
.\.venv\Scripts\python.exe -m pytest core/common/tests core/labs/features/base/tests core/labs/features/equipment/tests core/support_desk/tests tests/architecture --reuse-db -q --tb=line -p no:sugar
.\.venv\Scripts\python.exe -m pytest core/support_desk/tests/test_api.py::TestTicketAPIEndpoints::test_ticket_list_filtering core/support_desk/tests/test_api_helpdesk.py::TestTicketScopingAPI::test_requester_cannot_list_or_read_foreign_tickets --reuse-db -q --tb=short -p no:sugar
.\.venv\Scripts\python.exe -m pytest core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py core/labs/features/equipment/tests/api/test_inventory_facets.py core/support_desk/tests/test_filtering_performance.py --reuse-db -q --tb=short -p no:sugar
```
In order: startup failed (missing CELERY_BROKER_URL); fixture failures (maker not registered); baseline selector command
first failed retired maker validation, then 10 passed/1 failed (pre-existing unsupported kind key); corrected red baseline
24 failed/44 passed (intentional DISTINCT regression assertions); after measurement 68 passed; wider 585 passed/4 failed;
isolated tickets 2 failed; final focused 139 passed. No skipped/xfail cases. Fixture issues corrected before production changes.
The final measurement helper is opt-in (`-o 'python_functions=test_* measure_*'` plus `-k measure_synthetic_explain_capture`)
so normal suites do not write benchmark artifacts or require the dedicated port.

Ticket baseline replay (failed, same two failures; old accumulation restored in memory only, no source file modification):
```powershell
.\.venv\Scripts\python.exe -c "import django; django.setup(); import inspect,textwrap,pytest; import core.common.api.filtering as m; source=textwrap.dedent(inspect.getsource(m.FilterSpec.apply)).replace('        needs_distinct = needs_distinct or item.distinct','    needs_distinct = needs_distinct or item.distinct'); scope={}; exec(source,m.__dict__,scope); m.FilterSpec.apply=scope['apply']; raise SystemExit(pytest.main(['core/support_desk/tests/test_api.py::TestTicketAPIEndpoints::test_ticket_list_filtering','core/support_desk/tests/test_api_helpdesk.py::TestTicketScopingAPI::test_requester_cannot_list_or_read_foreign_tickets','--reuse-db','-q','--tb=line','-p','no:sugar']))"
```
Replay also emitted Windows invalid logging-handle errors; test failures remained identical.

### Gates
Exact changed-path list P below is used for each gate (not a narrowed scope):
```powershell
$P = @('core/common/api/filtering.py', 'core/labs/features/equipment/queries/equipment.py', 'core/labs/features/equipment/queries/facets.py', 'core/common/tests/test_filtering.py', 'core/labs/features/equipment/tests/test_filtering_performance.py', 'core/support_desk/tests/test_filtering_performance.py')
.\.venv\Scripts\python.exe -m ruff check @P
.\.venv\Scripts\python.exe -m ruff format --check @P
.\.venv\Scripts\python.exe -m mypy @P
.\.venv\Scripts\python.exe manage.py check --settings=config.settings.test
git diff --check -- core/common/api/filtering.py core/labs/features/equipment/queries/equipment.py core/labs/features/equipment/queries/facets.py core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py core/support_desk/tests/test_filtering_performance.py core/labs/features/equipment/docs/filtering-performance*
```
These are exact equivalent argv to the expanded commands executed. Initial lint failed two missing final newlines;
initial format failed three test files. Formatter executed only on these task-owned test files:
```powershell
.\.venv\Scripts\python.exe -m ruff format core/common/tests/test_filtering.py core/labs/features/equipment/tests/test_filtering_performance.py core/support_desk/tests/test_filtering_performance.py
.\.venv\Scripts\python.exe -m ruff format core/labs/features/equipment/tests/test_filtering_performance.py
```
Final lint passed; format passed (6 files). Initial mypy 98 errors included new test annotations; corrected to 91,
then final 90 errors in 27 files, all on unchanged lines/imported dependencies; no remaining errors in new tests/facets.
Examples: filtering.py:166 `_kwargs`; equipment.py:245/288/414 dynamic `.objects`, 355/357/444/446 Q/Combinable;
remaining imported model/settings/common/storages backlog. No ignores added, gate not represented as passed.
Django passed (0 issues). Whitespace passed. Broader suite failure list:
- equipment categories/computing/test_computing_activity_application.py: two stale core.labs.signals monkeypatches (known).
- support_desk/tests/test_api.py:50 and test_api_helpdesk.py:26: list HTTP 400; same with old FilterSpec replay.
Root cause of existing ticket HTTP 400 is not verified; deliberately not repaired.

Artifact parity command (passed after an initial one-line command failed PowerShell quote parsing):
```powershell
$compare = @'
import json
from pathlib import Path
p = Path('core/labs/features/equipment/docs')
b = json.loads((p / 'filtering-performance-before.json').read_text())
a = json.loads((p / 'filtering-performance-after.json').read_text())
for name, before in b['cases'].items():
    after = a['cases'][name]
    assert before['count'] == after['count'] and before['page_keys'] == after['page_keys'], name
    print(name, before['median_ms'], after['median_ms'])
print('PASS: all 13 captured paginator counts and stable ordered page keys match')
'@; $compare | .\.venv\Scripts\python.exe -
```

## Facts, drift, limitations / decisions
- Production scope held to three hunks plus comments; no unrelated dirty files edited. No staging/commits.
- Existing deferred serializer N+1: equipment model calibration properties call latest_service_record; storage_room is not
  joined by generic list. Query-only measurements exclude serialization; unchanged problem, not fixed by this optimization.
- Existing drift: equipment.py imports transaction and contains pre-existing mapping/locking behavior; no refactor here.
- Existing kind string-key branch raises FieldError (kind model has no key). Numeric-kind path tested; repair deferred.
- Broad synthetic inventory is only one kind/category and small distinct bucket counts. No concurrent load, deep pagination,
  large M2M population, cold cache, production data, representative hardware, acquisition-history population or HTTP latency study.
  Acquisition annotations compared for nulls; existing equipment suite passed acquisition cases but benchmark has no purchase rows.
- Security/deploy/schema/migration gates not run (no applicable change); audit/static-security tooling not run in this task.
- Independent reviewer unavailable in the original implementation session; see the followup's scoped disposition and evidence limits above. Self-review is not independent review. Editor-selected interpreter not verified
  (Pylance tooling unavailable); actual execution explicitly used project Python.
- Human owner: review these three hunks and evidence; resolve baseline suite/type failures and obtain independent T1 review before merge.
- Cardinality tests must remain gating when dimensions or generic outer joins change; future reverse/M2M outer dimension needs
  redesign or DISTINCT reintroduction. No production speedup promised.
