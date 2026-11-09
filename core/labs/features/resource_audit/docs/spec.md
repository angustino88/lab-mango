# Feature Specification: Resource Auditing & Change Logs (`core/labs/features/resource_audit`)

## 1. Domain Overview & Purpose
The Resource Audit feature manages formal compliance inspections, periodic physical audits, and field-level immutable change logging across all laboratory assets (benches, equipment, licenses, rooms, stations).

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.ResourceAudit`
- **Fields:**
  - `resource_content_type` (FK `ContentType`, PROTECT).
  - `resource_object_id` (CharField(64)).
  - `resource` (GenericForeignKey).
  - `audited_at` (DateTimeField).
  - `auditor` (FK `AUTH_USER_MODEL`, PROTECT).
  - `overall_result`: Enum (`PASS`, `FAIL`, `NOT_ASSESSED`).
  - `summary` (CharField), `details` (TextField).

### 2.2 `core.labs.models.ResourceAuditItem`
- Line-item verification checks against specific audit criteria (`criteria`, `result`, `notes`).

### 2.3 `core.labs.models.ResourceChangeLog`
- Immutable delta log tracking entity mutations:
  - `action`: Enum (`create`, `update`, `delete`, `restore`).
  - `field_name`, `old_value`, `new_value`, `changed_at`, `actor`.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/resource-audits` | `ResourceAuditListCreateAPIView` | Filtered list of historical audit reports. |
| `POST /api/labs/resource-audits` | `ResourceAuditListCreateAPIView` | Record a formal compliance audit inspection. |
| `GET /api/labs/resource-audits/{id}` | `ResourceAuditDetailAPIView` | Audit report detail with checklist criteria. |
| `GET /api/labs/resource-audits/change-logs` | `ResourceChangeLogListAPIView` | Chronological field-level state change audit logs. |
