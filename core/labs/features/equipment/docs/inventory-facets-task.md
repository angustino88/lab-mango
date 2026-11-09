# Task: additive relationship-based inventory facets

**Tier:** T2 — additive public API operations and optional list filters.
**Assigned role:** Backend Engineer.
**Authorization/design:** Human owner explicitly authorized implementation in the task request. This equipment pilot supersedes the proposed pilot choices in the all-feature filtering plan; other owners remain out of scope. Specialist and independent review remain required before merge.

## Outcome and acceptance criteria
- Generic and every declaratively generated category collection expose slashless GET `/facets` with required `dimension`.
- Explicit allowlist: category, kind, type, manufacturer, product_model_id, department_id, group_id. No client ORM paths, ordering, or include_ids.
- Only equipment_filter_spec gains optional CSV department_id/product_model_id. Existing public names and payloads remain unchanged.
- Reuse each list's complete membership/search composition before pagination: AND across filters, OR inside CSV, including the requested dimension's own filter.
- SQL counts distinct visible non-deleted equipment IDs; only represented values appear, including retired references and null/unset buckets.
- Buckets use `{value: {id, name} | null, equipment_count}` and standard collection pagination (25 default, 100 maximum); name then ID, null last.
- Test relationships, invalid inputs, counts, pagination, search parity, authorization, query budgets, and all category routes; regenerate schema without overwriting unrelated dirty artifacts.

## Design and scoped files
Equipment-owned `queries/facets.py` declares frozen relationship configuration and DRF-free aggregation. `api/facets.py` removes ordering from a derived list FilterSpec and adds only the required dimension validator. It composes the existing list provider/spec and delegates grouping to the owner query. `api/categories.py` generates adapters from each list view's provider/spec, never category chains. `api/urls.py` wires the generic endpoint. Tests live in `tests/api/test_inventory_facets.py`. Update this feature's architecture and generated equipment/shared schemas where affected. Existing source edits in equipment.py/test_equipment_options.py must remain untouched.

## Authorized reviewer-fix continuation
The continuation explicitly includes `core/common/api/api_views.py` for minimal safe pagination conversion, alongside facet adapter/tests/docs and schema regeneration. Declare integer `page` (minimum/default 1) and `page_size` (minimum 1, default 25, maximum 100); exclude both from membership filters. Bound decimal conversion to DRF IntegerField's existing 1000-character limit and map ValueError to 400 invalid_query with field detail before inventory SQL. No permission or paginator-policy change.

Schema documentation uses the configured project AutoSchema and its existing security-component registration mechanism (the finance endpoint uses the same mechanism). Facets document authenticated JWT/cookie alternatives and API keys: `Authorization: Api-Key <key>` unless `API_KEY_CUSTOM_HEADER` configures a different header. Never put credentials in query parameters. Do not broadly repair other endpoints' authentication schemas.

Reviewer acceptance: all 13 operations expose pagination types/defaults/bounds; every category has positive inventory evidence; parent-only sibling/crossed stored relationships; CSV OR on seven dimensions and OR-within/AND-across; exact list/bucket parity for status, assignment, owner, dates and subtype filters; zero inventory SQL for oversized pagination on both routes/parameters. Preserve unrelated dirty files and unchanged stale computing-signal tests.

## Relationship semantics and frontend
Category → kind → type; category → manufacturer catalog association; (type, manufacturer) → product model; department → group. Facets are inventory projections, not catalog eligibility validation: no active-only joins and no additional hidden parent checks. Stored resource relationships determine membership exactly as on the list. Incompatible selections that match no inventory return empty buckets. Retired referenced values remain visible. Null buckets mean unset relations, not zero or an empty lookup object.

Frontend sends **all current selections and search with every dimension request**, including that dimension's own selection. Counts are conjunctive, not disjunctive. Page controls paginate buckets only; counts never paginate equipment. Use catalog options for create/edit forms. Dependency configuration is internal/documented, not added to existing metadata payloads.

## Non-goals and risks
No migrations, dependencies, permissions, writes, caches, automatic model discovery, catalog-active semantics, or other feature rollout. Preserve HasAPIKey | IsAuthenticated read population. No environment-secret inspection. Existing global read policy is not tightened. Full SQL aggregate cost and icontains scans require representative PostgreSQL profiling; no index claims without measurement.

## Verification required
Focused equipment tests; Ruff lint/format; mypy; architecture tests; Django check; generated OpenAPI and schema lint; whitespace/diff inspection. Record exact results in handoff. Writes/race guards/rollback are not applicable (read-only); rollback removes the additive operations and optional filters, with no data rollback.