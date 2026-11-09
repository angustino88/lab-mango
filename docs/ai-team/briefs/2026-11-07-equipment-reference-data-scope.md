# Task: Filter category equipment reference data

**Tier**: T2 — public API collection membership changes; explicit human-owner approval required before implementation/release.
**Assigned role**: Engineering Lead / API Designer; backend implementation after the contract change is approved.

## Outcome
The category-specific equipment reference-data endpoint returns the relevant choice hierarchy—category → kind → type → manufacturer → product model—without large unrelated lists, while preserving unrelated reference lists.

## Acceptance criteria
- [ ] `kinds` contains only active kinds associated with the resolved category; `types` contains only active types associated with those kinds.
- [ ] `manufacturers` contains only active manufacturers explicitly linked to the resolved category through `EquipmentManufacturer.categories`.
- [ ] `product_models` contains only active models whose equipment type belongs to the resolved category through its kind; model, manufacturer, type, kind, and category must all be active, and the manufacturer must explicitly be linked to that category.
- [ ] Manufacturers with no category membership are excluded, not treated as global.
- [ ] Preserve response keys/item serializers, existing category resolution, `groups`, `owners`, category-specific lookups, permission behavior, and generic `/equipment/reference-data` behavior.
- [ ] Add regression tests for two-category isolation, unassociated manufacturers, inactive parents, and response-shape preservation.
- [ ] Update category API docs and generated OpenAPI descriptions/examples if they describe the old global/common semantics. Do not hand-edit generated OpenAPI.
- [ ] Complete security and independent review; run the relevant gates.

## Non-goals
- Preserve the existing category identity resolution in this task; adding rename support for the existing name/key mismatch is separate work because persisted category keys may be null.
- Do not change `groups`, `owners`, permissions, or category-specific lookup scope.
- Do not change generic catalogs/options endpoints.
- Do not backfill manufacturer-category memberships or other stored data. Any data repair needs a separately reviewed and approved plan.

## Context
- `core/labs/features/equipment/queries/equipment.py`
- `core/labs/features/equipment/api/categories.py`
- `core/labs/features/equipment/api/category_serializers.py`
- `core/labs/models/resource/equipment/reference_data.py`
- `core/labs/features/equipment/docs/equipment-category-apis.md`
- `core/labs/features/equipment/tests/api/test_equipment_options.py`
- `docs/ai-team/api/response-standard.md` (VER rules)
- `docs/ai-team/team.md`

## Implementation contract
Use the category already resolved by the current route/query flow. Filter manufacturers by active manufacturer, active category, and explicit manufacturer-category M2M membership. Filter product models by active model, manufacturer, type, kind, and category; require the model type's kind to belong to the resolved category and the manufacturer to be explicitly associated with it. No category association means the manufacturer/model is not eligible for this category endpoint.

Product models are linked to both a manufacturer and an equipment type. Use the type relation for filtering; do not add a type field to the product-model response item unless that separate API shape change is explicitly approved.

This changes collection row inclusion, not response schema shape. It is a breaking behavior change under VER-2. ADR 002's coordinated catalog/selector redesign does not explicitly authorize this aggregate endpoint change. Obtain explicit human-owner approval before implementing/releasing; document the impact on clients. There is no approved deprecation/version path in this brief.

## API contract delta

| Method / path | Auth | Query and row inclusion | Response | Compatibility |
|---|---|---|---|---|
| `GET /api/labs/equipment/{category}/reference-data` | Preserve current `EquipmentAPIView` auth/permission behavior. | No new parameters. Kinds/types follow the requested category hierarchy; manufacturers and product models follow the rules above; all other lists remain unchanged. | Preserve existing envelope, keys, item serializers, status, and empty-list behavior. | Breaking row inclusion (VER-2); approval required before release. |

## Constraints and risks
- Existing category docs describe manufacturers/models as common; update them to explain category relevance.
- Existing product-model validation checks manufacturer/category compatibility, aligning the endpoint filter with write eligibility.
- Membership data quality has not been audited. Rows without explicit category registration will disappear; do not silently populate associations.
- Owner/group visibility is not addressed by this task and remains an independent policy question.

## Verification required
Write a design note and obtain human-owner approval before implementation. Add focused category reference-data API tests and QA review; run the equipment feature suite, `manage.py check`, OpenAPI generation/diff and Spectral. Complete security and independent review before merge. Report exact commands and outcomes.

## Return
`docs/ai-team/templates/handoff-report.md`