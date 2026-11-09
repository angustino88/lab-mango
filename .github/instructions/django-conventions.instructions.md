---
applyTo: 'core/**/*.py'
---
# Django and DRF layering

The layout and responsibilities are owned by `docs/architecture/feature-template.md` (sections 2 and 4). This file
lists the checks agents most often get wrong. Existing code that breaks them is drift: report it, do not copy it.

## Layers (checkable)
- **Views** (`api/views.py`) call exactly one application command or one query. A view contains no
  `.objects`, no `transaction.atomic`, no `select_for_update`, and no `except <FeatureError>`.
  Bad: `Bench.objects.filter(room=room)` in a view. Good: `list_benches(actor=actor, room_id=room_id)` from `queries`.
- **Commands** (`application.py` or `application/<verb>_<entity>.py`): every write, including admin actions,
  management commands, and tasks, goes through a command with a frozen input and keyword-only `actor`.
  The command owns the `transaction.atomic` boundary.
- **Policies** (`application/policies.py`): pure `can_*` / `ensure_*` functions; no queries.
- **Queries** (`queries.py` or `queries/`): read-only; apply actor visibility; declare `select_related` /
  `prefetch_related` for every relation the serializer reads.
- **Models**: no imports of features, DRF, Celery, Channels, or settings adapters.
- A layer uses the single-file or the package form, never both in one feature.

## Transactions, locking, idempotency
Owned by `write-safety.instructions.md`.

## Errors
- Commands and queries raise exceptions from the feature's `exceptions.py` (no HTTP status, no DRF imports).
  The central handler maps them to the error envelope (`docs/api/response-standard.md` ERR-1).
- Each feature exception has a class attribute `code` in lowercase `snake_case` that becomes the API error `code`
  (ERR-2), e.g. `BenchConflict.code = "bench_conflict"`. A released code never changes (ERR-2).
- Distinct business failures get distinct exception classes when the client must react differently
  (e.g. `EquipmentAlreadyAssigned` vs `InvalidEquipmentStatus`); do not reuse one `Conflict` with different messages.
- A view lists the feature's conflict exceptions in `conflict_exceptions` (`core/labs/features/base/command.py`)
  instead of catching them itself.

## HTTP base classes (use these; do not build new ones)
| Need | Base | Location |
|---|---|---|
| Endpoint with a declared contract | `AppAPIView` / `AppListAPIView` / `AppDetailAPIView` | `core/common/api/api_views.py` |
| Labs command or selector endpoint | `CommandAPIView` + `operation(...)` | `core/labs/features/base/command.py` |
| List filters | `FilterSpec` / `resource_filter_spec` | `core/common/api/filtering.py`, `core/labs/features/base/resource_filters.py` |
| Pagination | `ResultsSetPagination` | `core/common/api/pagination.py` |
| Role checks | `RolePermission` | `core/common/api/permissions.py` |
New endpoints do not use `ModelViewSet` / `AppModelViewSet`: they bypass the command layer
(drift: `core/jira_integration/features/requests/manage_requests/api.py`).
A new feature starts from the scaffold: `uv run python scripts/scaffolding/scaffold_feature.py <domain> <feature> --entity <name> --dry-run`.

## Serializers
Separate input and output serializers (RW-1). Explicit `fields`; never `"__all__"`. Ownership, role, status,
and audit fields are never writable through an input serializer.

## Signals and `save()`
No new signal or `save()` override that starts a business workflow. Allowed only for technical concerns
(timestamps, cache keys). Event handlers call commands (`handlers.py`).
