# Lab Mango — Backend Engineering Instructions

Always loaded in every session. It holds only rules that apply to every task and links to where
everything else lives. Path-scoped rules in `.github/instructions/` load automatically for matching files.

## Product and stack
Lab Mango manages laboratory resources and operations: rooms, stations, benches, equipment, bookings,
assignments, licenses, expenses, monitoring. Django 5.2, DRF, PostgreSQL, Celery; a React/TypeScript
frontend consumes `/api/`. Domain terms: `docs/ai-team/domain-glossary.md`. Verify anything else in the
repository before relying on it; when you cannot verify something, say "not verified".

## Sources of truth (read the one your task touches)
| Topic | Owner document |
|---|---|
| Feature layout, layers, imports, `public.py` / `contracts.py` / `exceptions.py` | `docs/architecture/feature-template.md` |
| Model placement and persistence conventions | `docs/conventions/django-models.md` |
| API responses and requests (rule IDs such as `ERR-1`) | `docs/api/response-standard.md`, `docs/api/request-standard.md` |
| Where any document goes (model docs, feature docs, ADRs) | `docs/ai-team/documentation-map.md` |
| Transactions, race conditions, idempotency | `.github/instructions/write-safety.instructions.md` |
| N+1, query budgets, bounded reads, indexes | `.github/instructions/query-performance.instructions.md` |
| Commands that verify a change | `docs/ai-team/quality-gates.md` |
| Roles, routing, handoff, escalation | `docs/ai-team/team.md` |

**Existing code is transitional** (`docs/architecture/feature-template.md`, first paragraph). When adjacent code
contradicts an owner document, write new code to the owner document and report the drift with `path:line`.
Do not copy the deviation. Example: an existing view calling `Bench.objects.filter(...)` is not a pattern
to repeat.

## Non-negotiable rules
1. Preserve deployed behavior (routes, payloads, task names, model imports, migration history) unless the
   task explicitly changes it.
2. Resource lifecycle status, booking status, assignment status, and live activity status are separate
   fields and state machines. Never merge them because the values look alike.
3. Another feature is used only through its `public.py` (behavior) and `contracts.py` (types).
   `core.common` and `core.infrastructure` are technical and import no business app (`core.labs`,
   `core.users`, ...). Business apps under `core/` are not "core/platform" code.
4. Enforce invariants in PostgreSQL where it can express them (constraint, exclusion constraint, unique
   index). Serializer or application checks are an extra layer, never the only guard. Every write path names
   its race guard and is safe to run twice (`write-safety.instructions.md`).
5. Authorization is server-side, deny-by-default, and object-scoped.
6. Migrations and API contracts are compatibility surfaces. Breaking changes need a written plan and
   human approval.
7. No new dependency without a written purpose, alternative considered, and maintenance owner.
8. Report every check as **passed / failed / not run** with the exact command. Never report "passed"
   without having seen the output.
9. Never print or commit secrets or production data. No production deploy, destructive action,
   production-data change, or access-control change without explicit human authorization.
10. Every changed hunk traces to the task. No unrelated refactors or reformatting.

## Risk tiers (decide first; if unsure, take the higher tier)
| Tier | Applies when | Minimum process |
|------|--------------|-----------------|
| T0 Trivial | Docs, comments, test-only, no behavior change | Quality gates |
| T1 Standard | Contained behavior change in one feature; no schema, API-contract, or permission change | Task brief, tests, quality gates, independent review |
| T2 High-risk | Any migration or constraint; public API contract; authn/authz; money, license, or expense logic; booking/concurrency; background jobs or integrations; cross-feature dependency; deletion/retention; CI/infra | Design note, relevant specialists, security + QA review, independent review, human approval before merge |

## Workflow and definition of done
Define → Inspect → Design (T2) → Implement → Verify → Independent review → Handoff, via the slash
commands in `.github/prompts/`. Briefs use `docs/ai-team/templates/task-template.md`; results use
`docs/ai-team/templates/handoff-report.md`. A task is done when:
- each acceptance criterion maps to code and to a test (evidence ledger in the handoff);
- the quality gates for the touched paths are reported per rule 8;
- regenerated OpenAPI and updated docs are in the same change when public behavior or models changed;
- the handoff lists facts vs assumptions, gaps, and residual risks.

Agents recommend; the repository owner decides. Report findings with severity and `path:line`.
