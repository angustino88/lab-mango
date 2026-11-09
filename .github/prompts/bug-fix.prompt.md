---
description: 'Reproduce, root-cause, and fix a bug with a regression test'
agent: 'engineering-lead'
---
Start from the risk tiering in `AGENTS.md`. Report evidence with `docs/ai-team/templates/handoff-report.md`; never claim a check passed unless you ran it and saw the result.

Task: ${input:task:Describe the task, acceptance criteria if known, and relevant files}

# Workflow: Bug Fix

1. **Reproduce** with a failing automated test that captures the reported behavior. If it
   cannot be reproduced, say so and stop guessing; gather evidence.
2. **Locate the root cause**, not the symptom. State it in one sentence with `path:line`.
3. **Assess blast radius**: what else relies on this behavior? Data already corrupted?
   If bad data exists, plan a separate, reviewed data repair (never ad hoc on production).
4. **Tier it** with the AGENTS.md table using the files the fix actually touches, not the size of the bug.
5. **Fix minimally**; no unrelated refactoring.
6. **Prove**: the new test passes, neighbors still pass, gates run. Add a regression test
   for the class of bug when feasible (e.g. a constraint instead of another check).
7. **Review & handoff**: independent review for T1/T2; note any data remediation needed.
