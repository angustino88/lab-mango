# Catalog and Selector API Standard

**Revises:** ADR 002, Separate selectors from catalogs and imports **Status:** Proposed. Not an implemented or approved API contract. **Date:** 2026-11-01 **Decision owner:** Human owner (pending) **Scope:** Labs lookup resources and Support Desk selectors

## 1. Summary

This document defines one consistent, mechanically enforceable way to expose lookup data (projects, manufacturers, vendors, cities, ticket priorities, and so on) across every domain. It separates three concerns that are currently mixed:

1. **Selector**: a small, bounded list used to fill a dropdown (`GET <resource>/options`).
2. **Catalog**: a paginated, filterable, readable collection of the same entity (`GET <resource>`, `GET <resource>/{id}`).
3. **Import**: an authorized bulk write (`POST .../reference-data/<segment>`), left unchanged.

It revises ADR 002 in four places:

- It replaces the judgment-based naming rule with a mechanical one, so every domain produces the same style of route.
- It requires a decision on `sku` for name-only catalogs instead of leaving it open.
- It requires a search parameter and a per-resource cap policy for selectors, because a hard 400 on overflow breaks dropdowns as data grows.
- It adds a way for edit forms to show retired selected values without a detail call per field.

Nothing here changes production behavior. Every path is a proposal until the human owner approves the route ledger.

### Alignment with the binding standards

This revision is aligned with the [response standard](../../ai-team/api/response-standard.md) and the [request standard](../../ai-team/api/request-standard.md). Where this document and those standards differ, the standards win until the owner approves the amendments in section 19. Specifically, this document does **not** introduce a second envelope, error format or caching policy:

| Topic | Governing rule |
| --- | --- |
| Success envelope `{"data": ..., "meta": ...}` | ENV-1, ENV-2, OPT-2 |
| Error envelope `{"error": {code, message, details, request_id}}` | ERR-1, ERR-11 |
| Pagination in `meta.pagination` | COL-2 |
| Unknown or invalid query parameter: `400 invalid_query` | COL-4, QRY-1 |
| Selector overflow: `400 too_many_results` | OPT-6 |
| Caching of authenticated JSON: `private, no-cache` plus `ETag` | CCH-1, CCH-2 |

Placement: the file name does not follow the documentation map pattern `NNN-short-title.md`, and it overlaps [ADR 002](002-selector-and-catalog-api.md). On acceptance it should become `003-catalog-and-selector-api.md` with ADR 002 marked "Superseded by ADR 003" (owner decision; not done here).

## 2. Context

The verified state from ADR 002 still applies:

- The common factory binds owner-declared `GET` collection/detail and `POST` import routes. An import collection is not a dropdown.
- Equipment has 17 import segments under `equipment/reference-data/{segment}`. `equipment/options` selects assets, not manufacturers or models.
- Bench bookings imports projects and exposes `lab-projects` and `lab-projects/{id}` reads, with no project options route.
- Benches, licenses and locations have import segments and some direct catalog routes. Aggregate `*/reference-data` responses and `licenses/filters` are not selectors.
- Support Desk has `<resource>/options` for five resources, `admin/<resource>` for management, and three inverse compatibility aliases (`options/categories`, `options/priorities`, `options/statuses`).
- Labs routes live under `/api/labs/`; Support Desk routes live under `/api/support/`.

This inventory covers the named owner groups, not every API or frontend consumer. A consumer audit is still outstanding.

### Problems this standard solves

| Problem | Effect |
| --- | --- |
| Several surfaces answer "give me the list of X" (import collection GET, aggregate, filters, options) | Clients pick inconsistently; behavior diverges |
| No selector for projects, makers, models, vendors, cities | Each form builds its own query or over-fetches |
| OPT-2 requires `sku`, but most catalogs have no stable secondary identifier | Selectors stall on schema debates |
| Naming differs by owner (`lab-projects`, `bench-groups`, `station-types`, bare `categories`) | New domains copy whichever example they saw first |
| Support uses `admin/<resource>` for management; Labs has no convention | Two management styles |

