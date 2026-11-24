# ADR 005 — Reset all project migrations to a fresh initial set

- Status: **Accepted by the repository owner** (2026-11-10, "drop all and create again, start with 0001; it is in development")
- Date: 2026-11-10
- Risk: T2 (migration history is a compatibility surface, AGENTS rule 6)
- Scope: `core/{labs,users,agents,routing,support_desk,websocket,reference_data}/migrations`

## Decision

Every project app's migration history was deleted and regenerated with `makemigrations`. There is
no deployed database to preserve. Three apps (`labs`, `agents`, `support_desk`) get a
`0002_initial` because of foreign keys between apps; that is Django's normal split.

Hand-written operations carried into the new set:

| App | Operation | Where |
|---|---|---|
| labs | `CREATE EXTENSION IF NOT EXISTS pg_trgm` and `btree_gist` (reverse is a no-op: extensions are database-wide and shared) | `0001_initial`, first |
| labs | Seed purchase priorities (`low`, `normal`, `high`, `urgent`) | `0002_initial`, last |
| support_desk | `CREATE EXTENSION IF NOT EXISTS pg_trgm` (its label index no longer relies on labs migrating first) | `0001_initial`, first |
| support_desk | `support_ticket_number_seq` sequence; `TicketActivity` insert-only trigger | `0002_initial`, last |

Dropped because they only transformed existing rows: the Jira data drop (users), the computing-activity
offline backfill and the storage-room placement backfill (labs), the helpdesk defaults backfill
(support_desk), and the `NOT VALID` booking constraints (now ordinary validated constraints).
The old "safe" trigram wrapper that swallowed extension errors was not kept: a missing extension now
fails at the operation that needs it instead of at a later index.

## Consequences

- Every existing database (developer machines, any shared dev or staging database) must be dropped and
  recreated, then `python manage.py migrate`. `migrate` against an old database fails or reports
  inconsistent history.
- Earlier ADRs and feature notes that name old migration files (`0004_drop_jira_integration`,
  `0007_trigram_search_indexes`, `0005_booking_notification`, `0002_referenceimportreceipt`) describe
  history; those files no longer exist.
- Tests that exercised a specific old migration were removed or now build tables from the model.

## Addendum (2026-11-12): one migration per app

On the owner's request ("only one migration; the database is blank"), the set was regenerated again after
merging the roles, URS and authentication work: every app now has exactly one `0001_initial`
(generated app by app in dependency order, so no `0002_initial` split is needed). The additive
`labs.0002_lab_session_access_links` is folded into `labs.0001_initial`.

Hand-written operations, in addition to the table above:

| App | Operation | Where |
|---|---|---|
| labs | Seed purchase priorities | `0001_initial`, last (previously `0002_initial`) |
| support_desk | Ticket number sequence; insert-only `TicketActivity` trigger | `0001_initial`, last (previously `0002_initial`) |
| users | Append-only `RoleAuditEvent` trigger (no UPDATE or DELETE) | `0001_initial`, last |

Verified on a blank database: 7 migrations apply; the four triggers, the sequence, both extensions and the
four priorities exist. Every existing database must be dropped and recreated again.


## Addendum (2026-11-19): regenerated again, one migration per app

On the owner's request ("use only one migration 0001 ... the database is blank; apply for all migrations in
repo"), every app's migrations were deleted and regenerated app by app in dependency order (users,
reference_data, routing, labs, agents, support_desk, websocket). Each app again has exactly one
`0001_initial`.

Folded or dropped:

| Removed file | Handling |
|---|---|
| `labs.0002_booking_completed_at` | Schema folded into `labs.0001_initial` (`completed_at` on both booking models and the `completed_at_iff_completed` constraints). Its backfill only transformed existing rows: dropped. |
| `support_desk.0002_widen_default_attachment_extensions` | Only rewrote existing `SupportSettings` rows; the model default (`DEFAULT_ALLOWED_EXTENSIONS`) already is the widened list: dropped. |

The hand-written operations of the 2026-11-12 table are carried over unchanged (extensions first; seed,
sequence and triggers last).

Verified: a blank database migrated with the old set (9 files) and one migrated with the new set (7 files)
have identical `pg_dump --schema-only` output; on the new database both extensions, the four triggers,
`support_ticket_number_seq` and the four purchase priorities exist. Every existing database must be
dropped and recreated, then `python manage.py migrate`.

## Addendum (2026-11-20): regenerated again, one migration per app

On the owner's request ("start a new migration start with 001_ only"), `users` and `labs` migrations were
regenerated into a single `0001_initial` per app (7 initial migrations across the repository):

| Removed file | Handling |
|---|---|
| `users.0002_labs_role_display_names` | Folded into `users.0001_initial` along with `LabsRole.MEMBER = "member", "Lab Member"` and the `users_ursgroup_valid_labs_role` constraint (`["", "admin", "coord", "member"]`). |
| `labs.0002_telemetry_configuration` | Telemetry configuration models and constraints folded into `labs.0001_initial`. |
| `labs.0003_seed_telemetry_metrics` | `seed_metrics` (`temperature_c`, `humidity_percent`, `power_w`) folded into `labs.0001_initial` (last). |
| `labs.0004_downtime_booking_access` | `ResourceDowntime.booking_access` and `downtime_booking_access_valid` folded into `labs.0001_initial`. |

## Addendum (2026-11-23): consolidated `labs` back into `0001_initial`

On the owner's request ("the migration shall only initial 001, since database is blank and fresh new"),
`labs` migrations were regenerated into a single `labs.0001_initial` (preserving the `pg_trgm` /
`btree_gist` extensions first, and the purchase-priority and v1 telemetry-metric seeds last):

| Removed file | Handling |
|---|---|
| `labs.0002_performance_indexes` | `equipment_active_kind_name_idx` and `equipment_loan_active_due_idx` folded into `labs.0001_initial`. |
| `labs.0003_inspection_retirement_snapshot` | `ResourceServiceRecord.result` (`unknown` choice) folded into `labs.0001_initial`. Temporary snapshot table `labs_bench_inspection_retirement_snapshot` dropped (blank DB). |
| `labs.0004_backfill_bench_inspection_records` | Existing-row backfill dropped (blank DB). |
| `labs.0005_remove_bench_inspection_dates` | Removal of `Bench.last_inspected_at` and `Bench.next_inspection_due_at` folded into `labs.0001_initial`. Migration-specific test `test_inspection_retirement.py` removed. |
| Retired deprecated schema | Removed `LicenseAgreement`, `LicensePayment`, and `ComputingProfile.monitored_devices` directly from `labs.0001_initial`. |
