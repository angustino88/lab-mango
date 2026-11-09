---
description: 'Implement approved Django models, constraints, migration, and tests from a model design document'
agent: 'backend-engineer'
---
# Implement models from an approved design (T2)

Approved design document: ${input:design:Path to the approved model design doc}
Scope: ${input:scope:Which models/groups to implement now, and anything explicitly out of scope}

This is a T2 change (schema, constraints). Follow `AGENTS.md` and the instruction files for models and migrations.

1. Read the design document and the existing models in the target package. If the design is not marked
   approved, or constraints and the migration plan are missing, stop and report what is needed
   (data-architect first). Do not invent requirements.
2. Implement only what the design specifies: model classes, fields, relationships, database constraints and
   indexes, inheritance exactly as designed, and a migration following expand, migrate, contract.
3. Write tests first or alongside: invalid data rejected by the database, constraint and lifecycle cases, and
   concurrent-writer cases where the design calls for them.
4. Run the quality gates (`docs/ai-team/quality-gates.md`) including `makemigrations --check`; report each as
   passed, failed, or not run. Never run migrations against production.
5. Update the model document: fields and statuses now verified, plus the model coverage check result.
6. Return `docs/ai-team/templates/handoff-report.md`, then hand off to `independent-code-reviewer`.
