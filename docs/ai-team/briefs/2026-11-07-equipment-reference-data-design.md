# Design: Category Equipment Reference Data

**Status**: Approved for implementation by the human owner on 2026-11-07.
**Risk**: T2 — public API collection membership changes.
**Related brief**: [2026-11-07-equipment-reference-data-scope.md](2026-11-07-equipment-reference-data-scope.md)

## Decision

For `GET /api/labs/equipment/{category}/reference-data`, scope the catalog hierarchy to the category resolved by the existing route/query path:

1. Return active kinds associated with the resolved category.
2. Return active types associated with those kinds.
3. Return active manufacturers explicitly associated with the category through the category's `manufacturers` association (`EquipmentCategory.manufacturers` / `EquipmentManufacturer.categories`).
4. Return active product models whose type belongs through an active kind to this category, and whose manufacturer is active and explicitly associated with the category.

Do not infer manufacturer-category association merely because a product model exists. A manufacturer explicitly associated with the category may appear even when it has no eligible model. A model is eligible only when both its type hierarchy and manufacturer association meet the category rules.

## Compatibility and scope

The endpoint keeps its existing response envelope, list keys, item serializers, status and empty-list behavior. No product-model type field is added. Preserve current category identity resolution, permissions, `groups`, `owners`, category-specific lookups and generic `/equipment/reference-data` behavior. No membership data repair or migration is included.

The row-inclusion change is breaking under VER-2 even though the response shape is unchanged. The human owner explicitly approved this exact scope on 2026-11-07. Clients relying on unrelated manufacturers/models appearing in a category response may need adjustment; this client impact must be communicated before release.

## API rule table

| Rule ID | Status | Application |
|---|---|---|
| GEN-3 | Pass | Preserve response keys and item shapes; clients should ignore any unknown response fields. |
| ENV-2 | Pass | Preserve the existing success envelope. |
| ENV-4 | Pass | Preserve `200` and empty-list behavior. |
| VER-2 | Breaking change, approved | Collection row inclusion narrows. Human owner approval recorded above; communicate impact to clients. |

No request-standard behavior changes: the route, parameters, authentication and permissions remain unchanged.

## Implementation and verification

- Apply the filters in the category-specific query path only; do not alter category key/name resolution in this change.
- Keep filtering in ORM querysets and ensure related serializer reads do not introduce N+1 queries.
- Add API regression tests for cross-category exclusion, category-associated kinds/types, manufacturers without explicit membership, parent inactive states, product-model type/manufacturer eligibility and response-shape preservation. Keep or add bounded query-count coverage where required by PRF-2.
- Update the category API documentation where it currently describes manufacturers/models as common.
- Regenerate OpenAPI from source using the repository command, inspect descriptions and generated diff, then run the prescribed bundling and Spectral lint commands. Do not hand-edit generated OpenAPI.
- Obtain QA, security and independent review before merge; record exact commands and results in the handoff.

## Data and residual risks

Manufacturer-category membership data has not been audited. Existing manufacturers/models without explicit category registration will no longer appear in this endpoint. No automatic backfill is allowed in this task; report this behavior to the owner/client stakeholders and handle any data repair through a separately reviewed plan.

The existing category identity behavior (including possible name/key mismatch where stored keys are null) remains unchanged and should be addressed separately if needed.# Design note: Category-specific equipment reference data

**Status**: Approved scope; implementation and release pending
**Tier**: T2 — category collection membership changes in a public API
**Decision authority**: Human owner approved this exact scope

## Decision

For `GET /api/labs/equipment/{category}/reference-data`, narrow the existing
reference collections as follows, using the category already resolved by the
current route/query flow:

- `kinds`: active kinds associated with the resolved active category.
- `types`: active types whose kind is one of those category kinds.
- `manufacturers`: active manufacturers explicitly linked to that category through
  `EquipmentManufacturer.categories`; a manufacturer with no category membership
  is not global and is excluded.
- `product_models`: active models whose equipment type belongs to a kind in the
  resolved category; require the model, manufacturer, type, kind, and category to
  be active, and require the manufacturer to be explicitly linked to the category.
- Preserve response shape and item serializers, response envelope, groups, owners,
  category-specific lookups, permissions, category resolution, and generic
  `/api/labs/equipment/reference-data` behavior.

The owner has approved exactly this T2 scope. This approves proceeding with the
design and implementation; it does not waive security/QA review, independent review,
quality gates, or any separate release decision.

## Endpoint contract

| Method / path | Auth and permission | Request | Success | Errors and behavior |
| --- | --- | --- | --- | --- |
| `GET /api/labs/equipment/{category}/reference-data` | Preserve the current `EquipmentAPIView` authentication and permission behavior. | No body or new query parameters. Resolve `{category}` through the existing route flow. | Existing success envelope and keys; preserve each existing item serializer and order contract. Narrow only `kinds`, `types`, `manufacturers`, and `product_models` as specified above. Preserve `groups`, `owners`, and category-specific lookup output. Empty collections remain arrays. | Preserve existing authentication, permission, route-resolution, and error behavior; do not introduce new error codes or statuses. `HEAD`/`OPTIONS` follow existing shared API behavior. |

No pagination, sorting, filtering, cache policy, conditional request, or new
idempotency behavior is introduced by this change. Preserve existing behavior;
those mechanics were not independently verified as conforming to the target
standards in this design review.

## VER-2 classification and compatibility

**Breaking behavior change.** The response schema and item shape stay the same, but
existing callers can receive fewer rows for `kinds`, `types`, `manufacturers`, and
`product_models`. In particular, manufacturers and models that previously appeared
globally may disappear for a category when there is no explicit membership. This
changes collection meaning/row inclusion and is breaking under response-standard
VER-2; unchanged JSON shape does not make it non-breaking.

