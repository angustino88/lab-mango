---
description: 'Design (generate) architecture for a feature or model group, with Mermaid diagrams'
agent: 'architecture'
---
# Design architecture (GENERATE mode)

Mode: GENERATE. Documentation only; do not change implementation code.
Scope: ${input:scope:Feature or model group to design, with requirements and constraints}

0. Output path: ${input:path:Optional exact path; leave empty to follow docs/ai-team/documentation-map.md}. State the path you choose and why before writing.
1. Inspect the repository first and start with a **Repository facts** block.
2. Follow GENERATE in the architecture agent: requirements and quality attributes, ownership and
   invariants, alternatives when consequential, the smallest design that works.
3. Use `docs/ai-team/templates/feature-architecture-doc.md` and `docs/ai-team/templates/model-group-doc.md`
   (adapt to the repository's documentation conventions), plus an ADR if the decision is hard to reverse.
4. Keep **Proposed** design visibly separate from **Verified** current state; list assumptions and open questions.
5. Define how each boundary rule will be enforced (import-linter contract, architecture test, CI gate).
