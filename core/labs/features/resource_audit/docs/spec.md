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

## 4. Audit tool endpoints (desktop scanner)

Design: `docs/proposals/resource-audit-scanner.md`. Client guide: `docs/proposals/resource-audit-scanner-tool.md`.
Section 3 above predates the current routes (`api/urls.py`); correcting it is a separate task.

| Method & Path | View Class | Contract |
|---|---|---|
| `GET /api/labs/audit-catalog` | `AuditCatalogAPIView` | Cursor-paged list of every auditable resource (equipment, bench, station, room, license). First page: optional `changed_since`, `page_size` (default 500, max 1000). Next pages: `cursor` alone. `meta.server_time` is the next `changed_since`. Never returns `License.identifier`. |
| `POST /api/labs/resources/uid/{uid}/audits` | `ResourceAuditByUidView` | Records one audit. Optional `Idempotency-Key` (1-128 chars): same key and body replays the stored audit with `Idempotency-Replayed: true`; a different body returns `422 idempotency_key_reuse`. |
| `GET /api/labs/equipment/uid/{uid}` | `EquipmentByUIDAPIView` (equipment feature) | Equipment detail; accepts the Entra access token for reads only. |

Invariants:
- One audit per `(auditor, idempotency_key)`: constraint `resource_audit_idempotency_uniq`, plus a transaction-scoped
  advisory lock on the same pair, so concurrent retries wait and replay instead of failing.
- Audit results never change lifecycle state, condition, booking or assignment status.

Catalog fields: `status` is equipment `lifecycle_state`, bench `lifecycle_status`, or the newest status record
of a station, room or license; `expiry_date` is set for licenses only. A delta (`changed_since`) also returns
rows whose location parent was renamed (bench ← station, station ← room, room ← building) or that got a new
status record, so locations and statuses do not go stale.

Query performance: one query per type per page (status via a subquery on `<type>_status_latest_idx`).
`modified` is not indexed (decision 2026-11-12: measure first). Add an index on `modified` for a model only when
it passes about 50,000 rows or a delta query on it takes over about 50 ms. Measure with, for example:
`EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM labs_equipment WHERE modified >= now() - interval '1 day' OR
deleted_at >= now() - interval '1 day' ORDER BY id LIMIT 501;`

Authentication: these three views accept a Microsoft Entra delegated access token with scope
`ENTRA_API_AUDIT_SCOPE` (`core.users.features.auth.access_token`) in addition to the Lab Mango JWT. The token's
`tid`/`oid` must map to an active, already bound `EntraIdentity`; an unlinked subject gets
`401 entra_identity_not_linked` (sign in to the web frontend once to link it). Authorization is unchanged: lab coordinators
and admins. Settings: `ENTRA_API_ACCESS_TOKENS_ENABLED`, `ENTRA_API_AUDIENCES`, `ENTRA_API_AUDIT_SCOPE`, checked at startup
(`users.E010`-`E013`). Verify a real token with `python manage.py check_entra_access_token < token.txt`: it
prints pass/fail per check and never the token.
