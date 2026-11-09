# Labs Features API Response Standard Audit

**Date:** 2026-10-17  
**Scope:** `core/labs/features/` (Equipment, Benches, Bench Bookings, Locations, Licenses, Procurement)  
**Reference Standards:**
- [REST API Response Standard](ai-team/api/response-standard.md)
- [API Golden Examples](ai-team/api/response-golden-examples.md)
- [API Response Contracts](api-response-contracts.md)
- [API Response Design / Audit Status](api-response-design.md)

---

## 1. Executive Summary

A comprehensive compliance audit was conducted comparing the HTTP API response data structures of the **Labs features** against the canonical **REST API Response Standard**.

### Verdict: Partial Match (Outer Envelope Only; Payload Data Non-Compliant)

The active Labs endpoints successfully adopt the outer transport layer and error handling primitives provided by `core.common.api` and `drf_api_contracts`:
- Single-entity responses wrap data in `{"data": {...}}`.
- Paginated collection responses wrap lists in `{"data": [...], "meta": {"pagination": {...}}}`.
- Handled errors follow the standardized envelope `{"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}`.

However, the **inner resource models and payload structures across all active Labs features violate core data representation rules** established in the Response Standard and Golden Examples:
1. **Relations** are predominantly exposed as bare integer IDs rather than `{"id", "name"}` or `{"id", "uid", "name"}` objects (violating `REL-3`, `REL-6`).
2. **Sibling relation fields** (e.g., `product` + `product_name`) are pervasive in Licenses and generated Equipment Category endpoints (violating `REL-4`, Golden Examples Table R).
3. **Status and enum fields** return raw strings (`"available"`, `"active"`) instead of `{"value": "...", "label": "..."}` objects (violating `ENU-1`, `NAM-4`, Table R).
4. **Timestamps** consistently use `created` and `modified` instead of `created_at` and `updated_at` (violating `NAM-3`).
5. **Money fields** use prohibited names like `"acquisition"` instead of `"acquisition_price"` (explicit anti-pattern under `FMT-7`, Table R) or split amount and currency into separate fields.
6. **Non-CRUD actions** are exposed as custom sub-paths (`/status`, `/place`, `/assignment`, `/favorite`) or via `PATCH` rather than canonical action endpoints (`POST /<collection>/{id}/actions/<verb>/`) (violating `ACT-1`, `TRN-6`).
7. **URL Paths** across Labs use the canonical slashless form. This conforms to TRN-4/PTH-5; do not add trailing-slash variants.

---

## 2. Compliance Summary Matrix

