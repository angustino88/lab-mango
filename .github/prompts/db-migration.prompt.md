---
description: 'Plan and deliver a safe schema/data migration'
agent: 'engineering-lead'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: Database Migration

1. **Design** (Data Architect): target schema, invariants as constraints, indexes,
   backfill need, expected table sizes and lock risk.
2. **Plan expand → migrate → contract** across releases. State what the *previous*
   app version needs to keep working.
3. **Write migrations**: one concern each; concurrent index creation where needed;
   `NOT VALID` then validate for big-table constraints; set lock timeout; reversible
   or explicitly documented as irreversible.
4. **Backfill** separately: batched, idempotent, resumable, observable.
5. **Test**: apply on PostgreSQL from the previous schema with representative data; run
   `makemigrations --check`; test constraint violations and concurrent writers.
6. **Review**: Data Architect + Independent Reviewer; DevOps confirms release ordering
   and rollback.
7. **Production**: only with explicit human authorization. Take/verify a restorable backup
   first; monitor locks and replication lag.
8. **Contract** in a later release once no instance uses the old shape.
