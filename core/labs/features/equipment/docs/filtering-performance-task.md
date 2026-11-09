# Task: bounded filtering performance

**Tier**: T1 — user-authorized read-query optimization; no schema, contract, permission or dependency change.
**Assigned role**: Backend Engineer

## Outcome / acceptance criteria
- Only applied filters request DISTINCT; preserve false values, search DISTINCT, existing DISTINCT and separate filter calls.
- Remove generic list DISTINCT only after PostgreSQL result/annotation/count/page parity and non-multiplying outer joins are verified.
- Keep facet PK-IN membership isolation; replace distinct count only with seven-dimension cardinality tests and duplicate-population parity.
- Cover reverse/M2M filtering, tickets, status/assignment/history/search, null/deleted/retired facets.
- Capture before/after paginator SQL and repeated EXPLAIN (ANALYZE, BUFFERS), using >1,000 synthetic rows if feasible.
- Persist exact gate commands, failures, measurement limits and review gaps in the performance handoff.

## Scope / non-goals
Production: core/common/api/filtering.py; equipment/queries/equipment.py; equipment/queries/facets.py only.
Tests: shared filtering tests, equipment performance regression/measurement tests; documentation beside equipment.
Preserve unrelated dirty hunks (including existing changes in equipment.py and untracked facets.py).
No migrations, schemas, dependencies, permissions, defaults, production data or deployment.
Calibration/storage_room serializer N+1 and stale core.labs.signals suite failures are deferred, not repaired.

## Context / verification
AGENTS.md, feature-template.md, team.md, quality-gates.md; coding, architecture, Django, testing and query-performance rules.
Run failing regression tests first, then focused/shared/equipment/ticket/architecture tests; changed-path Ruff format/lint/mypy,
whitespace and Django system check. PostgreSQL only; disable dotenv loading and use a new loopback-only trust-authenticated
temporary cluster without reading credentials or environment files. Tests own all synthetic writes; no production connection.
Independent review is required before merge; unavailable independent tooling must be reported, not simulated.