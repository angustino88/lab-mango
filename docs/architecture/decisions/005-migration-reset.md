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
