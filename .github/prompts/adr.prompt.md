---
description: 'Write an Architecture Decision Record'
agent: 'architecture'
---
# Write an Architecture Decision Record

decision: ${input:decision:The decision, context, options considered, decision owner}

Use `docs/ai-team/templates/adr-template.md`. Decide the path via `docs/ai-team/documentation-map.md` (default `docs/architecture/decisions/NNN-short-title.md`) and state it.
1. Inspect existing ADRs and the code the decision affects; do not invent context.
2. Record the decision, at least two realistic options with trade-offs, and consequences (compatibility, operations, security).
3. Define enforcement: import-linter contract, test, or CI gate.
4. Status is Proposed until the decision owner accepts it. Documentation only.
