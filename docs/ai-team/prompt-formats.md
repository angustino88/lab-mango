# Prompt formats

One format per kind of work. Use the slash command when one exists (it asks for the same fields), or paste the
filled format into chat with the agent shown. Fill what you know; write `unknown` for the rest and the agent will
list it as an open question instead of guessing. Never put secrets or production data in a prompt.

## Index
| # | Work | Slash command | Agent | Tier |
|---|---|---|---|---|
| 0 | Any task (universal brief) | paste | `engineering-lead` | any |
| 1 | New feature | `/feature` | `engineering-lead` | T1/T2 |
| 2 | Model design (docs) | `/model-design` | `architecture` | T2 |
| 3 | Model implementation | `/model-implement` | `backend-engineer` | T2 |
| 4 | Model docs update | `/architecture-update` | `architecture` | T0 |
| 5 | API change | `/api-change` | `engineering-lead` | T2 |
| 6 | Database migration | `/db-migration` | `engineering-lead` | T2 |
| 7 | Bug fix | `/bug-fix` | `engineering-lead` | T1/T2 |
| 8 | Background job / integration | `/integration` | `integration-engineer` | T2 |
| 9 | Tests / test plan | `/test-plan` | `qa-engineer` | T1/T2 |
| 10 | Architecture review | `/architecture-review` | `architecture` | read-only |
| 11 | Architecture design (feature) | `/architecture-design` | `architecture` | T2 |
| 12 | Decision record (ADR) | `/adr` | `architecture` | T2 |
| 13 | Security review | `/security-review` | `security-engineer` | T2 |
| 14 | Independent code review | `/review` | `independent-code-reviewer` | T1/T2 |
| 15 | Performance investigation | `/performance` | `engineering-lead` | T1/T2 |
| 16 | Refactor | `/refactor` | `engineering-lead` | T1/T2 |
| 17 | CI/CD or ops change | `/ops-change` | `devops-reliability-engineer` | T2 |
| 18 | Release readiness | `/release-check` | `engineering-lead` | recommendation only |

Typical flows: feature = 1 → (2 → owner approval → 3) → 5/6 as needed → 9 → 13 → 14.
Model = 2 → approval → data-architect → 3 → 14. Bug = 7 → 14.

## 0. Universal brief
```text
Tier: <T0 | T1 | T2 | unknown, lead decides>
Outcome: <what changes for the user or the business>
Acceptance criteria: <observable results, one per line>
Non-goals: <what must not change>
Context: <paths, features, models, APIs, ADRs involved>
Risks to consider: <security, permissions, data integrity, concurrency, migration, performance, operations>
Verification: <tests and gates expected>
Return: handoff report with an evidence ledger
```

## 1. Feature
```text
Agent: engineering-lead
Feature: <name and one-sentence purpose>
Users and permissions: <who can do what>
Behavior: <main flow, edge cases, failure cases>
Acceptance criteria: <observable results>
Data involved: <existing models, new models, lifecycle/status concepts>
API surface: <endpoints needed, or "none">
Async or integration needs: <jobs, events, external systems, or "none">
Non-goals: <list>
Constraints: <deadlines, compatibility, dependencies not allowed>
Decisions already made: <list, or "none">
```

## 2. Model design (documentation only)
```text
Agent: architecture, mode GENERATE
Domain / model group: <domain> / <group>
Goal: <what these models let the business do>
Models: <existing, and new ones to add>
Business rules and invariants: <rules that must always hold>
Status concepts involved: <lifecycle | assignment | booking | runtime activity | financial>
Hierarchy: <none | describe | let the agent propose; prefer composition>
Relationships to other domains: <models and direction>
Volume, concurrency, performance: <contested records, expected size, hot queries>
Output path: <exact path, or "follow documentation-map">
Not in scope: <list>
Deliverables: model document, ER diagram, hierarchy diagram if any, state diagram, ADR if hard to reverse, open questions
```

## 3. Model implementation
```text
Agent: backend-engineer (T2)
Approved design: <path to design doc>
Implement now: <models/groups>
Out of scope: <list>
Must include: constraints, indexes, migration (expand/migrate/contract), tests (invalid data, lifecycle, concurrency)
Gates to run: <per docs/ai-team/quality-gates.md>
```

## 4. Model docs update
```text
Agent: architecture, mode UPDATE (documentation only)
Changed: <models, fields, constraints, inheritance that changed, with PR or commit>
Document(s): <path, or "locate via documentation-map">
Also check: catalog row, domain ER, hierarchy overview, links, coverage check
```

## 5. API change
```text
Agent: engineering-lead -> api-designer
Endpoint(s): <method and path, new or changed>
Change: <what is added, changed, or removed>
Clients affected: <frontend screens, other consumers>
Breaking?: <yes | no | unknown, API designer classifies>
Auth and permissions: <roles and object scoping>
Contract details: <pagination, filters, errors, idempotency, concurrency control>
Deprecation window: <if breaking>
Verification: <schema validation, permission matrix, contract tests>
```