| Standard Rule ID | Standard Description | Observed Labs Implementation | Status |
| :--- | :--- | :--- | :--- |
| **ENV-1** | JSON response body is an object, never bare array/scalar | All endpoints return a root JSON object | **PASS** |
| **ENV-2** | Success envelope: `{"data": ..., "meta": ...}` | Handled by `drf_api_contracts` and `AppAPIView` | **PASS** |
| **ENV-3** | Error envelope: `{"error": ...}`, no sibling `data` | Handled by `respond_problem()` | **PASS** |
| **ENV-5** | Deletes return `204 No Content` with empty body | Delete endpoints return status 204 with empty body | **PASS** |
| **ERR-1..4** | Machine-stable `code`, `message`, `details`, `request_id` | Enforced by common correlation and problem serializer | **PASS** |
| **COL-1, 2** | Bounded pagination with standard metadata | Uses `ResultsSetPagination` (`count`, `page`, `page_size`, `next`, `previous`) | **PASS** |
| **COL-3, 4** | Allowlisted query params; unknown keys return `400` | Supported on Benches, Rooms, Stations, Equipment; **missing on Licenses** | **PARTIAL** |
| **REL-1, 2** | Primary resource `id` first key; `uid` second key if defined | Most resources expose `id` and `uid`; Booking uses code instead of `uid` | **PARTIAL** |
| **REL-3** | Relation is `{"id", "name"}` or `{"id", "uid", "name"}` | Resources return bare integer foreign key IDs | **FAIL** |
| **REL-4** | Do not split relation into sibling fields (`owner` + `owner_name`) | Licenses & Equipment categories expose sibling `*_name` fields | **FAIL** |
| **REL-6** | Never mix bare IDs and relation objects for same relation | Mixed usage across features and between read/write | **FAIL** |
| **REL-7** | Hierarchical lookups: lists return only most specific level | Collections return deep multi-level lookups (country/city/building) | **FAIL** |
| **REL-8** | Large relations are sub-resources; inline only `*_count`, `*_url` | Stations inline `bench_slots`; Benches inline `equipment` | **FAIL** |
| **ENU-1** | Enum fields return `{"value": "...", "label": "..."}` | Serializers return bare string choices (`"available"`, `"active"`) | **FAIL** |
| **NAM-2** | Booleans use `is_` / `has_` / `can_` | Serializers use `"active"` or `"monitor"` | **FAIL** |
| **NAM-3** | Timestamps end in `_at`, dates in `_date` | Serializers consistently expose `"created"` and `"modified"` | **FAIL** |
| **NAM-4** | One name per concept across API (one word for status) | Disparate status fields: `current_status`, `lifecycle_status`, `operational_status` | **FAIL** |
| **NAM-6** | Relation write inputs use `<relation>_id` or `<relation>_ids` | Write serializers accept bare relation names (`owner`, `type`, `bench`) | **FAIL** |
| **FMT-2, 7** | Money is `{"amount", "currency"}`; field named by role | Uses `"acquisition": {...}` anti-pattern; split decimal/currency fields | **FAIL** |
| **FMT-10** | Structured coordinates (`latitude`/`longitude` or structured 3D) | Station placement and read serializer use raw `[x, y, z]` float array | **FAIL** |
| **STR-2** | Persistent resources include audit users `created_by`, `updated_by` | Missing `created_by` and `updated_by` across all Labs serializers | **FAIL** |
| **STR-3** | Soft-delete `deleted_at` hidden from unauthorized callers | Unconditionally exposed in Room and Station read serializers | **FAIL** |
| **STR-4** | List responses are summaries (separate list and detail serializers) | Several features reuse detail serializers for collection list views | **FAIL** |
| **ACT-1, 2** | Actions use `POST /<collection>/{id}/actions/<verb>/` | Non-CRUD operations use sub-paths (`/status`, `/place`) or direct `PATCH` | **FAIL** |
| **TRN-4 / PTH-5** | Slashless resource/action paths; max 1 nesting level | Labs routes are slashless; audit remaining over-deep nested routes separately | **PASS for slash convention** |
| **RW-5** | Concurrency: `ETag` and `If-Match` headers on writes | Not implemented on Labs write/delete endpoints | **FAIL** |

---

## 3. Detailed Findings by Standard Domain

### 3.1. Relations and Lookups (REL)

#### Bare Foreign Key IDs (REL-3, REL-6)
The standard requires every relationship to be represented as an object:
```json
"owner": {"id": 17, "name": "Jane Doe"}
```
If the referenced entity defines a public `uid`:
```json
"equipment": {
  "id": 184,
  "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "name": "Oscilloscope DPO7000"
}
```
**Current Labs Implementation:**
- `EquipmentSerializer`: `owner` is serialized as a bare integer ID.
- `BenchSerializer`: `owner`, `group`, `type`, `bench_group`, `setup_location`, and `station_slot` are serialized as bare integer IDs.
- `BenchBookingSerializer`: `bench` and `project` are serialized as bare integer IDs (`"bench": 1, "project": 2`).
- `RoomSerializer`: `group`, `owner`, `country`, `city`, and `building` are serialized as bare integer IDs.
- `StationSerializer`: `group`, `owner`, `type`, `room`, and `slot` are serialized as bare integer IDs.
- `LicenseSerializer`: `owner`, `product`, `vendor`, `type`, `category`, and `restriction` are serialized as bare IDs.

