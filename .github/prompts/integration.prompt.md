---
description: 'Design and implement a background job, webhook, or external integration'
agent: 'integration-engineer'
---
# Design and implement a background job, webhook, or external integration

task: ${input:task:Purpose, trigger, input/output, idempotency, failure behavior, volume}

Follow `.github/instructions/async-and-integrations.instructions.md` and AGENTS.md (T2). Inspect the existing task runner first; do not add a new one without an ADR.
1. Define trigger, idempotency key, timeout, retry policy, failure destination, and ownership.
2. Implement behind a small adapter at the boundary; business rules stay in the application layer; enqueue after commit or via the outbox.
3. Test retry, duplicate delivery, partial failure, and timeouts; no real network in tests.
4. Define metrics and alerts. Report with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it.
