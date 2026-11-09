---
applyTo: '**/queries/**,**/queries.py,**/selectors*.py,**/serializers*.py,**/api/**,**/tasks*.py'
---
# Query performance and scalability

Owns N+1 prevention, bounded reads, and query budgets. HTTP limits (page size, `/options` cap) are owned by
the response standard COL-1, OPT-6, PRF-1 to PRF-5; this file says how to meet them in code.

## 1. No N+1: the query feeds everything the serializer reads
For each serializer field that touches a relation, the query that feeds it must already provide the data:
| Serializer reads | The query provides | Bad (one query per row) |
|---|---|---|
| FK / one-to-one (`obj.type.name`) | `select_related("type")` | missing `select_related` |
| Reverse FK / M2M list (`obj.items.all()`) | `prefetch_related("items")` or `Prefetch("items", queryset=...)` | |
| Count or exists (`obj.items.count()`) | `.annotate(item_count=Count("items", distinct=True))` / `Exists(...)` | `obj.items.count()` in a `SerializerMethodField` |
| Latest related row (current status) | `Subquery(LATEST.values("status")[:1])` | `obj.status_records.latest()` per row |
| Filtered subset of a prefetch | `Prefetch("items", queryset=Item.objects.filter(active=True), to_attr="active_items")` | `obj.items.filter(active=True)` (ignores the prefetch cache) |
| Generic FK (`obj.resource`) | `prefetch_related("resource")` | |

Repo patterns: `benches/queries/selectors.py::list_benches` (`select_related` + `Count` + `Exists`),
`equipment/queries/equipment.py` (`LATEST_STATUS` subquery).

- `SerializerMethodField` and model `@property` used by serializers never run queries. They read annotations
  or prefetched attributes only.
- Detail endpoints reuse the list query plus `.get(pk=...)` so both paths have the same shape
  (pattern: `get_bench` → `list_benches(...).get(pk=bench_id)`).
- After `prefetch_related`, never call `.filter()`, `.order_by()`, `.exclude()`, `.count()`, `.exists()`, or
  `.first()` on the related manager in Python; each one issues a new query. Use `Prefetch(..., to_attr=...)`.
- Any join that multiplies rows (reverse FK, M2M) inside `Count`/`Sum` uses `distinct=True`, or moves the
  aggregate into a `Subquery`.

## 2. Query budget is a test
- Every list and detail endpoint has a test with `django_assert_num_queries(N)`. N is a constant that does not
  grow with the number of rows (patterns: `core/labs/features/dashboard/tests/api/test_views.py::test_query_budget_bounded`,
  `tests/unit/test_resource_summary_queries.py`).
- The test creates at least 3 rows, each with its related rows, so per-row queries would change the count.
- Raising N in an existing test means stating why in the handoff. Never raise it to make a test pass without
  finding the new query.

## 3. Bounded reads
- Every list goes through the standard paginator (`core/common/api/pagination.py`, max 100) or a documented hard
  cap (OPT-6). Never `list(queryset)` or `len(queryset)` on an unbounded queryset; use `.count()`/`.exists()`.
- Select only needed columns for projections: `.only(...)` / `.values(...)` (pattern: `list_bench_options`,
  OPT-8).
- Filter and aggregate in SQL, not Python. Bad: `[b for b in Bench.objects.all() if b.is_active]`.
- Sorting is deterministic: always end `order_by` with a unique field (`"pk"`, COL-5).

## 4. Batch and background work
- Iterate large tables with `.iterator(chunk_size=2000)`, or with keyset batches (`pk__gt=last_pk`, ordered by `pk`).
  Never OFFSET pagination over a whole table.
- Write in bulk: `bulk_create(..., batch_size=...)`, `bulk_update`, or `queryset.update()`. These skip `save()` and
  signals; if the model relies on them, either call the command per row or set the fields yourself, and say which
  in the handoff.
- A task processes a bounded batch and re-enqueues for the rest; no task loads a whole table into memory.
- Work that may exceed the synchronous budget returns `202` with a status resource (ASY-1).

## 5. Indexes
- A new filter, ordering, or join column used by a list endpoint needs an index on a large table; leading column
  = the most selective filter (`docs/django-model-conventions.md` section 7).
- "This index helps" is a claim; back it with `EXPLAIN (ANALYZE, BUFFERS)` output, or label it
  "reasoned, not measured".
- `icontains` search on large tables is a known full scan; flag it, do not silently add a trigram index
  (that needs `pg_trgm`, a migration, T2).

## 6. Caching
No new cache layer inside a feature task. The cache backend is per-process locmem in tests and Redis in
deployments, so cached data can be stale across instances. A proposed cache states its key, TTL, invalidation
trigger, and what happens on a cache outage (pattern: `core/users/tests/features/auth/test_cache_outage.py`).
