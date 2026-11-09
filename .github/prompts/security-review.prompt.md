---
description: 'Security review of a change'
agent: 'security-engineer'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: Security Review

1. Scope the change and list assets, actors, entry points, trust boundaries.
2. Walk authorization: permission class per view, queryset scoping, object-level checks on mutations.
3. Walk data exposure: serializer fields, error bodies, logs, exports.
4. Walk input paths: validation, uploads, outbound URLs (SSRF), deserialization.
5. Check config: secrets handling, CORS/CSRF/session posture, headers, `check --deploy`.
6. Check dependencies and CI credentials.
7. Require the authorization test matrix; run it.
8. Report findings in the Security Engineer format; verdict Pass / Pass with notes / Block.
Never test destructively or against production. State residual risk and limits.
