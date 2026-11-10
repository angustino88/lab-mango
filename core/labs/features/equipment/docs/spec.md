# Feature Specification: Equipment Management (`core/labs/features/equipment`)

## 1. Domain Overview & Purpose
The Equipment feature manages the physical and logical lifecycle of hardware devices, laboratory test equipment, computing stations, display screens, and accessories. It owns equipment identity, the lifecycle-state and condition state machines, category-specific configurations, and placement (where each unit is: bench, station, room, or an untracked place). Section 2.0 explains what each state means in practice.

---

## 2. Data Models & Database Invariants

### 2.0 Equipment state at a glance

Three separate facts describe a unit. They are stored and changed independently; one label is computed from them for display.

| Fact | Question it answers | Values | Changed by |
|---|---|---|---|
| `lifecycle_state` | Does the lab still have it? | `planned`, `in_service`, `transferred_out`, `retired`, `lost` | `POST .../actions/change-lifecycle` only |
| `condition` | Does it work? | `operational`, `in_maintenance`, `out_of_service` | `POST .../actions/change-condition` only (while `in_service`) |
| placement | Where is it? | a bench, a station, a room, only a `location_note`, or none (unknown) | `PUT` / `DELETE .../placement` (and the bench `/assignment` routes) |
| `display_status` (computed) | One label for lists and counts | see below | never written |

**`in_service` does not mean "on a bench".** It means the lab owns the unit and it is part of the active inventory, wherever it is. Being on a bench is a placement and shows as `display_status = in_use`.

| Situation | `lifecycle_state` | placement | `display_status` |
|---|---|---|---|
| Mounted on bench B-12 | `in_service` | bench B-12 | `in_use` |
| Removed from the bench and put in Room 5 | `in_service` | Room 5 | `available` |
| Removed from the bench, place not recorded | `in_service` | none | `available` |
| In storage ("Cabinet 3, shelf B") | `in_service` | note only | `available` |
| On bench B-12 but broken | `in_service` | bench B-12 | `broken` |
| Ordered, not delivered | `planned` | none, or a room while waiting | `on_order` |
| Given to a partner lab | `transferred_out` | none | `transferred` |

**Removing a unit from a bench** (`DELETE .../placement` or `.../assignment`) closes only the bench placement. `lifecycle_state` stays `in_service` and `condition` is unchanged, so `display_status` goes from `in_use` to `available` (or `maintenance`, `broken`, `calibration_overdue` if one applies). The unit's location is unknown until it is placed again. Only `change-lifecycle` moves a unit to another lifecycle state (for example `retired` when scrapped, `lost` when it cannot be found).

**Equipment in storage** is a unit placed in a room, at a station, or at an untracked place (`location_note`). It displays as `available`; where it is shows in `placement`. There is no `in_storage` label, because no field marks a room as a storage room (open question 2 in the redesign proposal).

**Lifecycle transitions** (anything else returns 409 `invalid_state_transition`; the same state is a no-op):

| From | To |
|---|---|
| `planned` | `in_service`, `retired` |
| `in_service` | `transferred_out`, `retired`, `lost` |
| `lost` | `in_service` (found), `retired` |
| `transferred_out` | `in_service` (handed back) |
| `retired` | none (final) |

- Leaving `in_service` resets `condition` to `operational` (its own event).
- Entering `transferred_out`, `retired`, or `lost` is refused while the unit is on a bench (409 `equipment_already_placed`); any other placement is closed and reserved equipment bookings are cancelled with the given reason. `transferred_out` requires `receiving_organisation`.
- Marking a unit `lost` is always a manual action; no timer sets it.

**Placement rules:** only an `in_service` unit can be placed on a bench; `transferred_out`, `retired`, and `lost` units cannot be placed anywhere. A unit resting in a room, at a station, or at a noted place moves directly to a new place; a unit on a bench must be removed from the bench first (409 `equipment_already_placed`). Changing `condition` never moves a unit.

**`display_status`** is computed in SQL; the first matching row wins:

| Priority | When | `display_status` |
|---|---|---|
| 1 | `lifecycle_state` is not `in_service` | `on_order` (planned), `transferred`, `retired`, `lost` |
| 2 | `condition = out_of_service` | `broken` |
| 3 | `condition = in_maintenance` | `maintenance` |
| 4 | active bench placement | `in_use` |
| 5 | calibration required and overdue | `calibration_overdue` |
| 6 | otherwise | `available` |

`borrowed` is added with loans (redesign step 3). The full design and its rationale are in `docs/proposals/equipment-management-redesign.md`.

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
  - `lifecycle_state` (CharField(32), indexed, default `in_service`; `planned` or `in_service` at creation).
  - `condition` (CharField(32), indexed, default `operational`).
  - `licenses` (ManyToManyField `License`, through `LicenseAssignment`).
- **DB Invariants:**
  - Soft-deletion via `deleted_at`. Active SKUs must be unique.
  - Deletion of an active equipment kind or type referenced by an active equipment instance is protected (`on_delete=PROTECT`).
  - `equipment_lifecycle_valid`, `equipment_condition_valid`: values must be in their enumerations.
  - `equipment_condition_only_in_service`: `condition = 'operational'` unless `lifecycle_state = 'in_service'`.