## 3. Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | One flat route shape for all domains: `/api/<root>/<resource>` and `/api/<root>/<resource>/options`. | Uniform, no nesting, no owner-specific exceptions. |
| D2 | `<resource>` is `<subject>-<plural-noun>`, where `<subject>` is the parent domain noun. Existing routes are kept. Bare nouns require an owner-approved allowlist. | A mechanical rule gives the same answer for every author. |
| D3 | Never nest a catalog under another resource. Relationships are query parameters. | URL depth would imply a dependency that does not exist. |
| D4 | `/options` is a sibling resource, never a query mode of the list. | One meaning per surface. |
| D5 | Selector items contain exactly `id`, `sku`, `name`. `sku` is a string or `null` where no stable identifier exists, **pending owner approval of a standard amendment** (sections 8 and 19.2). Enums get no selector (section 6.4). | Avoids inventing identifiers and avoids blocking on migrations. |
| D6 | Selectors accept `q` and, for large catalogs, require a parent filter. Overflow handling is defined per resource (section 7.3). | A bare 400 at a global cap breaks dropdowns as data grows. |
| D7 | Retired selected values are rendered via `include_ids` on options and via detail reads. | Edit forms render history without making retired rows selectable. |
| D8 | Management writes use the same flat collection URL, gated by permission. Support's `admin/` routes are kept until clients are enumerated, then deprecated. | One convention going forward without an unplanned break. |
| D9 | Imports remain a separate, unchanged surface. | No regression to importer clients. |

## 4. Route rules

These rules apply to every domain and are enforced by a contract test (section 12).

| # | Rule |
| --- | --- |
| R1 | Path is `/api/<root>/<resource>[/options]`. `<root>` is `labs` or `support`. The owning feature is not in the URL. It is recorded in the route registry and in the OpenAPI `x-owner` extension. |
| R2 | `<resource>` is `<subject>-<plural-noun>`. Allowed exceptions: routes that already exist, and nouns on a short allowlist reviewed by the owner. |
| R3 | No nested catalog paths. `/equipment/manufacturers` and `/equipment/{id}/manufacturers` are both disallowed. |
| R4 | One owner per resource. Other features consume it through `/options` and never redeclare it. |
| R5 | Names are lowercase, hyphen-separated, plural, and unique within a root. The name is reserved for its `/options`. |
| R6 | `options` is registered before `{id}`, and `{id}` uses a typed converter, so the two cannot collide. |
| R7 | Slashless paths. Trailing-slash aliases are not added. |

### Why not `/equipment/manufacturers`

`equipment` is already a resource (`equipment`, `equipment/options`, `equipment/{id}`) and means assets. Nesting makers under it makes the same prefix mean two things, risks a routing collision with `{id}`, and implies manufacturers belong to asset instances when they are shared lookups linked to categories. The qualified flat name avoids all three.

### Cross-domain ownership

A resource belongs to one feature but is available to every form. Projects are owned by bench bookings, yet a support or equipment form calls `/api/labs/lab-projects/options`. The URL does not move with the consumer.

## 5. Route ledger (proposed)

All Labs paths are relative to `/api/labs/`; Support Desk paths are relative to `/api/support/`. A `?` marks a candidate that needs the decision in the last column. Existing import paths stay as they are.

| Root | Owner | Catalog → selector | Existing surface retained | Decision before implementation |
| --- | --- | --- | --- | --- |
| labs | Bench bookings | `lab-projects` → `lab-projects/options` | `bench-bookings/reference-data/projects` (import) | Nullable `code` as `sku`; eligibility by booking date and active state; user scope |
| labs | Equipment assets | `equipment` → `equipment/options` (existing) | `equipment/reference-data` aggregate | Keep category-specific asset selectors only if consumers need them; fix cap and slash alias |
| labs | Equipment taxonomy | `equipment-categories`, `equipment-kinds`, `equipment-types` → each `/options`? | `equipment/reference-data/{categories,kinds,types}` | Category key versus ID; parent filter names; `sku` source for kind and type |
| labs | Equipment makers and models | `equipment-manufacturers`, `equipment-product-models` → each `/options`? | `equipment/reference-data/{manufacturers,product-models}` | Name-only rows; manufacturer-to-category M2M; model filters by manufacturer and type |
| labs | Other equipment catalogs | One qualified collection per registered segment; `/options` only when selectable | The remaining equipment import segments (specification definitions, interfaces, materials, display sizes and resolutions, networking protocols, sample customers and characteristics, technical users, departments, resource groups) | Which are selector targets; no automatic selector for specification values; ownership of departments and resource groups across features |
| labs | Benches | `benches` (existing options), `bench-groups`, `bench-types` → each `/options`? | `benches/reference-data/{groups,types}`; aggregate | Whether groups and types need selectors; `sku` source |
| labs | Licenses | `licenses`; `license-vendors`, `license-products`, `license-types`, `license-categories`, `license-restrictions` → each `/options`? | `licenses/reference-data/*`; `licenses/filters` | Which are used in write forms; product filter `vendor_id`; `sku` source |
| labs | Locations | `location-countries`, `location-cities`, `location-buildings` → each `/options`?; `station-types` (existing); `rooms`, `stations` only if selectable | `locations/reference-data/*`; aggregate `stations/reference-data` | Allowlist decision on bare nouns; country code as `sku`; parent filters `country_id`, `city_id` |
| support | Tickets | `categories`, `priorities`, `statuses`, `teams`, `labels` → each `/options` (existing) | `admin/<resource>`; three inverse aliases | Enforce cap; distinguish derived `sku` types (rank, state, name); permission comparison between admin and read paths; alias retirement plan |

