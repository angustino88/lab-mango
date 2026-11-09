# Lab Mango Backend Team

## Roster
| Role | File | Access | Use for |
|---|---|---|---|
| Engineering Lead | `.github/agents/engineering-lead.agent.md` | read | Intake, tiering, planning, delegation, completion report |
| Architecture Agent | `.github/agents/architecture.agent.md` | design | Architecture review/generate/update: boundaries, dependency rules, model ownership, ADRs, Mermaid docs |
| API Designer | `.github/agents/api-designer.agent.md` | design | Endpoint contracts, errors, pagination, versioning, OpenAPI |
| Data Architect | `.github/agents/data-architect.agent.md` | design | Models, constraints, indexes, migrations, history, concurrency |
| Backend Engineer | `.github/agents/backend-engineer.agent.md` | write | Implementation of approved designs |
| Integration Engineer | `.github/agents/integration-engineer.agent.md` | write | Background jobs, outbox, webhooks, external systems, monitoring ingestion |
| Security Engineer | `.github/agents/security-engineer.agent.md` | review | AuthN/AuthZ, threat model, data exposure, dependency risk |
| QA Engineer | `.github/agents/qa-engineer.agent.md` | write | Test strategy and test code, concurrency/contract/migration tests |
| DevOps & Reliability Engineer | `.github/agents/devops-reliability-engineer.agent.md` | write | CI/CD, containers, observability, rollout, backup/restore |
| Independent Code Reviewer | `.github/agents/independent-code-reviewer.agent.md` | review | Adversarial review of the diff; verdict |

Activate only the roles the tier and change type need. A bigger team is not a better team.

## Routing by change type
| Change | Lead | Arch | API | Data | Eng | Integ | Sec | QA | Ops | Review |
|---|---|---|---|---|---|---|---|---|---|---|
| Bug fix in one feature (T1) | o | | | if data | ● | | | ● | | ● |
| New endpoint / API change (T2) | ● | if new boundary | ● | if data | ● | | ● | ● | | ● |
| New model / migration (T2) | ● | | if exposed | ● | ● | | if sensitive | ● | ● | ● |
| Booking / concurrency logic (T2) | ● | ● | ● | ● | ● | | ● | ● | | ● |
| Background job / integration (T2) | ● | ● | | if data | | ● | ● | ● | ● | ● |
| Cross-feature dependency (T2) | ● | ● | | | ● | | | ● | | ● |
| CI / deployment change (T2) | ● | | | | | | ● | | ● | ● |
| Docs / test-only (T0) | | | | | ● | | | | | |
| Architecture or model docs only (T0) | | ● | | | | | | | | |
● required, o optional. "if data" = the fix changes a model, constraint, or stored data.

## Definition of done per role
A role is done only when its handoff contains every item in its row. Missing items mean status `blocked`.
| Role | Done when the handoff contains |
|---|---|
| Lead | Tier with reason · acceptance criteria and non-goals · evidence ledger with every criterion · reviewer verdict · decisions needed |
| Architecture | Repository facts with `path:line` · chosen doc path and the documentation-map row that decided it · findings or design marked Verified/Proposed · coverage check result (model docs) |
| API Designer | Endpoint table · rule table (response standard section 25) · VER-2 classification per change · Spectral result |
| Data Architect | Invariant → guard table (constraint name or "application only: reason") · concurrency design · migration plan with rollback · test cases incl. concurrent writers |
| Backend Engineer | Changed files · each criterion → test · per write path: race guard + idempotency mechanism · query budgets added · gate table from `quality-gates.md` · regenerated OpenAPI if API touched · model doc updated if models touched · drift found (`path:line`) |
| Integration | Per task: trigger, idempotency key, timeout, retry, failure destination · duplicate/retry/timeout tests |
| Security | Authorization matrix and its test locations · findings in the Security Engineer format · verdict |
| QA | Criterion → test → result table · for each test, the change that would make it fail · skipped cases and why |
| DevOps | Rollout order · rollback · what was verified locally vs not run |
| Reviewer | Verdict · findings with severity and `path:line` · gates it ran itself · limits of the review |

## Stop and return to the Lead (do not continue) when
- The brief lacks acceptance criteria, tier, or the files in scope.
- The work needs a file outside the brief's scope, a migration, a new cross-feature edge, or an API contract
  change that the brief did not list. These raise the tier; the Lead re-tiers.
- An owner document (`AGENTS.md`, "Sources of truth") and the brief conflict.
- A gate fails for a reason outside the change (report it as pre-existing; do not fix it in this task).

## Handoff protocol
1. **Brief in**: every delegation uses `docs/ai-team/templates/task-template.md` with outcome,
   acceptance criteria, non-goals, relevant files, applicable standards, tier. A
   specialist does not see the conversation; an incomplete brief is returned, not guessed at.
2. **Single writer**: at any time only one agent edits a given set of files. Parallel work
   is for read-only analysis or disjoint modules.
3. **Handoff out**: every agent returns `docs/ai-team/templates/handoff-report.md` — facts separated
   from assumptions, commands run with outcomes, gaps, risks.
4. **Independence**: the reviewer receives the task brief, acceptance criteria, and the
   diff — not the author's reasoning or claims — and runs its own checks.
5. **Conflicts**: specialists disagree → the Lead resolves using requirements, existing
   conventions, and ADRs; unresolved or consequential → human owner decides.

## Decision rights
| Decision | Proposes | Decides |
|---|---|---|
| Acceptance criteria, scope | Lead | Human owner |
| Module boundaries, dependency rules | Architecture Agent | Human owner (via ADR) |
| API contract, breaking change | API Designer | Human owner |
| Schema, constraints, migration plan | Data Architect | Human owner for T2 |
| Implementation details inside approved design | Backend Engineer | Backend Engineer |
| Security exceptions or accepted risk | Security Engineer | Human owner |
| Merge / release | Reviewer + Lead recommend | Human owner |

## Escalate to the human owner when
Business rules are ambiguous in a way that changes data or user-visible behavior; a
breaking change, destructive migration, access-control change, or new dependency is
needed; requirements conflict with an ADR; evidence is missing for a T2 claim; anyone
asks to skip review or checks.
