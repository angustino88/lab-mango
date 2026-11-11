# ADR 006 — Second migration reset for the single equipment table

- Status: **Accepted by the repository owner** (2026-11-10, redesign step 6 decision C, "Reset again")
- Date: 2026-11-11
- Risk: T2 (migration history is a compatibility surface, AGENTS rule 6)
- Scope: `core/labs/migrations`, `core/agents/migrations`

## Decision

Redesign step 6 removes the 12 multi-table subclasses of `Equipment`, adds typed columns and
`ComputingProfile`, adds capability flags to `EquipmentCategory`, and repoints four foreign keys from
`ComputingEquipment` to `Equipment`. There is still no deployed database, so, as in ADR 005, the history is
regenerated instead of written as data migrations.

Only `labs` and `agents` are regenerated: `agents.0002_initial` is the only migration outside `labs` that
depends on a `labs` migration. `users`, `routing`, `support_desk`, `websocket` and `reference_data` keep the
ADR 005 history unchanged. `labs` is now one `0001_initial` (it no longer needs a `0002`).

Hand-written operations carried into `labs.0001_initial`: `CREATE EXTENSION IF NOT EXISTS pg_trgm` and
`btree_gist` first (no-op reverse), the purchase-priority seed last. Dropped: the step 3 loan-batch backfill
(`0005`) and the step 5 bench value map (`0008`), which only transformed existing rows, and the test that
exercised the `0005` backfill.

## Consequences

- Every development database must be dropped and recreated, then `python manage.py migrate`.
- Data in the old category tables is not carried over.
- `makemigrations --check` reports no changes; `migrate agents zero`, `migrate labs zero`, `migrate` round-trips.
