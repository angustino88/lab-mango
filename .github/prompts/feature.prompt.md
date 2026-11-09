---
description: 'Plan and deliver a backend feature end to end'
agent: 'engineering-lead'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: Feature Development

Roles per tier: see `docs/ai-team/team.md`. Lead runs steps 1–3 and 8; specialists own their steps.

## 1. Define (Lead)
Outcome, acceptance criteria, non-goals, roles/permissions, lifecycle transitions,
failure scenarios, tier. Resolve ambiguity that could change data or visible behavior
with the human owner before design.

## 2. Inspect (Lead + specialists)
Read `AGENTS.md`, relevant standards, adjacent feature code, tests, models, API
contracts, ADRs. Record existing patterns to preserve and the baseline gate results.

## 3. Design (T2; short note for large T1)
Use `docs/ai-team/templates/design-doc.md`: domain behavior and invariants, module ownership and
allowed dependencies (Architecture Agent), contract (API Designer), schema/constraints/migration
(Data Architect), authorization and threat notes (Security), async/integration needs
(Integration), rollout and observability (DevOps), test plan (QA).
**Human approval** for material architecture changes and ambiguous business rules.

## 4. Implement (Backend Engineer; single writer)
Smallest complete change. Tests first or alongside. Update schema/OpenAPI, docs, migrations.

## 5. Verify (Engineer + QA)
Focused tests, then broader gates (`docs/ai-team/quality-gates.md`). Inspect the diff for
secrets, noise, unrelated changes, missing migrations. Report anything not run.

## 6. Security & ops review (T2)
Security Engineer: authorization matrix, data exposure, dependencies.
DevOps: rollout, rollback, monitoring.

## 7. Independent review
Reviewer receives brief + diff only. Author fixes blockers; affected checks are re-run
and re-reviewed.

## 8. Handoff (Lead)
`docs/ai-team/templates/handoff-report.md` with the evidence ledger. Human owner decides merge.
