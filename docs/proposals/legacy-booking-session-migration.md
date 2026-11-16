# Design: Migrate legacy bench bookings and lab session logs

- Tier: T2 (production data change, booking concurrency, cross-feature)
- Status: Proposed, **on hold** (owner, 2026-11-16). Not implemented. Needs the open questions answered,
  sign-off on the mapping tables and human approval before any production run.
- Scope: one-off copy of the old system's booking table and session-log table (PostgreSQL) into
  `BenchBooking` (`core/labs/models/booking/bench_booking.py`) and `LabSessionLog`
  (`core/labs/models/session/lab_session.py`).

## 1. Source tables (from the owner, 2026-11-16)

Old booking table:

```
id, created, modified, from_date_time, to_date_time, booking_code, creator_id, last_modified_by_id,
lab_device_id, status, booking_reason, lab_information_id, lab_project_id, approval_status, approval_by_id
```

Old session-log table:

```
id, created, modified, login_time, logout_time, remote_ip, source, remote_computer, booking_code,
remote_user, lab_id, active_time, computer_name, remote_user_displayname, creator_id, last_modified_by_id
```

Sample rows show `timestamptz` values in UTC, `status = done`, `approval_status = approved`,
`source = AGENT_<hostname>` and empty strings for missing text values.

## 2. Target constraints that shape the migration (verified in code)

| Target | Constraint | Consequence |
|---|---|---|
| `BenchBooking.booking_code` | unique | Keep the old code unchanged; session logs link to bookings through it |
| `bench_booking_no_overlap` | exclusion constraint on reserving bookings (reserved/in_progress and pending/approved) | Past rows are terminal and never collide; future reserving rows that overlap go to the conflict report |
| `*_valid_booking_period` | `ends_at > starts_at` | Rows that break it are rejected and reported |
| `*_cancellation_has_reason`, `*_rejection_has_reason` | reason required | Default `"Migrated: no reason recorded"` |
| `*_pending_has_no_approver` | pending has no approver | Approver dropped for pending rows |
| `Booking.clean()` | rejected needs an approver | Owner decision needed (section 7, Q5) |
| `BOOKING_STATUS_TRANSITIONS` | state machine for live writes | The final state is set directly, not replayed |
| `unique_session_report_per_agent` | `(computing_equipment, agent_id, event_id)` | `agent_id = source`, `event_id = uuid5(NS, "legacy-session:<id>")`: reruns skip loaded rows |
| `labsess_valid_period` | `logout_time > login_time` or either is NULL | A bad logout becomes NULL and is reported |
| `labsess_access_type_matches_code` | `ad_hoc` has no code; booked/unverified has a code | Empty booking codes become NULL |
| `labsess_booking_only_when_booked` | a booking link needs `access_type = booked` | Links come from the classification rule (section 4) |

Model defaults (`reason=""` and others) are Django defaults, not database defaults: a raw `INSERT` or `COPY`
must supply every NOT NULL column.

## 3. Column mapping

### 3.1 Bookings → `BenchBooking`

| Old | New | Rule |
|---|---|---|
| `id` | migration id map | `(legacy.booking, id) → new pk` |
| `created`, `modified` | `created`, `modified` | copied (already UTC `timestamptz`) |
| `from_date_time`, `to_date_time` | `starts_at`, `ends_at` | `to <= from` rejected |
| `booking_code` | `booking_code` | unchanged; a duplicate is rejected |
| `creator_id` | `creator` and `requester` | via the user map; the old table has no separate requester |
| `last_modified_by_id` | `last_modified_by` | via the user map, NULL when empty |
| `lab_information_id` | `bench` (required) | via the bench map; unmapped rows are rejected |
| `lab_device_id` | — | a device booking belongs to `EquipmentBooking`: out of scope, counted and reported |
| `lab_project_id` | `project` | via the project map (code, then name); unmapped → NULL and reported |
| `booking_reason` | `reason` | trimmed |
| `status` | `status` | status map (3.3) |
| `approval_status`, `approval_by_id` | `approval_status`, `approved_by` | `approved_at = modified` when approved, else NULL |

### 3.2 Session logs → `LabSessionLog`