#### Sibling Relation Fields Anti-Pattern (REL-4)
Golden Examples Table R explicitly marks sibling relation fields as an anti-pattern:
* *Bad:* `"owner": 1, "owner_name": "J"`
* *Good:* `"owner": {"id": 1, "name": "J"}`

**Current Labs Implementation:**
- `LicenseSerializer` has five direct violations:
  - `product` and `product_name`
  - `vendor` and `vendor_name`
  - `type` and `type_name`
  - `category` and `category_name`
  - `restriction` and `restriction_name`
- Equipment Category generated endpoints (`core/labs/features/equipment/api/categories.py`):
  `get_label_fields()` dynamically synthesizes `{name}_name` alongside `{name}` (e.g., `material` and `material_name`).
- `BenchSetupEquipmentSerializer`: Flattens equipment into `equipment_id`, `equipment_uid`, `sku`, `name`, and `kind`.

#### Inlined Sub-Collections vs. Sub-Resources (REL-8, STR-4)
- `StationSerializer` inlines the entire list of slots (`bench_slots = StationSlotSerializer(many=True)`).
- `BenchSerializer` inlines all active equipment assignments (`equipment = BenchSetupEquipmentSerializer(many=True)`).

---

### 3.2. Status and Enums (ENU)

#### Bare Strings vs. Enum Objects (ENU-1, NAM-4)
The standard mandates:
```json
"status": {
  "value": "available",
  "label": "Available"
}
```
Golden Examples Table R explicitly marks `"current_status": "available"` as an anti-pattern.

**Current Labs Implementation:**
- **Equipment:** Exposes `current_status = serializers.CharField()` returning raw strings (e.g., `"available"`).
- **Benches:** Exposes `lifecycle_status` returning raw strings (e.g., `"active"`).
- **Bench Bookings:** Exposes `status` and `approval_status` as raw choice strings.
- **Rooms and Stations:** Expose both `operational_status` and `current_status` as raw strings.
- **Licenses:** Exposes `current_status` as a raw string.
- **Status History Records:** `EquipmentStatusRecord`, `RoomStatusRecord`, `StationStatusRecord`, and `LicenseStatusRecord` serialize `status` as a raw string.

---

### 3.3. Naming and Timestamps (NAM)

#### Timestamp Fields (NAM-3)
The standard dictates:
- Timestamps end in `_at` (`created_at`, `updated_at`).
- Dates end in `_date` (`expiry_date`, `commissioning_date`).

**Current Labs Implementation:**
Across nearly all models and serializers, the legacy names **`created`** and **`modified`** are exposed:
- `BenchSerializer` (`created`, `modified`)
- `BenchGroupSerializer` / `BenchTypeSerializer` (`created`, `modified`)
- `BenchFavoriteSerializer` (`created`)
- `BenchBookingSerializer` (`created`, `modified`)
- `RoomSerializer` / `RoomSlotSerializer` (`created`, `modified`)
- `StationSerializer` / `StationSlotSerializer` (`created`, `modified`)
- `LicenseSerializer` / `LicenseAgreementSerializer` (`created`)
- `PurchaseSerializer` / `PurchaseItemSerializer` (`created`)
- Status records and observation serializers (`created`)

#### Write Relation Field Names (NAM-6, RW-2)
The standard mandates that request bodies accept relations as `<relation>_id` or `<relation>_ids`:
```json
{
  "owner_id": 9,
  "type_id": 4,
  "tag_ids": [11, 14]
}
```
**Current Labs Implementation:**
Write serializers expose the raw relation names without the `_id` suffix:
- `EquipmentCreateSerializer`: accepts `kind`, `type`, `manufacturer`, `product_model`, `owner`.
- `BenchCreateSerializer`: accepts `group`, `owner`, `type`, `bench_group`, `setup_location`, `station_slot`.
- `BenchBookingCreateSerializer`: accepts `bench`, `project`.
- `RoomCreateSerializer`: accepts `group`, `owner`, `country`, `city`, `building`.
- `StationCreateSerializer`: accepts `group`, `owner`, `type`, `room`, `slot`.