No route version or alias is proposed. Coordinate backend/frontend adoption and
communicate that missing manufacturer-category mappings are excluded, not repaired
or interpreted as global. Do not backfill data in this scope. No deprecation path
was requested or approved; if a consumer migration/deprecation path is needed, it
requires a separate owner decision under VER-1/VER-3.

## Design recommendations

1. Keep the query change in the existing category reference-data query, using the
   already-resolved category identity; do not revise name/key resolution here.
2. Apply active-parent predicates explicitly through each relation. Avoid relying
   only on child `active=True`, because inactive category/kind/type/manufacturer
   parents must not leak child rows.
3. Express manufacturer membership as an explicit relation filter against the
   resolved category. Use `distinct()` if joins can duplicate rows; preserve the
   existing deterministic ordering rather than inventing a new order.
4. Scope product models through `equipment_type -> kind -> category` and separately
   require active status on model, manufacturer, type, kind, and category plus the
   manufacturer's category membership. Do not add a type field to the product-model
   response item.
5. Keep generic `equipment_reference_data()` isolated and unchanged. Keep category
   lookup, groups, owners, permissions, and serializer construction unchanged.
6. Add regression/API tests for category isolation across two categories, an
   unassociated manufacturer being excluded, inactive ancestors at each level,
   product-model manufacturer membership, response-key/item-shape preservation,
   preserved groups/owners/lookups, unchanged generic endpoint results, and
   unchanged permissions/category resolution. Include bounded-query assertions for
   the endpoint per PRF-2 and the query-performance instructions.
7. Audit the existing category docs' claim that manufacturers and product models
   are common and replace it with this category-specific behavior as part of
   implementation.

## Required API rule table

Status distinguishes design compliance from runtime verification. Runtime is not
verified by this design-only review.

| Rule ID | Status | Fix or evidence |
| --- | --- | --- |
| GEN-1 | Pass (scope) | Treat this as an HTTP/JSON API contract change; endpoint remains under `/api/`. |
| GEN-3 | Pass (preserved) | No request fields or response fields are added/removed; clients must continue to tolerate unknown response fields. |
| GEN-4 | Pass (design) | Per-resource item fields remain defined by the existing generated OpenAPI contract; do not invent fields. |
| ENV-1 | Pass (preserved) | Preserve the existing object response envelope, not a bare array. |
| ENV-2 | Pass (preserved) | Preserve existing `data` success structure and keys; do not add ad-hoc `meta`. |
| ENV-4 | Pass (preserved) | Empty filtered collections remain `200` with empty arrays; no single-resource semantics change. |
| VER-1 | Pass (route) | No parallel versioned prefix or alternate route; approval for this exact scope is recorded above. |
| VER-2 | Breaking | Row inclusion/meaning changes despite unchanged schema shape. Coordinate affected consumers; no route version proposed. |
| VER-3 | Not applicable / unresolved | No field or endpoint is removed/deprecated. A deprecation rollout is not in approved scope; obtain a distinct decision if required. |
| DOC-1 | Pass (recommendation) | Regenerate OpenAPI from source after implementation and keep generated output in the same change; see schema decision below. |
| DOC-2 | Pass (recommendation) | Update endpoint documentation with category membership and active-parent rules, auth/permission preservation, and an example if existing docs provide one. |
| DOC-4 | Required | Add/extend contract assertions for response envelope and schema shape, plus behavioral regression tests for included/excluded rows. |

Request-standard rules concerning body validation, writes, idempotency, and
preconditions do not apply to this bodyless `GET`. Query rules remain unchanged:
there are no new query parameters. Authentication/authorization and endpoint
security must preserve the current behavior; retain the existing authorization
tests, and have Security review verify it is not broadened or narrowed.

## OpenAPI regeneration decision

**Regeneration is warranted and required by the repository API-design gate, even
though the OpenAPI schema shape is expected to remain unchanged.** The runtime
operation's documented collection semantics change, and the category API docs
currently describe manufacturers/product models as common. First inspect whether
the operation description or examples encode that old meaning. If so, update the
source schema annotations/documentation as needed and regenerate; never hand-edit
generated OpenAPI. If the generated diff is empty, record that the generated schema
was regenerated/validated and had no diff. If only prose metadata changes, include
that generated diff. Do not claim unchanged schema by assumption before generation.

## Required contract tests and remaining reviews

- Verify schema response keys and nested item fields are unchanged.
- Verify category-isolated active kinds and types.
- Verify manufacturers without explicit category membership are excluded.
- Verify models require category hierarchy, active model/manufacturer/type/kind/
  category, and explicit manufacturer membership.
- Verify groups, owners, category-specific lookups, permission behavior, category
  resolution, and generic endpoint behavior remain unchanged.
- Verify query counts remain bounded; run the focused test suite, project checks,
  OpenAPI generation/diff, and Spectral as required by the API-design instructions.
- Complete Security, QA, and independent review before merge. Their results are
  not established by this design note.

## Facts and limits

- **Verified in repository:** the category reference route delegates to
  `category_reference_data`; the current query returns active kinds/types by
  category but currently selects all active manufacturers and active models with
  active manufacturers. Generic reference data has a separate query function.
- **Verified in repository:** `EquipmentManufacturer.categories` is an explicit
  many-to-many relation. Product models relate to a manufacturer and equipment
  type; the model validation checks manufacturer/category membership.
- **Verified in brief:** the owner approved exactly the scope stated in this note.
- **Not verified:** runtime permissions/auth behavior beyond the instruction to
  preserve it; database membership quality; query budgets; tests; OpenAPI generation
  or Spectral results; reviewer or Security/QA sign-off.