The ledger accounts for all 17 equipment, five license, four location, two bench and one project import segments. It does not assume all of them need selectors.

## 6. Shared conventions

### 6.1 Query parameters

| Purpose | Name | Applies to |
| --- | --- | --- |
| Text search | `q` (1 to 100 characters, case-insensitive, matches `name` and `sku`; QRY-7) | list, options |
| Parent filter | `<relation>_id` (NAM-6), for example `country_id`, `vendor_id`, `category_id`; multi-value `category_id=3,7` (QRY-2) | list, options |
| Active state | `is_active` (`true` or `false`; QRY-3). Absent on options means active only. `is_active=false` requires manage permission | list |
| Retired selected values | `include_ids` (comma-separated positive integers, maximum 50, no duplicates; TYP-15) | options |
| Paging | `page` (at least 1), `page_size` (1 to 100, default 25) | list |

Rules that close drift seen in existing selectors (section 20):

- **One name per filter.** `q` is the only search parameter; `search` is not accepted on new endpoints. A filter has exactly one name (`bench_group_id`, never also `bench_group`). Aliases are breaking to remove, so they are never added.
- **No empty values.** `?q=` returns `400 invalid_query` (QRY-4); query serializers do not use `allow_blank=True`.
- **Same validator as the list.** The options query serializer is the list query serializer minus paging, plus `include_ids` (OPT-5). It is declared once and reused, not copied.
- Unknown or malformed parameters return `400 invalid_query` (COL-4, QRY-1). Ordering is fixed (`name`, then `id`; OPT-7) and there is no `ordering` parameter on options.

### 6.2 Catalog list response

```json
{
  "data": [
    {
      "id": 41,
      "name": "Bosch",
      "categories": [{"id": 3, "name": "Computing"}, {"id": 7, "name": "Measurement"}],
      "is_active": true,
      "created_at": "2026-03-02T09:14:00Z",
      "updated_at": "2026-09-18T13:02:11Z"
    }
  ],
  "meta": {
    "pagination": {"count": 1, "page": 1, "page_size": 25, "next": null, "previous": null}
  }
}
```

Envelope per ENV-2 and COL-2. Relations are read as `{id, name}` objects (REL-3, REL-9) and written as `<relation>_ids` (NAM-6). Audit fields apply to reference catalogs only; controlled vocabularies carry none (STR-8, section 6.4). Fields beyond `id`, `name` and `is_active` vary by resource and are documented in OpenAPI.

### 6.3 Selector response

```json
{"data": [{"id": 41, "sku": null, "name": "Bosch"}]}
```

- Always the `data` envelope (ENV-1, OPT-2). Never a bare array; an empty match is `{"data": []}`.
- Exactly three keys, never more.
- Active rows only, plus any rows named in `include_ids` that the caller may read.
- Fixed ordering by `name`, then `id`.
- Visibility is never wider than the matching list and detail.

### 6.4 Lookup classes

REL-5 requires lookup ids to be seeded with fixed values identical in every environment. That fits code-adjacent vocabularies but not catalogs that users import at runtime (manufacturers, product models, projects). Every resource in the ledger declares one class:

| Class | Examples | Identity | Audit fields | Write surface | Selector `sku` |
| --- | --- | --- | --- | --- | --- |
| **Enum** (fixed in code, drives behavior; ENU-5) | audit result, booking status | `value` string | none | none | not applicable: no `/options`; exposed as `{value, label}` in filter metadata or schema |
| **Controlled vocabulary** (admin-managed data, small; REL-5) | ticket priorities, statuses, license types, station types | seeded fixed `id` | none (STR-8) | seed migration or admin | stable `code` if one exists, else per section 8 |
| **Reference catalog** (user-imported or user-created, may grow) | manufacturers, product models, projects, cities, buildings | database `id`, not seeded | `created_at`, `updated_at` (STR-2) | import or owner-approved management contract | natural code if one exists, else per section 8 |
| **Primary resource** | equipment, benches, rooms, stations | database `id` | full | its own CRUD contract | business identifier (asset SKU) |

An enum never gets a `/options` route with synthetic integer ids. Selector shape is identical for the last three classes; only the `sku` source and seeding rules differ.

## 7. Selector contract

### 7.1 Mapping

| Selector key | Source | Rule |
| --- | --- | --- |
| `id` | Stored identity | Immutable primary key |
| `sku` | A documented secondary identifier | Nullable if none exists (D5). No invented column or stringified surrogate. |
| `name` | Display text | The label shown to the user |

