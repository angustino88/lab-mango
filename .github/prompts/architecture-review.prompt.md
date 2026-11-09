---
description: 'Review module boundaries and dependency direction'
agent: 'architecture'
---
Mode: REVIEW (read-only). Scope and depth: ${input:scope:Feature/model group to review, and Quick, Standard or Deep}
Report in the architecture agent's REVIEW format (`ARCH-NNN` findings) and its section 10 final response.

# Workflow: Architecture Review

**Inputs**: requirements and constraints, current layout and import graph, existing ADRs
and import rules, expected near-term changes from the product owner.

1. Describe the current design from repository evidence.
2. Identify responsibility boundaries and dependency direction; list violations with `path:line`.
3. Find concrete coupling, duplication, and change-propagation risks.
4. Compare at least two viable options when the decision is consequential, including
   "smallest change". Evaluate complexity, migration cost, testability, operations.
5. Recommend the smallest defensible change and an incremental migration path.
6. Define enforcement (architecture test under `tests/architecture/`, import-linter contract, CI gate).
7. Recommend an ADR for long-lived decisions; do not write it in REVIEW mode (use `/adr`).
**Do not**: redesign everything for a local problem, treat a pattern as proof of quality,
add speculative abstractions, or claim the repo follows a pattern before inspecting it.