## 6. Database migration
```text
Agent: engineering-lead -> data-architect
Change: <tables, columns, constraints, indexes, data backfill>
Reason: <business or performance need>
Table size and traffic: <rows, write rate, lock sensitivity>
Compatibility: <old app version must keep working? release order>
Backfill: <needed? volume, batching limits>
Rollback: <how to undo, data implications>
Production: <planned window; no execution without explicit authorization>
```

## 7. Bug fix
```text
Agent: engineering-lead
Symptom: <what happens, what should happen>
Reproduction: <steps, data, environment, or "unknown">
Evidence: <error message, log line, failing test, screenshot path>
Impact: <who and how many, data already affected?>
Suspected area: <paths, or "unknown">
Constraints: <hotfix urgency, no schema change, ...>
```

## 8. Background job / integration
```text
Agent: integration-engineer
Purpose: <what must happen outside the request>
Trigger: <event, schedule, API call>
Input and output: <data, external system, expected result>
Idempotency: <what makes a repeat safe>
Failure behavior: <retries, timeouts, dead-letter, who is alerted>
Volume and timing: <rate, size, latency tolerance>
Security and data: <credentials handling, personal data, webhooks signature>
Observability: <metrics and alerts wanted>
```

## 9. Tests / test plan
```text
Agent: qa-engineer
Target: <feature, endpoint, model, job, or diff>
Acceptance criteria / invariants: <list>
Layers wanted: <unit | integration | API | permission matrix | concurrency | migration | contract>
Known gaps or flaky tests: <list>
Constraints: <runtime budget, no real network>
Return: criterion -> test -> result table; commands run
```

## 10. Architecture review (read-only)
```text
Agent: architecture, mode REVIEW
Scope: <feature, model group, or whole domain>
Depth: <Quick | Standard | Deep>
Focus: <boundaries | model ownership | inheritance | transactions | authorization | performance | docs drift | all>
Known concerns: <list, or "none">
Output: findings by priority with Confirmed or Potential status, evidence, and suggested owner
```

## 11. Architecture design (feature)
```text
Agent: architecture, mode GENERATE
Feature: <name>
Requirements: <behavior and quality attributes: integrity, concurrency, performance, security>
Existing code to reuse or respect: <paths>
Boundaries: <features it may depend on, who may depend on it>
Alternatives to compare: <list, or "agent proposes">
Output path: <exact path, or "follow documentation-map">
Deliverables: feature architecture document, diagrams, enforcement plan, ADR if warranted
```

## 12. Decision record (ADR)
```text
Agent: architecture
Decision: <the choice to record>
Context and constraints: <why it is needed now>
Options considered: <list, with known trade-offs>
Decision owner: <name>
Status: <Proposed | Accepted>
Enforcement: <import-linter contract, test, CI gate>
```

## 13. Security review
```text
Agent: security-engineer
Scope: <diff, endpoint, feature, or dependency change>
Assets and actors: <data and roles involved>
Auth mode: <session | token | other, or "inspect">
Focus: <authorization | data exposure | uploads | integrations | dependencies | all>
Known risks or past incidents: <list, or "none">
Constraints: <no destructive tests, no production access>
Return: findings in the security format, verdict, residual risk
```

## 14. Independent code review
```text
Agent: independent-code-reviewer
Diff: <branch, PR, or working tree>
Task brief: <outcome>
Acceptance criteria: <list>
Tier: <T1 | T2>
Focus: <anything the author is unsure about>
Do not use: the author's summary or conclusions
Return: review report with verdict, blocking findings, missing tests, checks run
```

## 15. Performance investigation
```text
Agent: engineering-lead (-> data-architect for queries)
Symptom: <slow endpoint, query, job, or page; how slow; target>
Measurements: <timings, query counts, EXPLAIN output, traces, or "none yet">
Data volume: <rows, growth>
Constraints: <no behavior change, no new dependency, index lock sensitivity>
Rule: measure first; no optimization without evidence; report before and after numbers
```

## 16. Refactor
```text
Agent: engineering-lead
Target: <module, class, or feature>
Reason: <what hurts today: coupling, duplication, boundary violation, testability>
Behavior: must stay identical
Safety net: <existing tests; add characterization tests first where missing>
Scope limits: <files that must not change; no unrelated cleanup>
Steps: <small, individually reviewable, each leaves tests green>
```

## 17. CI/CD or ops change
```text
Agent: devops-reliability-engineer
Change: <pipeline, container, config, observability, deployment>
Reason: <need or incident>
Environments: <dev | staging | production>
Rollout and rollback: <order, flags, how to undo>
Secrets and access: <what is touched; never paste secrets>
Verification: <how to prove it works without touching production>
Authorization: <no deploy or production change without explicit approval>
```

## 18. Release readiness
```text
Agent: engineering-lead
Release: <version, branch, or change set>
Included changes: <PRs or summary>
Migrations: <list, release order>
Compatibility: <API consumers, previous app version>
Evidence available: <test runs, scans, review reports>
Return: readiness checklist with evidence, risks, and a recommendation (not an approval)
```
