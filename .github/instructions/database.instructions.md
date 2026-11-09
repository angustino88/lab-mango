---
applyTo: '**/models/**,**/models.py,**/migrations/**,**/queries*.py,**/queries/**'
---
# Database rules (PostgreSQL / Django ORM)

Model placement, naming, base classes, field design, `on_delete` choice, and index naming are owned by
`docs/django-model-conventions.md`. This file owns integrity enforcement, concurrency, migrations,
and inheritance kind. Do not restate the conventions document; cite its section.

## Integrity
- Each invariant in the design note names its guard: `CheckConstraint`, conditional `UniqueConstraint`,
  `ExclusionConstraint` (needs `btree_gist`), FK, or "application only: <reason PostgreSQL cannot express it>".
  Example: "one active assignment per bench" → `UniqueConstraint(fields=["bench"], condition=Q(unassigned_at__isnull=True))`.
- An application check before a write (`if X.objects.filter(...).exists(): raise ...`) is not a guard by
  itself. It must run under a lock taken by every competing writer, or be backed by a constraint.
- Soft-deleted rows must not block reuse: unique constraints on soft-deletable models include
  `condition=Q(deleted_at__isnull=True)`.
- Booking windows are half-open ranges; money is `DecimalField` plus a currency field.
- `CASCADE` is forbidden on the record types listed in `docs/django-model-conventions.md` section 5.

## Concurrency and queries
Race guards, locking, and idempotency: `write-safety.instructions.md`. N+1, query budgets, bounded reads, and
indexes: `query-performance.instructions.md`.
- Constraint names are stable and unique: application code maps `IntegrityError` by constraint name, so renaming
  a constraint is a breaking change for that code (search for the name before renaming).
- Where an idempotency key or dedupe key exists, its uniqueness is a `UniqueConstraint` covering the full scope
  (e.g. `fields=["actor", "operation", "key"]`), never a global `unique=True` on the key alone.

## Model documentation
A change to model fields, constraints, relationships, or inheritance updates the domain's model document in
the same change. Find its path in `docs/ai-team/documentation-map.md` (Labs:
`core/labs/models/docs/labs-model-architecture.md`). Never write model docs under repo-level `docs/`.

## Migrations (expand → migrate → contract)
1. **Expand**: add nullable columns/new tables/indexes concurrently (`AddIndexConcurrently`,
   `NOT VALID` then validate for large-table constraints). Old app version must keep working.
2. **Migrate**: backfill in batches, idempotent, resumable, outside the schema migration,
   with a reverse path or documented irreversibility.
3. **Contract**: after all app instances use the new shape, drop old columns/constraints in a later release.
- Set a lock timeout for schema changes; avoid long `ACCESS EXCLUSIVE` locks.
- One concern per migration. Never edit applied migrations. Squash only with a plan.
- CI runs `makemigrations --check` and applies migrations on PostgreSQL.
- Every migration in the change states its rollback in the handoff (reverse operation, or "irreversible: why").

## Model inheritance
Prefer composition (FK or OneToOne) unless the subtype truly "is a" base with the same invariants. Keep hierarchies
shallow (typically two levels; justify more) and give each base class exactly one owner.
- **Abstract base**: shared columns and technical behavior, no table. Constraint and index names declared on an
  abstract base must include `%(app_label)s_%(class)s` so child names do not collide.
- **Multi-table inheritance**: each level has its own table and an implicit one-to-one parent link; reads join,
  constraints live per level, and queries return base instances unless resolved to the subtype. Costly on large
  hierarchies and hard to change later: record the choice in an ADR.
- **Proxy**: behavior, ordering, or manager changes only; no schema change.
- **Mixin**: technical behavior only (timestamps, audit); no business rules.
- **Single table with a type discriminator**: only with check constraints that force type-specific columns to be
  null or not null per type.
- Subtypes must honor the base's invariants and never weaken its constraints.
- Do not share a base across distinct concepts (lifecycle, booking, assignment, activity, payment) just because
  their fields look alike.
- Changing the inheritance kind of a populated model is a migration project: plan expand/migrate/contract.

## Ownership scope
If data is scoped by lab, group, or owner, the scope key is a real indexed column and queries filter on it.
