# Feature Specification: Software Licenses (`core/labs/features/licenses`)

## 1. Domain Overview & Purpose
The Licenses feature tracks commercial software and firmware entitlements, seat limits, commercial billing agreements, and assignments to computing equipment.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.License`
- **Inheritance:** `ResourceModel`.
- **Fields:**
  - `product` (FK `LicenseProduct`, PROTECT).
  - `category` (FK `LicenseCategory`, PROTECT).
  - `restriction` (FK `LicenseRestriction`, PROTECT, optional).
  - `max_version` (CharField(64)).
  - `serial_number` (CharField(255), vendor's license serial or ID, e.g. the Vector license ID). Visible and
    searchable. Unique per vendor among live licenses, case-insensitive (`license_vendor_serial_uniq`);
    agents match the licenses they find on lab computers to it.
  - `identifier` (CharField(255), license key / activation key; secret).
  - `expiry_date` (DateTimeField, nullable).
  - `status`: Enum (`available`, `assigned`, `expired`, `revoked`, `suspended`). Default: `available`.
    Stored as append-only `LicenseStatusRecord` rows; a license reads as its latest record.
    - Create writes the first record, `available`.
    - Assigning a seat turns `available` into `assigned`; releasing the last seat turns `assigned` back
      into `available` (metadata `reason` and the equipment). Both run under the license row lock.
    - `expired`, `revoked` and `suspended` are set only through `actions/change-status`; seat changes
      never override them.
    - A license with no record (created before initial records existed) reads as `assigned` when a seat
      is held, else `available` — in the list, the detail and `status-summary` alike, so none reads as
      unknown.

### 2.2 `core.labs.models.LicenseAssignment`
- **Fields:** `license` (FK `License`, PROTECT), `equipment` (FK `Equipment`, PROTECT), `assigned_at`, `unassigned_at` (nullable).
- **Invariant:** A software license can be actively assigned (`unassigned_at IS NULL`) to at most one equipment unit at a time.

### 2.3 `core.labs.models.LicenseAgreement` & `LicensePayment`
- **`LicenseAgreement`**: `price` (DecimalField), `currency` (default "EUR"), `billing_period` (`one_time`, `monthly`, `quarterly`, `annual`), `valid_from`, `valid_until`.
- **`LicensePayment`**: Financial records of disbursement against agreements (`amount`, `paid_at`, `reference`).

---

## 3. Options Standard Compliance (ADR 002)
`GET /api/labs/licenses/options` provides selector options `{id, sku, name}`.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/licenses` | `LicenseListAPIView` | Filtered list of software licenses. |
| `POST /api/labs/licenses` | `LicenseListAPIView` | Register a license (`create_license`); see section 5. |
| `GET /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | License details with active bindings. |
| `PATCH /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | Partial update (`update_license`); `sku` is immutable; see section 5. |
| `DELETE /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | Soft delete (`delete_license`); `409` while assigned; see section 5. |
| `GET /api/labs/licenses/options` | `LicenseOptionsAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/licenses/status-summary` | `LicenseStatusSummaryAPIView` | Status count distribution. |
| `GET /api/labs/licenses/categories/summary` | `LicenseCategorySummaryAPIView` | License counts per category. |
| `POST /api/labs/licenses/{license_id}/actions/assign` | `LicenseAssignActionAPIView` | Bind license to computing unit. |
| `DELETE /api/labs/licenses/{license_id}/actions/assign` | `LicenseAssignActionAPIView` | Standard unassign command. |
| `POST /api/labs/licenses/{license_id}/actions/change-status` | `LicenseStatusAPIView` | Update lifecycle state. |
| `GET /api/labs/licenses/{license_id}/history` | `LicenseHistoryAPIView` | Status records (`status`, `metadata`, `actor`, `created_at`), newest first, paginated; 404 for a missing or deleted license. |
| `GET` / `PUT` / `DELETE /api/labs/licenses/{license_id}/image` | `LicenseImageAPIView` | Read, replace (multipart, one `file` part: JPEG/PNG/GIF/WebP, at most 5 MB) or remove the image; license reads return `image_url` (see `core/labs/features/base/docs/resource-images.md`). |
| `GET/POST /api/labs/licenses/{license_id}/agreements` | `LicenseAgreementListCreateAPIView` | Commercial agreements list. |

---

## 5. Inventory writes (`application/inventory.py`)
Commands take a frozen input and a keyword-only `actor`: `create_license(CreateLicenseInput)`,
`update_license(UpdateLicenseInput)`, `delete_license(DeleteLicenseInput)`. Access: lab coordinators and
admins (`LABS_STAFF_ACCESS`).

### 5.1 Request body (create and update)

| Field | On create | Notes |
|---|---|---|
| `sku` | required | Fixed after creation: sending it on `PATCH` is `409 resource_field_immutable`. Unique among live licenses. |
| `product_id`, `vendor_id`, `type_id`, `category_id` | required | Must exist. The vendor must match the product's vendor. |
| `restriction_id`, `department_id`, `group_id`, `owner_id` | optional, nullable | Must exist. A group must belong to the department. |
| `name`, `remark`, `max_version` | optional | |
| `seats` | optional, default `1` | `1` to `32767`. |
| `expires_at` | optional, nullable | Date-time (stored as `expiry_date`). |
| `serial_number` | optional | Vendor's license serial or ID; trimmed; returned and searchable (`q`). A duplicate for the same vendor among live licenses → `409` |
| `identifier` | optional | **The license key. Write-only: never returned by any endpoint and kept out of `repr` and logs.** |

Unknown keys are rejected with `422`. Update is partial: only the keys sent change. Responses are the
license as in `GET /api/labs/licenses/{id}`.

### 5.2 Errors

| Case | Status |
|---|---|
| Missing or invalid field, unknown reference, product and vendor mismatch | `422` |
| Duplicate `sku` among live licenses | `409 license_conflict` |
| `seats` lower than the seats in use | `409 license_conflict` |
| Delete while the license is assigned to equipment | `409 license_conflict` |
| Unknown or already deleted license | `404` |
| Caller is not a coordinator or admin | `403` |

### 5.3 Concurrency and idempotency
- Update and delete lock the license row (`select_for_update`) in one transaction. Assignment commands lock
  the same row first, so the seat and assignment counts a write reads cannot change underneath it.
- SKU uniqueness among live licenses is a PostgreSQL constraint of `ResourceModel`; two creates racing on one
  SKU end with one `201` and one `409`.
- Delete is a soft delete; the SKU becomes reusable. Deleting an already deleted license is `404`.
- Create is not idempotent: a retry after a timeout returns `409` once the first request succeeded.

Status changes, assignment, agreements, images and acquisition price (from procurement allocation) keep
their own routes.

### 5.4 Assignment and seats
- A license read (`GET /licenses`, `GET /licenses/{id}`, and the responses of the write routes) carries
  `assigned_equipment`: the live equipment items that hold a seat, as `{id, uid, sku, name}`, oldest assignment
  first. Deleted equipment is left out. It is loaded with one extra query per page, not one per license.
- Assigning is the action `POST /licenses/{id}/actions/assign` with `{equipment_id}`; releasing is
  `DELETE` on the same route. It is idempotent for the same equipment.
- `seats` is the number of equipment items that may hold the license at once. An assignment beyond it is
  `409 license_conflict`, checked under the license row lock, so concurrent assignments cannot overshoot.
- A client that wants "create and assign" or "change the assigned equipment" calls the create or update
  route and then the assign or release actions; each is its own transaction.
