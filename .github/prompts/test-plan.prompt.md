---
description: 'Plan and write tests that prove behavior and invariants'
agent: 'qa-engineer'
---
# Plan and write tests that prove behavior and invariants

target: ${input:target:Feature, endpoint, model, job, or diff; acceptance criteria or invariants}

Follow `.github/instructions/testing.instructions.md`.
1. Map each acceptance criterion and invariant to tests (criterion, test, result table).
2. Pick the cheapest layer that proves it; use PostgreSQL; cover positive, negative, boundary, permission-denied, duplicate/retry, invalid transitions, and concurrent conflict where state is contested.
3. Check test quality: would each test fail if the code were wrong?
4. Report exact commands and outcomes (passed, failed, skipped, not run).
