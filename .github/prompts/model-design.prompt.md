---
description: 'Design (generate) Django model architecture for a domain or model group: ownership, constraints, lifecycle, inheritance, Mermaid'
agent: 'architecture'
---
# Design models (GENERATE mode, documentation only)

Domain and model group: ${input:scope:Domain and model group, e.g. "labs / equipment"}
Requirements, business rules, relationships: ${input:requirements:What the models must represent, key rules and invariants, related domains, hierarchy needs}
Output path: ${input:path:Optional exact path; leave empty to follow docs/ai-team/documentation-map.md}

Do not change implementation code. Start with a **Repository facts** block, then:

1. Inspect the existing models, migrations, and docs for the scope. Decide and state the output path and why.
2. Define for every model: responsibility and owner, fields, keys, relationships and cardinality, constraints
   and indexes (database-enforced vs application-enforced), lifecycle, deletion and audit history,
   concurrency needs, query patterns, migration notes.
3. Keep lifecycle, assignment, booking, runtime-activity, and financial concepts as separate models or state
   machines; never merge them because the fields look alike.
4. Inheritance: prefer composition. If a hierarchy is justified, state the kind (abstract, multi-table, proxy,
   mixin), why, the invariants subclasses honor, and its query and migration cost.
5. Produce the document from `docs/ai-team/templates/model-group-doc.md` (and the catalog if that layout is
   adopted), with Mermaid `erDiagram`, `classDiagram` for hierarchies, and `stateDiagram-v2` for lifecycles.
6. Mark **Proposed** design separately from **Verified** current state; list assumptions and open questions.
7. Finish with the model coverage check and the next step (data-architect for constraints and migration plan,
   then `/model-implement` once the owner approves).
