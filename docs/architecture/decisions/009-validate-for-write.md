# ADR 009 — Model validation without redundant queries (`validate_for_write`)

- Status: **Proposed** (implemented on the import-performance branch; needs owner approval before merge, T2)
- Date: 2026-11-25
- Risk: T2 (shared write-path behavior used by equipment and downtime writes)
- Scope: `core/common/models/validation.py`; first callers `create_equipment`, `create_profile`,
  `ResourceDowntime.objects.start_now`
- Related: [workbook import performance](../../../core/labs/features/workbook_import/docs/import-performance.md)

## Context

`Model.full_clean()` sends a query for every foreign key ("does the target exist?") and evaluates every
`Meta.constraints` entry with a query. Django wraps each `CheckConstraint` and conditional `UniqueConstraint`
check in a savepoint, so one check costs three statements. Creating one equipment unit cost about 17 validation
statements; opening one downtime window cost 19. In a workbook import these were 54% of all queries.

Most of them cannot fail at that point: the references were just loaded and checked as active, the
`lifecycle_state in (...)` check repeats the field's choices validation, and `ResourceDowntime.clean()` already
raises `ends_at <= starts_at`. PostgreSQL enforces every one of them again on `save()`.
`Resource.save()` (`core/labs/models/resource/base/resource.py`) already skips these queries for the same reason.

## Decision

`validate_for_write(instance, *, skip_constraints=(), skip_unique=())` runs `full_clean()`'s steps in the same
order and raises the same `ValidationError` shape, skipping only:

| Skipped | Why it cannot find an error | Still enforced by |
|---|---|---|
| Existence query of a foreign key whose related instance is loaded, saved, matches the id and has no `limit_choices_to` | The row was read or written in this process | The foreign key constraint |
| `CheckConstraint(field__in=<that field's choices>)` when the value is not empty | `clean_fields` checked the same choices | The check constraint |
| Constraints in the model's `constraints_validated_in_clean` | `clean()` raises the same rule with a field message | The constraint |
| The savepoint and SQL condition check of a conditional `UniqueConstraint` whose condition is only `field__isnull` | Decided on the instance in Python; the duplicate lookup is the same single query and raises the same error | The unique index |
| Constraints the caller lists in `skip_constraints`, unique fields in `skip_unique` | The caller's own logic guarantees them; the call site says why | The constraint or index |

Callers are commands that create rows from validated, loaded references. A view or serializer path keeps
`full_clean()`.

## Consequences

- Equal results: `tests/unit/test_validate_for_write.py` compares the errors with `full_clean()` for valid rows,
  duplicates, soft-deleted duplicates, invalid choices, foreign keys given by id, foreign keys changed after
  loading, `clean()` errors and exclusion overlaps.
- Race behavior is unchanged. The skipped existence query took no lock, and Django's foreign keys are
  `DEFERRABLE INITIALLY DEFERRED`, so a reference deleted by another transaction after the check already failed
  the transaction at commit; it still does. The duplicate-SKU lookup and the downtime overlap guards (row lock,
  then exclusion constraint) are unchanged.
- A new constraint shape is validated by Django as before; only the shapes above take the fast path.