For each approved selector, the registry records the `sku` type, its source, and whether it is stable. Support Desk needs a review first: its `sku` values may be a rank, a system state, or a label name rather than an immutable identifier.

### 7.2 Dependent dropdowns

Parent relationships are expressed with declared query parameters, never with path depth. Candidates to assess, not approved rules:

- Equipment category, then kind, then type.
- Manufacturer by category; product model by manufacturer and type.
- License product by `vendor_id`.
- City by `country_id`; building by `city_id`.
- Project eligibility by booking date and active state.

Filters on many-to-many relations must not return duplicate rows.

### 7.3 Size and overflow policy

The response standard calls for an unpaginated selector with a hard cap and a 400 on overflow. A single global cap will fail as catalogs grow, so each resource declares one of:

| Class | Meaning | Behavior |
| --- | --- | --- |
| Small, stable | Fits comfortably under the cap (priorities, statuses, license types) | Returns all active rows |
| Large, growing | May exceed the cap (cities, buildings, product models, projects) | A parent filter or `q` is required; a request with neither returns `400 invalid_query` with `details[].field` naming the missing parameters. A request that would exceed the cap returns `400 too_many_results` (OPT-6) |

The cap is a single project constant (OPT-6 example: 1000) defined once in `core/common/api`, overridable downward per resource. Implementation fetches `cap + 1` rows and fails if the extra row exists; it never counts the whole table and never truncates. A metric counts `too_many_results` responses so growth is visible before it breaks a form. Moving a resource from "small" to "large" adds a required parameter and is therefore breaking (VER-2): classify conservatively at first release.

### 7.4 Retired values

A form editing an existing record must display a value that has since been retired. The client passes the current IDs as `include_ids`. The server returns the active matching rows plus those IDs if the caller may read them; IDs the caller may not read, or that do not exist, are silently omitted (no existence leak, REL-11). `include_ids` rows are not subject to `q` or parent filters, count toward the cap, and are merged into the fixed `name, id` order. Because OPT-4 forbids an `is_active` key, the client marks as "retired" any returned ID it requested in `include_ids` that it did not see in a plain request; if the UI needs the flag directly, it uses the detail endpoint. Writes still reject retired IDs with `422 does_not_exist` or a documented `inactive` code, so `include_ids` never makes a retired value submittable for new records.

## 8. SKU decision (blocking)

OPT-2 requires `{id, sku, name}`, but name-only catalogs have no meaningful `sku`. The owner must choose one default:

| Option | Description | Trade-off |
| --- | --- | --- |
| A | Amend the standard: lookup selectors return `{id, name}`, matching REL-5 | Cleanest; two selector shapes exist (assets keep `sku`) |
| B | Keep three keys; `sku` is nullable for lookups | One shape; clients must handle null |
| C | Add a stable code column to each catalog | Uniform and meaningful; migrations, backfills and duplicate-identity risk |

**Recommendation: B**, with **C** only where a real code already exists (country ISO code per FMT-9, support category/team `code`, license product code, project `code` once its nullability is resolved).

Why B over A: OPT-2 says the key set is "fixed for every options endpoint" so that one frontend component and one OpenAPI schema (`CatalogOption`) serve every dropdown. Option A creates two selector shapes and forces every consumer to know which class a resource is. B costs only a nullable type, which OPT-2 does not forbid but does not state either; the amendment in section 19 makes it explicit.

Hard rules regardless of option:

- `sku` is always a **string or `null`** (FMT-5). Never an integer in one selector and a string in another.
- `sku` must be stable: never derived from mutable display text, rank or a sort position. Current violations: Support Desk priority `sku = rank`, label `sku = name` (section 20).
- No stringified surrogate (`"sku": "41"` duplicating `id`), no invented column.
- `sku` is display and search aid only (OPT-3). Clients never submit or branch on it; writes use `id`.
- A `code` that exists only to fill `sku` is not added. If a stable code is genuinely needed, the Data Architect owns a reversible migration plan.

This decision gates every new selector in the ledger.

## 9. Errors

Errors use the project envelope (ERR-1, ERR-11); no other format is introduced. Example of a selector query failure:

```json
{"error": {
  "code": "invalid_query",
  "message": "One or more query parameters are invalid.",
  "details": [
    {"field": "include_ids", "code": "max_items", "message": "Ensure this list has at most 50 items."},
    {"field": "sort", "code": "unknown_field", "message": "Unknown query parameter."}
  ],
  "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f90"
}}
```

| Status | `code` | Trigger |
| --- | --- | --- |
| 400 | `invalid_query` | Unknown, repeated, empty or malformed parameter; bad `include_ids`; missing required parent filter for a large catalog (COL-4, QRY-1, QRY-4) |
| 400 | `too_many_results` | Selector result would exceed the cap (OPT-6) |
| 401 | per SEC-1 | Missing or invalid credentials, with `WWW-Authenticate` |
| 403 | `insufficient_scope` | Lacks view permission, or `is_active=false` without manage rights (SEC-16) |
| 404 | `not_found` | Missing or hidden detail. Use 404, not 403, to avoid revealing existence (ERR-5) |
| 429 | per SEC-10 | Includes `Retry-After` |