| Old | New | Rule |
|---|---|---|
| `id` | `event_id` | `uuid5(NS, "legacy-session:<id>")` |
| `source` | `agent_id`, `host_name` | `agent_id = source`; `host_name = source` without the `AGENT_` prefix; `agent_version = "legacy"`; `reported_at = created` |
| host name, `computer_name` | `computing_equipment` | profile hostname (case-insensitive), then equipment name; unmatched → NULL and reported |
| `login_time`, `logout_time` | same | `logout <= login` → `logout_time = NULL`, reported |
| `remote_ip` | `remote_ip` | empty → NULL; invalid → NULL, reported |
| `remote_computer` | `remote_host` | empty → NULL |
| `booking_code` | `booking_code` | empty → NULL |
| `remote_user` | `remote_user` | copied; drives the user link |
| `remote_user_displayname` | `remote_user_display_name` | copied; personal data, kept out of reports |
| `active_time` | `active_duration_seconds` | unit to confirm (Q3) |
| `lab_id` | `bench` | via the bench map |
| `creator_id`, `last_modified_by_id`, `created`, `modified` | same | copied |

### 3.3 Status map (to confirm with the distinct values, Q2)

| Old `status` | Booking already ended | Booking ends in the future |
|---|---|---|
| `done` | `completed` | `completed` (reported as odd) |
| booked / reserved / pending | `expired` | `reserved` (checked against the overlap constraint) |
| in use / in progress | `completed` | `in_progress` |
| cancelled | `cancelled` + default reason | same |
| rejected | `approval_status = rejected` + default reason | same |

## 4. Session links: set by the loader, not by `backfill_session_links`

`backfill_session_links` derives the bench from the equipment placement at login time (`bench_id_at`).
The new system has no placement history before go-live, so almost every migrated session would get no
bench and become `unverified_booking`. The loader instead:

1. sets `bench` from the old `lab_id` (the historical truth);
2. finds the booking by `booking_code` among the migrated bookings;
3. applies the same rule as `classify_access` (`lab_sessions/application/resolve_session_links.py`):
   booked only when the booking is approved, not cancelled, on the same bench and the login falls inside
   the booking window; otherwise `unverified_booking`; no code is `ad_hoc`;
4. sets `user` with `resolve_user_id_for_login_name`.

Afterwards run `backfill_analytics_daily_snapshots`.

## 5. Load options

| | A. pgAdmin transport + SQL script | B. Django management command |
|---|---|---|
| Transport | pgAdmin Import/Export (CSV, header, UTF-8) into a `legacy` staging schema | `pg_dump` of the needed tables restored into a `legacy` schema, or a read-only `DATABASES["legacy"]` alias |
| Transform | one reviewed `INSERT … SELECT` script with joins to mapping tables, `ON CONFLICT DO NOTHING`, one transaction | `migrate_legacy_lab_history --dry-run --batch-size --since` |
| Validation | database constraints plus pre-check queries | database constraints plus model `clean()` |
| Booking verification | re-implemented in SQL (main risk) | reuses the Python rule through a new `lab_sessions` public function that takes the bench as input |
| Error report | pre-check queries; otherwise the first error aborts | per-row report |
| Fits | up to a few thousand rows | hundreds of thousands of session logs, or exact verification needed for reports |

Rejected: exporting the old rows to Excel or CSV, editing them by hand and importing them straight into the
new tables. Old ids differ from new ids, required columns have no database defaults, Excel converts codes
and timestamps, the work cannot be repeated for the final delta, and nothing is reconciled.

Excel is used only for:

- the mapping tables (old bench → new bench SKU, old user → username, old project → project code,
  old status → new status), exported, completed by the team and re-imported;
- the dry-run report and the reconciliation report.

## 6. Procedure

1. Rehearse on a staging copy of the new database; back up the target first.
2. Load the old tables into the `legacy` schema.
3. Export, complete and re-import the mapping tables; run the pre-checks (unmapped benches, users, projects;
   duplicate codes; bad periods; overlapping future bookings).
4. Load bookings, then session logs, then derived links and analytics.
5. Reconcile: row counts; booked hours per bench per month; sessions and active time per host per month;
   share of `booked`, `ad_hoc`, `unverified_booking`.
6. Cutover: freeze the old system, run the final delta (`created > watermark`), reconcile again, switch.
7. Drop the `legacy` schema.

## 7. Open questions

| # | Question |
|---|---|
| Q1 | Are `lab_information` (booking) and `lab_id` (session) the same old table, one row per bench? Which column matches the new bench SKU? |
| Q2 | Distinct `status` / `approval_status` values with counts, and how many rows have `lab_device_id`. |
| Q3 | Unit of `active_time`: seconds or minutes? |
| Q4 | Columns of the old project and user tables. |
| Q5 | Rejected bookings without an approver: approver = `legacy-migration` system user (recommended), or load as `cancelled`? |
| Q6 | Row counts of both tables (chooses option A or B). |