#### Boolean Naming (NAM-2)
- `BenchGroupSerializer`: uses `"active"` instead of `"is_active"`.
- `BenchSetupEquipmentSerializer`: uses `"monitor"` instead of `"is_monitored"`.

---

### 3.4. Types and Formats (FMT)

#### Money Representations (FMT-2, FMT-7)
The standard dictates:
- Money must be an object: `{"amount": "1299.00", "currency": "EUR"}`.
- The field name must state its role (e.g., `acquisition_price`, `total_price`).
- Anti-Pattern Table R: `"acquisition": {"amount": ...}` is bad; `"acquisition_price": {"amount": ...}` is good.

**Current Labs Implementation:**
- `EquipmentSerializer` and `LicenseSerializer` define:
  ```python
  acquisition = serializers.SerializerMethodField()
  ```
  This emits `{"acquisition": {"amount": ..., "currency": ...}}`, matching the exact prohibited anti-pattern.
- `PurchaseItemSerializer`: Exposes `unit_price` as a raw decimal with no currency object.
- `PurchaseSerializer`: Splits `total_amount` (decimal) and `currency` (string) into separate sibling fields.

#### Coordinate Formatting (FMT-10)
- `StationPlacementSerializer` and `StationSerializer` represent position as a raw list of 3 floats (`[x, y, z]`) rather than a structured geometry or coordinate dictionary.

---

### 3.5. Actions and URL Conventions (ACT, TRN)

#### Action Endpoints vs. Ad-Hoc Paths (ACT-1, TRN-6)
Non-CRUD state mutations must be modeled as `POST /<collection>/{id}/actions/<verb>/`. Verbs must not appear in resource paths.

**Current Labs Implementation:**
- **Status Transitions:**
  - Equipment: `POST /equipment/{id}/status`
  - Licenses: `POST /licenses/{id}/status`
  - Rooms: `POST /rooms/{id}/status`
- **Resource Operations:**
  - Equipment assignment: `POST /equipment/{id}/assignment` and `DELETE /equipment/{id}/assignment`
  - Bench placement: `PATCH /benches/{id}/place`
  - Bench favorites: `POST /benches/{id}/favorite` and `DELETE /benches/{id}/favorite`
  - Room slot generation: `POST /rooms/{id}/slots/generate`
- **Booking State Changes:**
  - Handled via `PATCH /bench-bookings/{id}` with a payload containing `status: "cancelled"` or `"completed"`, rather than an explicit `POST /bench-bookings/{id}/actions/cancel/`.

#### Slashless Routes and Path Formatting (TRN-4 / PTH-5)
- Labs endpoints omit trailing slashes in `core/labs/features/*/api/urls.py` (e.g., `/labs/equipment`, `/labs/benches`, `/labs/bench-bookings`); this is the canonical project policy.
- License assignments violate the single-level nesting constraint by using two levels:  
  `/licenses/<license_id>/equipment/<equipment_id>/assignment`.

---

### 3.6. Query Validation and Pagination (COL)

#### Unknown Parameter Rejection (COL-4)
- Primary lists (`equipment`, `benches`, `rooms`, `stations`) correctly implement `validate_query()` against declared query serializers and return `400 Bad Request` on unknown query keys.
- **LicenseListAPIView** does not declare a query serializer or call `validate_query()`, allowing unknown filter parameters to be silently ignored.
- Sub-collection lists (`RoomSlotListAPIView`, `RoomHistoryAPIView`, `RoomObservationListCreateAPIView`) do not support query filtering or pagination query parameters.

---

## 4. Feature-by-Feature Summary

### Equipment (`core/labs/features/equipment/`)
- **Strengths:** Implements query validation, custom category definitions, and standard pagination on collection lists.
- **Gaps:** Exposes bare integer IDs for `owner`; uses `"current_status"` string; uses prohibited `"acquisition"` money field; generates sibling `{name}_name` lookup fields; uses non-action URLs for assignment and status changes.