Error responses carry `Cache-Control: no-store` (CCH-1).

## 10. Security

- A selector must not grant access to data hidden by its list or detail, and must not weaken object scope.
- Selectors are read-only and do not change import permission, idempotency or concurrency guards.
- Catalog management writes need their own owner-approved contract. Neither `PATCH` nor `DELETE` is implied by the presence of `/options`.
- API-key-only callers get an explicit permission per resource, never a default grant.
- The Security Engineer confirms, per resource, who may list, select, import and manage, including inactive and historical access.
- Do not infer write permission from current import reads.

## 11. Caching, performance and observability

| Area | Requirement |
| --- | --- |
| Caching | `Cache-Control: private, no-cache` with a strong `ETag` over the serialized body; `If-None-Match` returns `304` (CCH-1, CCH-2). `Vary: Accept-Language` because `name` may be localized (I18N-1, CCH-4). Any `max-age` is a per-resource exception approved by the owner, never a default, because selectors are permission-scoped. |
| Query cost | One query, selecting only `id`, `sku` (annotated) and `name`; relation filters use `Exists(...)` so M2M filters never duplicate rows and need no `distinct()` (OPT-8). Query count asserted equal for 1 and 100 rows (PRF-2). |
| Search | `q` uses `icontains` on `name` and `sku`. A large catalog with `q` needs a trigram (`pg_trgm` GIN) index; that is a migration and goes through the Data Architect. |
| Indexes | Index supporting `ORDER BY name, id` filtered on `is_active`; indexes on FK and join-table columns used by parent filters. |
| Targets | Proposed p95 under 150 ms for list and under 100 ms for options on production-sized data (not measured). |
| Observability | Structured log with `request_id`, actor, route, status, latency (OBS-3); metric for `too_many_results`; metric for `304` ratio. |

## 12. Enforcement

Proposed: one architecture test, `tests/architecture/test_options_contract.py` (pattern of the existing `tests/architecture/test_import_boundaries.py`), iterates the resolved URL patterns and the generated OpenAPI, so a non-conforming route fails CI instead of relying on review. Existing violations go into an explicit allowlist in the test that may only shrink (section 20):

- Every path ending in `/options` is `GET`-only and its 200 schema is `{data: CatalogOption[]}` by `$ref`, not an inline copy.
- Names match R5 and are unique within a root; no `options/<resource>` inverse path and no `select-list` path exists.
- Every `/options` has a sibling list route and a declared `x-owner`.
- `options` resolves before `{id}`; a `GET` on options never dispatches the import command.
- No catalog path is nested under another resource.
- No path ends in `/` (TRN-4, PTH-5).
- Options query serializers declare no `search`, no `ordering`, no paging parameter and no `allow_blank=True` field.

Per-resource tests cover:

- Exact keys and types for list, detail and options; `sku` is `str` or `None`.
- Stable ordering with an `id` tie-break, and no duplicates under many-to-many filters.
- Unknown parameter returns `400 invalid_query`; overflow returns `400 too_many_results` (use a monkeypatched cap, as `core/labs/features/benches/tests/test_select_list_options.py` already does).
- Hidden, inactive and historical objects for each permission level.
- Query counts equal for 1 row and for 100 rows.
- Import regression: POST semantics and idempotency unchanged.

## 13. Compatibility and rollout

Rollout is phased so additive work is not held up by breaking work.

| Phase | Content | Breaking? |
| --- | --- | --- |
| 0 | Decisions: SKU (section 8), naming allowlist, management convention, caps. Audit of frontend and importer consumers and route collisions. Reconcile with the API response redesign document. | No |
| 1 | Add shared selector base (section 14) and the architecture test with the current-violation allowlist. Migrate `benches/options` (closest to target) as the reference implementation. | No |
| 2 | Add missing selectors and catalogs (projects, makers, models, vendors, cities, and so on). New endpoints are non-breaking (VER-2); no feature flag needed. Imports untouched. | No |
| 3 | Fix existing selectors: add cap to Support Desk and equipment options, add `q`. Accept `search` as a deprecated alias for one release (VER-3). | No |
| 4 | Remove aliases (`search`, duplicate filter names, `options/<resource>`, `equipment/options/`), unstable `sku` derivations and `admin/` routes after enumerating clients, in one coordinated release under ADR 001 with published schema and changelog. Replace audit-result `/options` with enum metadata. | Yes |

No automatic `/api/v2/`. No production migration or access change follows from this document alone.

