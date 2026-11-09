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
  - `identifier` (CharField(255), license asset key).
  - `expiry_date` (DateTimeField, nullable).
  - `status`: Enum (`available`, `assigned`, `expired`, `revoked`, `suspended`). Default: `available`.

### 2.2 `core.labs.models.LicenseAssignment`
- **Fields:** `license` (FK `License`, PROTECT), `equipment` (FK `Equipment`, PROTECT), `assigned_at`, `unassigned_at` (nullable).
- **Invariant:** A software license can be actively assigned (`unassigned_at IS NULL`) to at most one equipment unit at a time.

### 2.3 `core.labs.models.LicenseAgreement` & `LicensePayment`
- **`LicenseAgreement`**: `price` (DecimalField), `currency` (default "EUR"), `billing_period` (`one_time`, `monthly`, `quarterly`, `annual`), `valid_from`, `valid_until`.
- **`LicensePayment`**: Financial records of disbursement against agreements (`amount`, `paid_at`, `reference`).

---

## 3. Options Standard Compliance (`GEMINI.md`)
`GET /api/labs/licenses/options` provides selector options `{id, sku, name}`.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/licenses` | `LicenseListAPIView` | Filtered list of software licenses. |
| `POST /api/labs/licenses` | `LicenseListAPIView` | Register software license. |
| `GET /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | License details with active bindings. |
| `PATCH /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | Update license metadata. |
| `DELETE /api/labs/licenses/{id}` | `LicenseRetrieveAPIView` | Soft delete license. |
| `GET /api/labs/licenses/options` | `LicenseOptionsAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/licenses/status-summary` | `LicenseStatusSummaryAPIView` | Status count distribution. |
| `GET /api/labs/licenses/categories/summary` | `LicenseCategorySummaryAPIView` | License counts per category. |
| `POST /api/labs/licenses/{license_id}/actions/assign` | `LicenseAssignActionAPIView` | Bind license to computing unit. |
| `DELETE /api/labs/licenses/{license_id}/actions/assign` | `LicenseAssignActionAPIView` | Standard unassign command. |
| `POST /api/labs/licenses/{license_id}/actions/unassign` | `LicenseUnassignActionAPIView` | Deprecated alias with Sunset headers. |
| `POST /api/labs/licenses/{license_id}/actions/change-status` | `LicenseStatusAPIView` | Update lifecycle state. |
| `GET/POST /api/labs/licenses/{license_id}/agreements` | `LicenseAgreementListCreateAPIView` | Commercial agreements list. |