### 2.2 Category Polymorphic Specializations (1:1 with `Equipment`)
- `ComputingEquipment`: `ip_address`, `os_name`, `disk_usage`, `system_info`, `hostname`, `mac_address`, `monitored_devices`, `rdp_file`, `technical_user`.
- `DisplayEquipment`: `resolution`, `size`, `interface`.
- `FurnitureEquipment`: `material`.
- `InstrumentEquipment`: `interface`.
- `MechanicalEquipment`, `NetworkingEquipment`, `PowerEquipment`, `SampleEquipment`, `AccessoryEquipment`, `DebuggingEquipment`, `LaboratoryEquipment`, `OtherEquipment`.

### 2.3 `core.labs.models.EquipmentAssignment` (placement) and the `EquipmentPlacement` proxy
One table records every placement. `EquipmentAssignment.objects` returns bench placements only (the historic meaning of "assignment"); `EquipmentAssignment.all_placements` and the proxy `EquipmentPlacement` return every placement.
- **Fields:**
  - `equipment` (FK `Equipment`, PROTECT).
  - `bench` (FK `Bench`), `station` (FK `Station`), `room` (FK `Room`): all PROTECT and nullable; at most one is set.
  - `location_note` (CharField(255)): required when no target is set; otherwise an optional detail such as a shelf.
  - `role` (CharField(64), default="default"), `position` (PositiveIntegerField, default=0), `monitor` (BooleanField, default=False): bench placements only.
  - `assigned_at` (DateTimeField), `unassigned_at` (DateTimeField, nullable; null is the active placement).
- **PostgreSQL Invariants:**
  - `one_active_bench_per_equipment`: unique `equipment` where `unassigned_at IS NULL` (one active placement of any kind per unit).
  - `equipment_placement_one_target`: exactly one of bench, station, room, or none with a non-empty `location_note`.
  - `equipment_placement_bench_fields`: `role`, `position`, `monitor` at their defaults unless `bench` is set.
  - `assignment_end_after_start`: `CheckConstraint(unassigned_at IS NULL OR unassigned_at >= assigned_at)`.
  - Partial index on `(bench, position)` where `unassigned_at IS NULL`.

### 2.4 `core.labs.models.EquipmentEvent`
Append-only history of lifecycle and condition changes, written only by `change_lifecycle`, `change_condition`, and creation.
- **Fields:** `equipment` (FK, PROTECT), `axis` (`lifecycle` or `condition`), `from_value` (empty for the initial state), `to_value`, `reason` (CharField(500)), `details` (JSON, for example `receiving_organisation`, `transfer_date`, `cancelled_booking_ids`), `actor` (FK user, nullable), `occurred_at`.
- **PostgreSQL Invariants:** `equipment_event_changes` (`from_value <> to_value`), `equipment_event_value_valid` (`to_value` belongs to the axis's enumeration).

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
- Query filter parity with list view (supports `assignable=true` (display status `available`), `kind`, `type`, `manufacturer`, `status` (display status), `lifecycle_state`, `search`).
- Fast query projected with `.only("id", "sku", "name")`.

---

## 4. API Endpoints & Transport Contracts

### Computing field ownership
- `ip_address`, `os_name`, `system_info`, and `disk_usage` are agent-owned snapshot fields. `hostname` is agent-reported inventory data. They are returned where configured for reading, but category create/update requests reject them as unknown or read-only.
- The authenticated agent snapshot endpoint described in `docs/agent-platform/backend-api.md` is not implemented yet. Until it is available, these values cannot be changed through the category API.
- `rdp_file` is server-generated and is also rejected on category create/update. `mac_address` remains user-editable on create; `monitored_devices` and `technical_user` remain editable on update. Agent writes to `technical_user` are prohibited by the agent contract.
- The computing agent snapshot endpoint is not implemented. Agent-owned fields remain readable through category detail responses, but this API currently offers no agent ingestion path.
- `hostname` is excluded from computing list responses until the agent snapshot endpoint exists; detail retains its read-only projection.
- Lifecycle state and condition are read-only in update and change only through `actions/change-lifecycle` and `actions/change-condition`; history is `EquipmentEvent`. `display_status` is computed, never written.
- Audit result/remarks are managed by the resource-audit API, not category payloads. Authenticated equipment creation currently still creates a server-generated `NOT_ASSESSED` audit record; this behavior is retained.
- Equipment `details`, shared-resource `remark`, `EquipmentEvent.details`, and per-audit `remarks` remain separate stored concepts. Do not consolidate them without an approved data and API compatibility plan.

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
| `POST /api/labs/equipment/{id}/actions/change-condition` | `EquipmentChangeConditionAPIView` | `EquipmentChangeConditionSerializer` | Set operational / in maintenance / out of service (in service only). |
| `POST /api/labs/equipment/{id}/actions/change-lifecycle` | `EquipmentChangeLifecycleAPIView` | `EquipmentChangeLifecycleSerializer` | Move along the lifecycle transition table. |
| `GET /api/labs/equipment/computing/activity-summary` | `ComputingActivitySummaryAPIView` | None | Summary of monitored computing units. |
| `GET /api/labs/equipment/computing/sku/{sku}/activity` | `ComputingActivityAPIView` | Path `{sku}` | Telemetry logs for computing unit. |