## 14. Shared implementation

Today each feature re-implements the selector (three `OptionSerializer`/`*OptionsSerializer` classes, one cap constant in benches only). Proposed: a thin helper in `core/common/api`, consistent with ADR 001 and explicitly not a model-discovery framework. `core/common` imports no business app (AGENTS.md rule 3):

- `CatalogOptionSerializer`: exactly `id` (int), `sku` (`CharField(allow_null=True)`), `name`; component name `CatalogOption`, so every options endpoint `$ref`s one schema.
- `OptionsQueryMixin`: adds `q` (1 to 100, no blank) and `include_ids` (TYP-15) to a feature's list query serializer.
- `OptionsAPIView` base: validates the query, calls the feature selector, applies `cap + 1`, merges `include_ids`, sets `ETag`, and returns the envelope or `too_many_results`.
- `OPTIONS_MAX_RESULTS`: the single cap constant.

Each feature supplies only a selector function in its `queries/` layer returning a queryset annotated with `sku`, its query serializer, its permission class and `x-owner`. The view never builds a queryset itself. OpenAPI is regenerated from code only after approved implementation.

```python
# Proposed shape, feature side (illustrative, not implemented)
class ManufacturerOptionsAPIView(OptionsAPIView):
    query_serializer = ManufacturerOptionsQuerySerializer  # list filters + OptionsQueryMixin
    permission_classes = (CanViewEquipmentCatalogs,)
    owner = "equipment"

    def select(self, *, actor, filters):
        return selectors.manufacturer_options(actor=actor, **filters)  # .annotate(sku=...).only(...)
```

## 15. Worked example: equipment manufacturers

### Surfaces

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/labs/equipment-manufacturers` | Paginated catalog |
| GET | `/api/labs/equipment-manufacturers/{id}` | Detail, including inactive for permitted callers |
| GET | `/api/labs/equipment-manufacturers/options` | Bounded selector |
| POST | `/api/labs/equipment/reference-data/manufacturers` | Existing import, unchanged |

### List

```
GET /api/labs/equipment-manufacturers?category_id=3&q=bos&page=1&page_size=25
```

Parameters: `q`, `category_id`, `is_active`, `page`, `page_size`. Ordering `name`, `id`. Response as in section 6.2.

### Options

```
GET /api/labs/equipment-manufacturers/options?category_id=3&q=bos&include_ids=58
```

```json
{"data": [
  {"id": 41, "sku": null, "name": "Bosch"},
  {"id": 58, "sku": null, "name": "Boston Dynamics"}
]}
```

Row 58 is retired and appears only because it was named in `include_ids`. `sku` is null pending the section 8 decision.

### OpenAPI fragment

```yaml
/api/labs/equipment-manufacturers/options:
  get:
    operationId: listEquipmentManufacturerOptions
    x-owner: equipment
    parameters:
      - {name: q, in: query, schema: {type: string, minLength: 1, maxLength: 100}}
      - {name: category_id, in: query, schema: {type: integer, minimum: 1}}
      - {name: include_ids, in: query, style: form, explode: false,
         schema: {type: array, maxItems: 50, uniqueItems: true, items: {type: integer, minimum: 1}}}
    responses:
      "200":
        headers: {ETag: {schema: {type: string}}}
        content:
          application/json:
            schema: {$ref: "#/components/schemas/CatalogOptionList"}
      "304": {description: Not modified}
      "400": {$ref: "#/components/responses/Error"}
      "403": {$ref: "#/components/responses/Error"}
components:
  schemas:
    CatalogOptionList:
      type: object
      additionalProperties: false
      required: [data]
      properties:
        data: {type: array, items: {$ref: "#/components/schemas/CatalogOption"}}
    CatalogOption:
      type: object
      additionalProperties: false
      required: [id, sku, name]
      properties:
        id: {type: integer}
        sku: {type: [string, "null"]}
        name: {type: string}
