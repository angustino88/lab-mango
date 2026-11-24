# Workbook import: performance of the create path

Status: implemented on the import-performance branch; T2 (shared validation, equipment create command), needs
owner approval before merge. Decision record for the validation helper: [ADR 009](../../../../../docs/architecture/decisions/009-validate-for-write.md).

## 1. Where the time went (measured before the change)

A Check of 202 equipment rows (half desktops with a Computing details row, half monitors with a Display details
row, a condition and a storage room) took 51 ms and 45 queries per row; reading the file was 0.2% of it.

| Source | Queries per row | Share |
|---|---|---|
| `full_clean()` in `create_equipment` (one query per loaded foreign key; savepoint-wrapped constraint checks) | 14.5 | 32% |
| `full_clean()` of the downtime window in `start_now` (per monitor with a condition) | 9.5 | 21% |
| `change_condition` and `place_equipment` called after the create (savepoints, re-lock, re-read of a new unit) | 7 | 16% |
| Computing profile saved as UPDATE-then-INSERT-then-UPDATE; activity via `get_or_create`; `.set()` on a new unit | 3.5 | 8% |
| Row savepoints, inserts, lifecycle event, duplicate-SKU lookup (kept) | 10.5 | 23% |

## 2. What changed

| Change | Where | Why it is equal |
|---|---|---|
| Validate with `validate_for_write` | `create_equipment`, `create_profile`, `start_now` | Same steps and errors as `full_clean()`; skips only checks that cannot fail (ADR 009); parity tests in `tests/unit/test_validate_for_write.py` |
| Starting condition and storage room in `CreateEquipmentInput` | `create_equipment`, used by the import | Same primitives as `change_condition` / `place_equipment` (`set_condition_now`, `rest_equipment`, `lock_room`), same checks and messages; only the re-lock and re-read of the unit created in the same transaction are skipped. `test_create_starting_state.py` compares the result with the separate commands |
| Profile inserted once with its .rdp file | `create_profile` | A new unit has no profile; `force_insert` refuses a second one |
| Activity row created directly | `start_computing_activity` | A new unit has no activity row; the one-to-one key refuses a second one |
| `.add()` instead of `.set()` on a new unit | `create_equipment` | A new unit has no links; the same m2m signals fire |
| .rdp file name read from the loaded profile | import `_remember_created_rdp_file` | Same name as the query returned |

Not changed: the per-row savepoint (ERR-7), the command's own transaction, the duplicate-SKU lookup, the downtime
and placement guard reads (`start_now` current/upcoming windows, `rest_equipment` loan and active placement), the
advisory lock for Apply, update mode (`upsert`).

## 3. Result

Measured 2026-11-25 on a local PostgreSQL 16 through the API (test client, warm process), same workbook
before and after: half desktops with Computing details, half monitors with Display details, a condition and a
storage room, plus the reference, space and placement rows of the test workbook.

| Rows | Endpoint | Before | After | Queries per row |
|---|---|---|---|---|
| 202 | Check | 10.3 s (51 ms/row) | 4.3 s (21 ms/row) | 45 → 15 |
| 202 | Apply | 10.0 s (49 ms/row) | 4.5 s (22 ms/row) | 45 → 15 |
| 2,002 | Check | 121.0 s (60 ms/row) | 38.3 s (19 ms/row) | 43.2 → 12.7 |
| 2,002 | Apply | 119.5 s (60 ms/row) | 38.5 s (19 ms/row) | 43.2 → 12.7 |

Not measured: update mode (`upsert`), workbooks dominated by space rows, a remote database (each saved round trip
counts more there).

The import query budget is a test: `tests/test_query_budget.py` fixes the queries per desktop-and-monitor pair
(86 before, 25 after).

## 4. Behavior notes

- Race guards are unchanged (ADR 009, "Consequences").
- A row whose storage room does not exist now fails on the room before the create runs. A row with both a bad
  storage room and another create error reports the room error (before: the create error). Either way the row
  fails and nothing of it is saved; fixing the reported problem shows the other one on the next Check.
- Remaining per-row cost is mostly savepoints and inserts. Batching creates (`bulk_create`) would bypass the
  owning commands, their signals and per-row error isolation; not done.