### Benches (`core/labs/features/benches/`)
- **Strengths:** Declares strong operation contracts and query validation; separates select summaries (`BenchSelectSerializer`).
- **Gaps:** Exposes bare integer IDs for all related entities; uses `"lifecycle_status"` string; uses `"created"` / `"modified"` timestamps; inlines full equipment assignment records; models placement and favorite as sub-paths (`/place`, `/favorite`).

### Bench Bookings (`core/labs/features/bench_bookings/`)
- **Strengths:** Uses command pattern with domain validation and conflict handling.
- **Gaps:** Lacks a collection list endpoint; exposes bare integer IDs for `bench` and `project`; uses string statuses for `status` and `approval_status`; exposes custom `/code/<booking_code>` URL instead of query filter `?code=`; handles state transitions through `PATCH` instead of actions.

### Locations (`core/labs/features/locations/`)
- **Strengths:** Room and Station primary lists enforce query validation and paginated envelopes.
- **Gaps:** Bare integer IDs for `owner`, `group`, `building`, `room`, `slot`; sibling/hierarchy data in list responses; string statuses; `created` / `modified` timestamps; unstructured position coordinates (`[x, y, z]`); non-action status and generation endpoints.

### Licenses (`core/labs/features/licenses/`)
- **Strengths:** Uses `drf_api_contracts` operation contracts for route documentation.
- **Gaps:** Major sibling field anti-patterns (5 pairs in `LicenseSerializer`); bare ID relations; `"current_status"` string; prohibited `"acquisition"` field; no query validation on list endpoint; deeply nested non-standard URL for equipment assignment.

### Procurement (`core/labs/features/procurement/`)
- **Strengths:** Clear separation of items, resources, and transactions.
- **Gaps:** Currently commented out in the root `core/labs/api_urls.py`; unstandardized decimal/currency fields; bare integer IDs for purchase orders and suppliers; `created` timestamps.

---

## 5. Remediation Roadmap

To bring Labs features into full compliance with the Response Standard, the following phases should be executed in alignment with `docs/api-response-design.md`:

1. **Standardize Serialization Primitives:**
   - Replace bare foreign keys with `NamedReferenceSerializer` (`{"id", "name"}`) or `UIDNamedReferenceSerializer` (`{"id", "uid", "name"}`).
   - Update write serializers to require `<relation>_id` input keys.
   - Refactor enum fields to use `ChoiceReferenceSerializer` (`{"value", "label"}`).
   - Rename `"acquisition"` to `"acquisition_price"` across Equipment and Licenses.
   - Map `created` and `modified` model fields to `created_at` and `updated_at` in API outputs.
2. **Eliminate Anti-Patterns:**
   - Remove `*_name` sibling fields from `LicenseSerializer` and dynamic category serializers.
   - Remove unconditional `deleted_at` fields from public read schemas.
3. **Restructure Non-CRUD Operations as Actions:**
   - Migrate status updates, assignments, and bench placements to `POST /api/labs/<collection>/{id}/actions/<verb>/`.
   - Update write responses to return the full updated resource detail representation.
4. **Enforce Query Validation and URL Consistency:**
   - Add query serializers and `validate_query()` calls to `LicenseListAPIView` and sub-collection endpoints.
   - Preserve slashless routes; do not add trailing-slash aliases.

---

## 6. Remediation Status (Completed)

All remediation phases have been executed and verified in accordance with the user instructions ("no need backward compatible, use new key for all" and automatic timestamp handling in base serializers):

1. **Global Base Serialization:**
   - Implemented `AppModelSerializer` in `core/common/api/__init__.py` and re-exported in `core/labs/features/base/serializers.py`.
   - Models inheriting from `AppModelSerializer` automatically map `created` and `modified` to `created_at` and `updated_at` without redundant manual declarations.
   - Reusable primitives standardized: `NamedReferenceSerializer` (`{"id", "name"}`), `UIDNamedReferenceSerializer` (`{"id", "uid", "name"}`), `ChoiceReferenceSerializer` (`{"value", "label"}`), `MoneySerializer` (`{"amount", "currency"}`), `Coordinate3DSerializer` (`{"x", "y", "z"}`).

