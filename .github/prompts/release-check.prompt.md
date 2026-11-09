---
description: 'Assess release readiness (recommendation only)'
agent: 'engineering-lead'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: Release Readiness

## Required evidence
- Acceptance criteria mapped to code and tests (evidence ledger).
- Unit, integration, API, concurrency, and regression results.
- Lint, type, architecture, schema/OpenAPI, and security-scan results where configured.
- Migrations reviewed for ordering, locks, backfill, and rollback; compatible with the
  currently deployed app version.
- API/frontend contract compatibility confirmed.
- Authorization and data-exposure review done for T2 changes.
- Config, secrets, health checks, logs, metrics, alerts understood; new alerts have runbooks.
- Backup state and rollback plan documented for changes that need them.

## Decision (recommendation only)
Ready for human release approval · Ready with documented non-blocking risks · Blocked.
Completing this checklist never authorizes a release. The authorized human or approved
release automation owns that decision.
