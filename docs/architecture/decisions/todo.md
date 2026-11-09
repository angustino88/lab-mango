# Catalog and Selector API — Implementation & Status

## Your decisions
| Item | Decision |
| --- | --- |
| 0.1 sku | Option B: sku is a stable string, or null when the model has no real code |
| 0.2 Breaking changes | Everything breaks once, in one backend and frontend release, with no aliases |
| 0.3 Which selectors | A resource gets a selector if a form saves it as a relation, or it is the parent filter of one. That gives 28 selectors (table in §20.3) |
| 0.4 Access | Reads: API key or logged-in user (HasAPIKey \| IsAuthenticated, already the FeatureAPIView default). Writes and inactive rows still need the feature's role |
| 0.5 Data changes | No new columns. One migration adds search indexes to the 7 large tables that lack one |

Two things to note:
1. **Access change:** Support Desk selectors are opened to every logged-in user and to API keys (`HasAPIKey | IsAuthenticated`), matching the system standard.
2. **Short names:** `buildings` and `departments` follow the bare-noun allowlist matching `countries` and `cities`.

---

## Implementation Status (Completed 2026-11-02)

### Phase 1: Shared Base (Completed)
- [x] `core/common/api/options.py` created with:
  - `CatalogOptionSerializer`: exactly `id`, `sku` (string or null), `name`.
  - `CatalogOptionListSerializer` envelope schema (`{"data": [...]}`).
  - `OptionsQueryMixin`: adds `q` (1 to 100 characters, no blank) and `include_ids` (up to 50 unique positive IDs).
  - `SizeClass` (`SMALL`, `LARGE`) and cap constant `OPTIONS_MAX_RESULTS = 1000`.
  - `OptionsAPIView`: query validation, size-class rule, cap + 1 enforcement (`400 too_many_results`), `include_ids` merge, ETag computation, `304 Not Modified` on `If-None-Match`, `Vary: Accept-Language`, and `Cache-Control: private, no-cache` (or `no-store` on errors). Permissions: `HasAPIKey | IsAuthenticated`.
- [x] Unit tests for the shared base in `tests/unit/test_options_base.py` (10 tests, all passing).
- [x] Architecture tests in `tests/architecture/test_options_contract.py` (4 tests, all passing with 0 allowlisted violations).
- [x] Migrations adding concurrent `pg_trgm` GIN search indexes:
  - `core/labs/migrations/0007_trigram_search_indexes.py` (`EquipmentType`, `EquipmentManufacturer`, `EquipmentProductModel`, `LabProject`, `City`, `Building`)
  - `core/support_desk/migrations/0005_support_label_trigram_index.py` (`SupportLabel`)

### Phase 2 & Phase 3: Selectors, Catalogs & Unified Breaking Release (Completed)
- [x] **Equipment:**
  - Migrated `EquipmentOptionsAPIView` to `OptionsAPIView` with `category_id`, `kind_id`, `type_id`, `manufacturer_id`, `lifecycle_status`, `assignable`, `q`, `include_ids`.
  - Migrated per-category options views (`<category>/options`) to `OptionsAPIView`.
  - Removed trailing-slash routes `equipment/options/` and `<category>/options/`, and removed duplicate `<category>/filters` route.
  - Added new catalog and selector endpoints:
    - `equipment-categories` (list, detail, options)
    - `equipment-kinds` (list, detail, options)
    - `equipment-types` (list, detail, options)
    - `equipment-manufacturers` (list, detail, options)
    - `equipment-product-models` (list, detail, options)
    - `departments` (list, detail, options)
    - `resource-groups` (list, detail, options)
- [x] **Bench Bookings:**
  - Added `lab-projects/options` endpoint (`LabProjectOptionsAPIView`) with `q`, `active_on`, `include_ids`.
- [x] **Benches:**
  - Migrated `BenchSelectAPIView` to `OptionsAPIView`.
  - Renamed filters: `search` -> `q`, `bench_group` -> `bench_group_id`, `type` -> `type_id`, `setup_location` -> `setup_location_id`, `status` -> `lifecycle_status`.
  - Added `bench-groups/options` and `bench-types/options`.
- [x] **Licenses:**
  - Added catalog list, detail, and options endpoints:
    - `license-vendors` (list, detail, options)
    - `license-products` (list, detail, options)
    - `license-types` (list, detail, options)
    - `license-categories` (list, detail, options)
    - `license-restrictions` (list, detail, options)
- [x] **Locations:**
  - Added `rooms/options`, `stations/options`, `station-types/options`.
  - Added catalog list, detail, and options endpoints for `countries`, `cities`, `buildings`.
- [x] **Support Desk:**
  - Migrated `categories/options`, `priorities/options`, `statuses/options`, `teams/options`, `labels/options` to `OptionsAPIView`.
  - Removed reverse paths `options/{categories,priorities,statuses}`.
  - Moved `admin/{categories,priorities,statuses,teams,labels}[/{id}]` to `{categories,priorities,statuses,teams,labels}[/{id}]` with `HasAPIKey | IsAuthenticated` on reads and `IsSupportAdmin` on writes.
  - Corrected `sku` semantics: Priority uses `NULLIF(code, '')`, Label and Status return `null`.
- [x] **Resource Audit:**
  - Removed synthetic enum endpoint `audits/options` per OPT-12 / D8.
- [x] **Duplicate Serializer Removal:**
  - Deleted duplicate serializers: `BenchSelectSerializer`, `EquipmentOptionsSerializer`, `core/labs/features/resource_audit` `OptionSerializer`, `core/support_desk` `OptionSerializer`.
- [x] **OpenAPI & Validation:**
  - Fully regenerated OpenAPI modules and full JSON schema via `python manage.py spectacular_modules`.
  - Verified 27 documents with zero drift (`python manage.py spectacular_modules --dry-run`).
  - Passed `ruff check core tests` with zero errors.
  - Passed all test suites with 100% success.
