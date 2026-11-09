# Django Model Conventions

This is the persistence-specific model standard, subordinate to the
[feature template](feature-template.md) for ownership, dependencies and tests.
It applies to all new Django
models and to files changed during refactoring. Existing database columns, API
payloads, routes, stored identifiers, and legacy model contracts are compatibility
surfaces; preserve them unless an explicit migration and deprecation plan is approved.

## 1. Model Package Structure

Organize models by domain and responsibility, not by one large model module:

```text
core/<domain>/models/
    __init__.py              Public re-exports only
    <feature>/              Plural capability group, owned by one feature
        __init__.py          Entity exports
        base.py              Abstract shared fields and behavior
        <entity>.py          Primary concrete model
        reference_data.py    Controlled lookup/reference models
        assignment.py        Many-to-many or temporal assignment models
        status.py            Lifecycle/status history models
        audit.py             Audit records
```

Use a separate file when a model has a different lifecycle, ownership boundary, or
relationship pattern. Keep closely related small reference models together only when
they share the same domain and migration lifecycle.

Do not create empty layers for architecture's sake. A folder needs only the files the
domain actually uses.

Existing singular/nested model groups are transitional compatibility paths; record
their feature owner instead of renaming imports or migrations solely for style.
Model integrity tests belong under the owning app's tests, feature workflow tests
with the feature, and cross-feature/architecture/deployment tests at project level.

## 2. Naming Rules

### Python

- Modules, fields, methods, variables, and database-facing identifiers use `snake_case`.
- Model, manager, queryset, and form classes use `PascalCase`.
- Constants use `UPPER_SNAKE_CASE`.
- Use singular model names: `Equipment`, `Booking`, `EquipmentAssignment`.
- Use plural reverse names: `bookings`, `assignments`, `status_records`.
- Use `*_at` for timezone-aware datetimes and `*_date` for calendar dates.
- Use `is_*` or `has_*` for booleans, with an explicit default.
- Use `*_id` only for integer/UUID values; use the relation name for model objects.
- Do not use ambiguous names such as `data`, `type`, `value`, or `status` without a
  domain qualifier when the meaning is unclear.

### Relationships

- Foreign keys are singular: `owner`, `project`, `equipment`.
- Many-to-many fields are plural: `licenses`, `compatible_types`.
- Through models use `<source><target>Assignment` or `<relationship>Assignment`.
- Historical models use names ending in `History`, `Log`, or `Record` consistently.
- Use `related_name="%(app_label)s_%(class)s_<role>"` in abstract models to prevent
  reverse accessor collisions.
- Use explicit stable `related_name` values in concrete models.

### Database and API Compatibility

Do not rename a field solely for style. First classify it as internal, persisted, or
public. A persisted or public identifier requires a search across Python, migrations,
admin, serializers, OpenAPI, tasks, and clients, followed by a compatibility plan.
Use `db_column` only for an existing schema integration or documented compatibility
requirement.

## 3. Shared Base Classes

Use the smallest suitable base:

- `TimeStampedModel` for created/modified timestamps.
- `UserStampedModel` when creator and last-modified actor tracking is required. Save
  through explicit actor stamping in application commands, not views. Preserve
  the current model signature via a persistence translation until migrated.
- `ResourceModel` for physical or managed resources that need SKU, ownership, image,
  lifecycle, audit, and timestamped soft deletion.
- `TimestampedSoftDeleteMixin` for new timestamp-based soft deletion outside resources.

Soft-deletable models must use `deleted_at` with the default manager that excludes
deleted rows and an explicit `all_objects` manager for administrative recovery
workflows.

Every abstract base must:

- declare `abstract = True`;
- document the behavior it owns;
- use collision-safe reverse names;
- avoid domain-specific foreign keys unless every subclass shares that relationship.

## 4. Field Design

- Prefer explicit fields over unvalidated JSON for values that are queried, constrained,
  sorted, or joined.
- Use `null=True` for database-level absence and `blank=True` for form/API optionality;
  do not add both without a reason.
- For strings, prefer `blank=True, default=""` when absence has the same meaning as an
  empty value. Use `null=True` only when null has a distinct business meaning.
- Give every boolean an explicit default.
- Use `DecimalField` for measured or financial values; never use floating point for
  persisted quantities requiring exact comparison.
- Use `JSONField(default=dict, blank=True)` only for flexible metadata, never as a
  substitute for a relational entity or a list of foreign-key IDs.
- Add `help_text` when units, lifecycle meaning, or operational constraints are not
  obvious from the field name.
- Keep identifiers immutable where they are used in audit records, URLs, or integrations.

## 5. Relationships and Deletion

Choose `on_delete` from business ownership:

- `PROTECT`: the referenced record must not disappear while history exists.
- `SET_NULL`: the relationship is optional and history remains valid without the target.
- `CASCADE`: the child has no independent meaning and may be removed with its owner.
- `RESTRICT`: deletion may proceed only when Django's restriction rules are satisfied.

