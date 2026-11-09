---
description: 'Design and deliver an API contract change'
agent: 'engineering-lead'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: API Change

1. **Design** (API Designer): resource/action, schema, errors, pagination, idempotency,
   concurrency, auth, with the rule table. Classify each change with VER-2.
2. **Breaking?** Deprecation plan per VER-1/VER-3 (no versioned prefix) and human approval.
   Give the frontend owner the exact `openapi/` diff.
3. **Implement** thin view → application command / query; separate input/output serializers.
4. **Schema**: regenerate and lint per `.github/instructions/api-design.instructions.md` steps 4–5;
   attach `git diff -- openapi/`.
5. **Tests**: contract (schema validation), permission matrix, validation errors,
   pagination bounds, idempotent replay, conflict cases.
6. **Security review** (T2): scoping, mass assignment, data exposure, throttling.
7. **Rollout**: additive first; old clients keep working through the deprecation window.
8. **Handoff** includes: schema diff, frontend impact, deprecation dates.