```

OpenAPI 3.1 nullability uses a type array (VAL-1). The `Error` response name is illustrative; use the component the generator already emits for ERR-1.

## 16. Options considered

| Option | Benefits | Costs and risks | Decision |
| --- | --- | --- | --- |
| Add only the missing selectors next to current routes | Fewest client changes | Naming and combined lookup responses stay mixed | Acceptable as Phase 1, not the target |
| Flat qualified collection plus `/options`, imports retained (this document) | Uniform, no deep URLs, imports keep working, ownership stays local | More endpoints; naming and permission audit needed | **Recommended** |
| Nested namespace per owner (`/equipment/manufacturers`) | Familiar grouping | Collides with asset meaning and `{id}`; implies dependency; inconsistent across owners | Rejected |
| Neutral namespace per domain (`equipment-catalog/...`) | Grouping without collision | Whether a domain needs it is a judgment call, so styles diverge | Rejected for consistency |
| Extend the aggregate `reference-data` response | No new routes | Aggregates are neither bounded nor filterable; not a selector | Rejected |
| Selector as a mode of the list (`?view=options`) | Fewer routes | Two meanings on one surface; hard to document and cache | Rejected |
| Move every import and management route in one release | Fewer route families eventually | Breaks importer callers; may grant unintended methods | Not without full inventory and approval |

## 17. Open owner decisions

| # | Question | Needed by |
| --- | --- | --- |
| 1 | SKU default: option A, B or C (section 8; recommended B); handling of nullable project `code` | Before Phase 2 |
| 2 | Is naming rule R2 (always qualify) accepted? Which bare nouns, if any, go on the allowlist (for example `countries`, `cities`)? | Before Phase 2 |
| 3 | Management convention (D8): flat URL with permissions, or keep `admin/` | Before Phase 4 |
| 4 | Size class per resource (section 7.3); confirm the single cap constant | Before each selector |
| 5 | Is every registered catalog selectable, or only those used as form inputs? Which candidate selectors should not exist? | Before Phase 2 |
| 6 | Do imports remain a permanent integration surface? | Before Phase 4 |
| 9 | Approve the standard amendments in section 19.2 | Before Phase 1 |
| 7 | Who may select projects, technical users, organizational catalogs and Support Desk teams, including API-key-only callers? How are inactive historical values shown? | Security review |
| 8 | ADR location (`docs/architecture/decisions/`) confirmed by the owner | On acceptance |

## 18. Work items by role

| Role | Work |
| --- | --- |
| API Designer | Per-route record: method, current and target path, response and error shape, page and cap, parameters, `sku` type and source, visibility, VER-2 classification. Consumer and collision audit. Reconcile with the API response redesign document and resolve proposal-versus-proposal drift. |
| Data Architect | Where stable IDs or codes are needed; reversible migration plan for any new column, constraint, backfill or seeded ID; duplicate-identity guards; confirm whether REL-5 applies to user-created catalogs. |
| Security Engineer and feature owners | Per-resource authorization for list, select, import and manage; tests for object scope, inactive and historical access. |
| Backend Engineer and QA | Feature-local selectors over authorized queries; negative, empty, cap, query-count, filter and parent tests; import regression. |
| Human owner | Approve the ledger, deprecations, SKU decision, standard amendments and the coordinated breaking release. |

## 19. Rulebook

### 19.1 Checklist for every new or changed selector

A selector is not mergeable until every line is true. Each item cites the rule it enforces.

| # | Check | Rule |
| --- | --- | --- |
| C1 | Path is `/api/<root>/<resource>/options`, slashless, `GET` only, sibling of the list | OPT-1, TRN-4, R1, R7 |
| C2 | Resource is a controlled vocabulary, reference catalog or primary resource, not an enum | 6.4, ENU-5 |
| C3 | Response is `{"data": [CatalogOption]}` via the shared serializer | OPT-2, OPT-4, 14 |
| C4 | `sku` is a stable string or `null`; source recorded in the ledger | OPT-3, 8 |
| C5 | Query serializer = list filters + `q` + `include_ids`; one name per filter; no blank, no `search`, no `ordering` | OPT-5, OPT-7, QRY-1, QRY-4, 6.1 |
| C6 | Size class declared; large class requires `q` or a parent filter; `cap + 1` overflow check | OPT-6, 7.3 |
| C7 | Same permission and object scope as the list; hidden IDs in `include_ids` omitted silently | SEC-2, REL-11, 10 |
| C8 | One query, `Exists` for relation filters, query count asserted | OPT-8, PRF-2 |
| C9 | `ETag`, `private, no-cache`, `Vary: Accept-Language` | CCH-1, CCH-2, CCH-4 |
| C10 | `x-owner` set; OpenAPI regenerated in the same change | DOC-1, R1 |
| C11 | Tests: keys/types, order, empty, unknown param, overflow, permission, inactive, `include_ids`, query count | 12 |

### 19.2 Proposed amendments to the response standard

To make this binding project-wide, the rules belong in [response-standard.md](../../ai-team/api/response-standard.md) section 26, not only in this ADR. Proposed text, for owner approval (adding endpoints is VER-2 non-breaking; these rules tighten validation only for new endpoints until Phase 4):

- **OPT-1 (amend)** Path is `GET /api/<root>/<resource>/options`. Inverse forms (`/options/<resource>`) and alternative names (`select-list`) MUST NOT be used.
- **OPT-3 (amend)** `sku` is a string or `null`, the same type on every options endpoint. It is stable: never derived from mutable display text, rank or position. `null` means the resource has no secondary identifier.
- **OPT-9 (new)** Search is `q` only (QRY-7), matching `name` and `sku`. `search` is not accepted.
- **OPT-10 (new)** `include_ids` returns the listed rows regardless of active state or filters, when the caller may read them; unreadable or missing IDs are omitted silently.
- **OPT-11 (new)** Each options endpoint declares a size class. A large-class endpoint requires `q` or a declared parent filter.
- **OPT-12 (new)** Enums (ENU-5) do not have options endpoints; their values are published as `{value, label}` in the schema or filter metadata.
- **OPT-13 (new)** Options endpoints return `ETag` and honor `If-None-Match` (CCH-2).
- **REL-5 (amend)** Seeded fixed ids apply to controlled vocabularies. Reference catalogs created by import or users have database ids and follow REL-3.

Once adopted, this ADR keeps only the decisions and ledger and links to section 26 for the rules (documentation map: API rules live in one place).

## 20. Current-state drift (verified, 2026-11-01)

Existing selectors checked against OPT-1 to OPT-8 and this document. These become the shrinking allowlist of the architecture test. Not exhaustive: aggregate `reference-data` and `filters` routes were not re-audited.

| ID | Priority | Location | Evidence | Fix (phase) |
| --- | --- | --- | --- | --- |
| DRIFT-1 | High | [core/support_desk/features/tickets/queries/options.py](../../../core/support_desk/features/tickets/queries/options.py#L15-L69) | All five selectors `list(...)` the full table; no cap | Use shared base with cap (3) |
| DRIFT-2 | High | [core/labs/features/equipment/api/views.py](../../../core/labs/features/equipment/api/views.py#L338-L362) | `equipment/options` returns `list(queryset)` with no cap | Shared base with cap (3) |
| DRIFT-3 | Medium | [core/support_desk/features/tickets/queries/options.py](../../../core/support_desk/features/tickets/queries/options.py#L29-L40) | Priority `sku = Coalesce(rank, 0)`: integer, mutable sort position | `code` or `null` (4) |
| DRIFT-4 | Medium | [core/support_desk/features/tickets/queries/options.py](../../../core/support_desk/features/tickets/queries/options.py#L65-L69) | Label `sku = name`: duplicates mutable display text | `null` (4) |
| DRIFT-5 | Medium | [core/support_desk/features/tickets/api/urls.py](../../../core/support_desk/features/tickets/api/urls.py#L41-L43) | Inverse aliases `options/categories`, `options/priorities`, `options/statuses` | Remove after client audit (4) |
| DRIFT-6 | Medium | [core/labs/features/equipment/api/urls.py](../../../core/labs/features/equipment/api/urls.py#L42) | Slash alias `equipment/options/` violates TRN-4, PTH-5 | Remove after client audit (4) |
| DRIFT-7 | Medium | [core/labs/features/resource_audit/api/urls.py](../../../core/labs/features/resource_audit/api/urls.py#L42-L46), [selectors.py](../../../core/labs/features/resource_audit/queries/selectors.py#L281-L291) | `audits/options` serves enum `ResourceAudit.Result` with synthetic ids 1 to 3; path is not a sibling of a selectable resource | Publish as enum metadata (4) |
| DRIFT-8 | Medium | [core/labs/features/benches/api/serializers.py](../../../core/labs/features/benches/api/serializers.py#L288-L299) | Duplicate filter names (`bench_group`/`bench_group_id`, `type`/`type_id`, `setup_location`/`setup_location_id`, `status`/`lifecycle_status`); `search` with `allow_blank` | Keep `*_id` names and `q` (3 alias, 4 remove) |
| DRIFT-9 | Low | [core/support_desk/features/tickets/api/serializers.py](../../../core/support_desk/features/tickets/api/serializers.py#L50-L54), [core/labs/features/equipment/api/serializers.py](../../../core/labs/features/equipment/api/serializers.py#L355-L376) | `search` and `q` both accepted with `allow_blank=True`; equipment filters `category`, `kind`, `type` not `<relation>_id` | Standard `q`; `*_id` names (3, 4) |
| DRIFT-10 | Low | [docs/ai-team/api/response-redesign.md](../../ai-team/api/response-redesign.md#L241) | Proposes `benches/select-list/` (with trailing slash) while code uses `benches/options` | Update redesign doc to `benches/options` |
| DRIFT-11 | Low | three serializers: support `OptionSerializer`, resource-audit `OptionSerializer`, `EquipmentOptionsSerializer`/`BenchSelectSerializer` | Same contract defined four times; support `sku` is `allow_blank`, not nullable | Shared `CatalogOptionSerializer` (1) |

`benches/options` ([views.py](../../../core/labs/features/benches/api/views.py#L169-L197)) is the closest to target (cap + 1, `too_many_results`, test with patched cap) and is the recommended reference implementation.