Do not use `CASCADE` for audit logs, bookings, status history, or operational records.
Prefer an explicit assignment/history model over multiple nullable foreign keys or arrays
of IDs. Add constraints for rules such as one active assignment per resource.

## 6. Validation and Domain Behavior

Model validation must protect invariants that are true regardless of the entry point:

- implement `clean()` for cross-field validation;
- call `full_clean()` in custom `save()` methods only when the model convention requires
  save-time enforcement, and preserve existing behavior when touching legacy models;
- keep validation deterministic and free of network calls or broad database scans;
- normalize user-entered labels and codes consistently before validation;
- use Django `ValidationError` with field-specific keys;
- use database constraints for uniqueness and race-sensitive invariants whenever possible.

Put workflows, permissions and side-effect orchestration in feature application
commands/policies, and availability reads in queries. Models may expose small pure domain properties and methods,
but should not own transactions spanning unrelated aggregates.

## 7. Constraints and Indexes

Add a constraint when the rule must hold for every writer, including admin, scripts, and
background jobs. Common examples:

- conditional unique constraints for active, non-deleted identifiers;
- `CheckConstraint` for positive quantities and valid ranges;
- unique constraints on assignment pairs;
- conditions that exclude cancelled or deleted records when appropriate.

Index fields in the order used by the most selective common filter, followed by ordering
or range fields. For resource schedules, put the resource foreign key before time fields.
Do not add indexes speculatively; document the query they support.

Use explicit names for constraints and indexes. Names must be unique within the database
and stable across migrations. Abstract models should use `%(app_label)s` and
`%(class)s` placeholders where supported.

Name indexes consistently as `<domain_or_model>_<field_or_purpose>_idx`, using readable
snake_case and the complete field or concept name where it fits. Keep the final database
identifier within Django's 30-character limit, counting every character in the complete
index name, including the `_idx` suffix; when a name would exceed it, shorten the
model/domain stem consistently across related indexes, and use a clear domain synonym
rather than opaque abbreviations. Omit a repeated app prefix such as `labs_` when it adds
no distinction. For compound indexes, include the leading/selective field and a concise
purpose when the full field list cannot fit. Keep related indexes parallel: use the same
model prefix, field ordering, and qualifier vocabulary (for example, do not alternate
between `active` and `live` for the same condition).

## 8. Migrations and Schema Changes

Any field, relationship, constraint, index, or model-table change is a schema change.

Before editing:

1. Search all model, feature, admin, serializer, task, test, and migration references.
2. Decide whether the change is additive, compatible, or breaking.
3. Define data backfill, rollout order, and rollback behavior.
4. Update documentation and tests.

After editing:

- inspect generated migration operations;
- use `makemigrations --check` in CI where the project environment supports it;
- run migration tests against a representative database;
- never edit an old applied migration to change production history;
- do not delete a model file while live code or migrations still import or reference it.

Model-only refactors are allowed only when the persisted schema and public imports remain
compatible. If compatibility is intentionally broken, document the affected imports and
required consumer migration in the change description.

## 9. Managers, QuerySets, and Queries

- The default manager should represent normal application visibility.
- Expose explicit alternate managers for deleted/all records; never hide them behind
  undocumented flags.
- Put reusable filters in typed QuerySet methods with names describing business meaning.
- Use `select_related` for required foreign keys and `prefetch_related` for collections.
- Avoid N+1 queries in serializers, admin lists, and dashboard selectors.
- Keep atomic persistence boundaries in application commands. `transaction.on_commit()`
  is only best-effort dispatch; required notifications/tasks use a transactional
  outbox, retryable dispatch and idempotent consumers. Do not hold database locks
  during external calls.

## 10. Documentation and Tests

Every new model should document, through its class docstring or domain documentation:

- what business entity it represents;
- its ownership and deletion policy;
- its lifecycle/status meaning;
- any non-obvious constraint or relation.

Add tests for:

- required and optional fields;
- `clean()` invariants;
- constraints where practical;
- soft-delete visibility and restore behavior;
- relationship deletion behavior;
- manager/queryset filters;
- application workflows and transaction boundaries.

Use `test_<behavior>.py` modules and `test_<expected_behavior>` function names. Prefer
factories for valid defaults and make exceptional states explicit in each test.

## 11. Review Checklist

Before merging a model change, reviewers should confirm:

- The model is in the correct domain folder and has a clear ownership boundary.
- Names follow this document and existing compatibility names are preserved.
- The selected base class matches the lifecycle and deletion policy.
- Relations use real foreign keys or through models rather than ID arrays.
- `on_delete`, constraints, and indexes reflect business rules.
- Validation is in the model only when it is entry-point independent.
- Writes remain in application commands; reads in queries avoid N+1 behavior.
- Migrations are intentional, reviewed, and reversible where possible.
- Tests cover invariants, relationships, visibility, and changed queries.
- Documentation and public exports are updated, with unused files and exports removed.