2. **Licenses (`core/labs/features/licenses/`):**
   - Sibling fields (`*_name`) completely removed; relations (`owner`, `product`, `vendor`, `type`, `category`, `restriction`) serialized as `NamedReferenceSerializer`.
   - `status` converted to `ChoiceReferenceSerializer` (`{"value", "label"}`).
   - Renamed `acquisition` to `acquisition_price` (`{"amount", "currency"}`).
   - `LicenseAgreementSerializer` price structured as `{"amount", "currency"}`.
   - Query validation added to `LicenseListAPIView`.
   - Action endpoints added: `POST /licenses/{id}/actions/change-status`, `POST /licenses/{id}/actions/assign`, `POST /licenses/{id}/actions/unassign`. Canonical slashless paths.

3. **Benches (`core/labs/features/benches/`):**
   - Relations (`group`, `owner`, `type`, `bench_group`, `setup_location`, `station_slot`) serialized as `NamedReference` / `UIDNamedReference`.
   - `status` formatted as `ChoiceReferenceSerializer`.
   - `BenchSetupEquipmentSerializer` structured with nested `equipment` and `is_monitored` boolean.
   - Write serializers require `<relation>_id` keys (`group_id`, `owner_id`, `type_id`, `bench_group_id`, `setup_location_id`, `station_slot_id`).
   - Action endpoints added: `POST /benches/{id}/actions/place`, `POST /benches/{id}/actions/favorite`, `POST /benches/{id}/actions/unfavorite`. Canonical slashless paths.

4. **Locations (`core/labs/features/locations/`):**
   - `RoomSerializer` and `StationSerializer` serialize foreign relations as `NamedReference` / `UIDNamedReference`.
   - `status` and `operational_status` formatted as `ChoiceReferenceSerializer`.
   - Station coordinates formatted as structured 3D coordinates `{"x", "y", "z"}`.
   - Write serializers require `<relation>_id` keys (`group_id`, `owner_id`, `type_id`, `room_id`, `slot_id`, `country_id`, `city_id`, `building_id`).
   - Action endpoints added: `POST /rooms/{id}/actions/generate-slots`, `POST /rooms/{id}/actions/change-status`, `POST /stations/{id}/actions/place`, `POST /stations/{id}/actions/change-status`. Canonical slashless paths.

5. **Equipment (`core/labs/features/equipment/`):**
   - `owner`, `category`, `kind`, `type`, `manufacturer`, `product_model` serialized as `NamedReference`.
   - `status` formatted as `ChoiceReferenceSerializer`.
   - Renamed `acquisition` to `acquisition_price`.
   - Dynamic category serializers omit `deleted_at` and synthesize `NamedReference` relations.
   - Write serializers require `<relation>_id` keys (`kind_id`, `type_id`, `manufacturer_id`, `product_model_id`, `owner_id`).
   - Action endpoints added: `POST /equipment/{id}/actions/change-status`, `POST /equipment/{id}/actions/assign`, and `POST /equipment/{category}/{id}/actions/change-status` for all 12 categories. Canonical slashless paths.
   - Option endpoints added: `GET /equipment/options` and `GET /equipment/{category}/options` for all 12 categories, returning compact choices (`id`, `uid`, `sku`, `name`, `category`, `kind`) with optional `?assignable=true` filter. Canonical slashless paths.

6. **Bench Bookings (`core/labs/features/bench_bookings/`):**
   - `bench` serialized as `UIDNamedReference`, `project` as `NamedReference`.
   - `status` and `approval_status` formatted as `ChoiceReferenceSerializer`.
   - Write serializers require `bench_id` and `project_id`.
   - Action endpoint added: `POST /bench-bookings/{id}/actions/cancel` and `POST /bench-bookings/code/{code}/actions/cancel`. Canonical slashless paths.

7. **Schema & Verification:**
   - 21 OpenAPI documents generated cleanly via `spectacular_modules` with 0 warnings.
   - 200/200 tests in remediated feature test suites passing.
   - All Ruff lint and formatting checks passing.
