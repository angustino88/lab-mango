# Feature Specification: Equipment Management (`core/labs/features/equipment`)

## 1. Domain Overview & Purpose
The Equipment feature manages the physical and logical lifecycle of hardware devices, laboratory test equipment, computing stations, display screens, and accessories. It owns equipment identity, status state machines, category-specific configurations, and bench assignments.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Equipment`
- **Inheritance:** `ResourceModel` (`uid`, `sku`, `name`, `group`, `owner`, `remark`, `image`, `created`, `modified`, `deleted_at`).
- **Key Fields:**
  - `kind` (FK `EquipmentKind`, PROTECT).
  - `type` (FK `EquipmentType`, PROTECT, optional).
  - `manufacturer` (FK `EquipmentManufacturer`, PROTECT, optional).
  - `product_model` (FK `EquipmentProductModel`, PROTECT, optional).
  - `serial_number`, `log_label` (CharField(255), blank=True, default="").
  - `details` (TextField), `metadata` (JSONField).
  - `replacement_date` (DateField, optional).
  - `licenses` (ManyToManyField `License`, through `LicenseAssignment`).
- **DB Invariants:**
  - Soft-deletion via `deleted_at`. Active SKUs must be unique.
  - Deletion of an active equipment kind or type referenced by an active equipment instance is protected (`on_delete=PROTECT`).

### 2.2 Category Polymorphic Specializations (1:1 with `Equipment`)
- `ComputingEquipment`: `ip_address`, `os_name`, `disk_usage`, `system_info`, `hostname`, `mac_address`, `monitored_devices`, `rdp_file`, `technical_user`.
- `DisplayEquipment`: `resolution`, `size`, `interface`.
- `FurnitureEquipment`: `material`.
- `InstrumentEquipment`: `interface`.
- `MechanicalEquipment`, `NetworkingEquipment`, `PowerEquipment`, `SampleEquipment`, `AccessoryEquipment`, `DebuggingEquipment`, `LaboratoryEquipment`, `OtherEquipment`.

### 2.3 `core.labs.models.EquipmentAssignment`
- **Fields:**
  - `bench` (FK `Bench`, PROTECT), `equipment` (FK `Equipment`, PROTECT).
  - `role` (CharField(64), default="default").
  - `position` (PositiveIntegerField, default=0).
  - `monitor` (BooleanField, default=False).
  - `assigned_at` (DateTimeField), `unassigned_at` (DateTimeField, nullable).
- **PostgreSQL Invariants:**
  - `one_active_bench_per_equipment`: Unique constraint on `equipment` where `unassigned_at IS NULL`.
  - `assignment_end_after_start`: `CheckConstraint(unassigned_at IS NULL OR unassigned_at >= assigned_at)`.
  - Partial index on `(bench, position)` where `unassigned_at IS NULL`.

---

## 3. Options Standard Compliance (ADR 002)
`GET /api/labs/equipment/options` strictly returns flat:
```json
{
  "data": [
    { "id": 1, "sku": "EQ-COMP-001", "name": "MacBook Pro 16" }
  ]
}
```
- Query filter parity with list view (supports `assignable=true`, `kind`, `type`, `manufacturer`, `status`, `search`).
- Fast query projected with `.only("id", "sku", "name")`.

---

## 4. API Endpoints & Transport Contracts

### Computing field ownership
- `ip_address`, `os_name`, `system_info`, and `disk_usage` are agent-owned snapshot fields. `hostname` is agent-reported inventory data. They are returned where configured for reading, but category create/update requests reject them as unknown or read-only.
- The authenticated agent snapshot endpoint described in `docs/agent-platform/backend-api.md` is not implemented yet. Until it is available, these values cannot be changed through the category API.
- `rdp_file` is server-generated and is also rejected on category create/update. `mac_address` remains user-editable on create; `monitored_devices` and `technical_user` remain editable on update. Agent writes to `technical_user` are prohibited by the agent contract.
- The computing agent snapshot endpoint is not implemented. Agent-owned fields remain readable through category detail responses, but this API currently offers no agent ingestion path.
- `hostname` is excluded from computing list responses until the agent snapshot endpoint exists; detail retains its read-only projection.
- Lifecycle status is read-only in category create/update and changes through the separate `actions/change-status` action. Status-action `details` are status-record metadata, not the equipment `details` field.
- Audit result/remarks are managed by the resource-audit API, not category payloads. Authenticated equipment creation currently still creates a server-generated `NOT_ASSESSED` audit record; this behavior is retained.
- Equipment `details`, shared-resource `remark`, status-record metadata, and per-audit `remarks` remain separate stored concepts. Do not consolidate them without an approved data and API compatibility plan.

| Method & Path | View Class | Request / Contract | Purpose |
|---|---|---|---|
| `GET /api/labs/equipment` | `EquipmentListCreateAPIView` | FilterSet query params | Paginated equipment inventory list. |
| `POST /api/labs/equipment` | `EquipmentListCreateAPIView` | `EquipmentCreateSerializer` | Create new equipment instance. |
| `GET /api/labs/equipment/{id}` | `EquipmentRetrieveAPIView` | Path `{id}` | Retrieve equipment details with assignments. |
| `PATCH /api/labs/equipment/{id}` | `EquipmentRetrieveAPIView` | `EquipmentUpdateSerializer` | Update equipment metadata. |
| `DELETE /api/labs/equipment/{id}` | `EquipmentRetrieveAPIView` | Path `{id}` | Soft delete equipment record. |
| `GET /api/labs/equipment/options` | `EquipmentOptionsAPIView` | Options query params | Dropdown selector `{id, sku, name}`. |
| `GET /api/labs/equipment/filters` | `EquipmentFiltersAPIView` | None | Available filter metadata schema. |
| `GET /api/labs/equipment/reference-data` | `EquipmentReferenceDataAPIView` | None | Category kinds, types, manufacturers. |
| `GET /api/labs/equipment/status-summary` | `EquipmentStatusSummaryAPIView` | Query filters | Aggregated count per operational status. |
| `GET /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | Path `{equipment_id}` | Active bench assignment detail. |
| `POST /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | `EquipmentAssignmentSerializer` | Assign equipment to bench. |
| `DELETE /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | Path `{equipment_id}` | Unassign equipment from current bench. |
| `GET /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | Path `{equipment_id}` | Active placement of any kind (bench, station, room, untracked place); 404 when the location is unknown. |
| `PUT /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | `EquipmentPlacementWriteSerializer` | Set where the unit is; 409 `equipment_already_placed` when it is on a bench and the target differs. |
| `DELETE /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | Path `{equipment_id}` | Remove the active placement; 204 also when there is none. |
| `POST /api/labs/equipment/{id}/actions/change-status` | `EquipmentStatusAPIView` | `EquipmentStatusSerializer` | Transition lifecycle state. |
| `GET /api/labs/equipment/computing/activity-summary` | `ComputingActivitySummaryAPIView` | None | Summary of monitored computing units. |
| `GET /api/labs/equipment/computing/sku/{sku}/activity` | `ComputingActivityAPIView` | Path `{sku}` | Telemetry logs for computing unit. |
