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
| `condition` | Does it work? | `operational`, `in_maintenance`, `out_of_service` | Computed from `ResourceDowntime` windows (RS2), never stored. `POST .../actions/change-condition` (while `in_service`) opens a window starting now or ends the current one; scheduled windows: `/api/labs/downtimes` |
| placement | Where is it? | a bench, a station, a room, only a `location_note`, or none (unknown) | `PUT` / `DELETE .../placement` (and the bench `/assignment` routes) |
| loan | Who holds it, until when? | an open loan (borrower, due time) or none | `POST .../actions/hand-over`, `.../actions/return`, `.../actions/extend-loan` |
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
| Handed to Ada until Friday | `in_service` | none (an open loan instead) | `borrowed` |

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

- Leaving `in_service` ends the current downtime window and cancels windows planned for later, so `condition` reads `operational`.
- Returning from `lost` to `in_service` (found) opens an `in_maintenance` downtime window, so the unit shows `maintenance` and cannot be lent until someone inspects it and sets it back to `operational`. Returning from `planned` or `transferred_out` keeps `operational`.
- `retired` is final: no action leaves it.
- Entering `transferred_out`, `retired`, or `lost` is refused while the unit is on a bench (409 `equipment_already_placed`); any other placement is closed and reserved equipment bookings are cancelled with the given reason. `transferred_out` requires `receiving_organisation`.
- Marking a unit `lost` is always a manual action; no timer sets it.

**Placement rules:** only an `in_service` unit can be placed on a bench; `transferred_out`, `retired`, and `lost` units cannot be placed anywhere. `PUT .../placement` moves an item in one call from wherever it is (a bench included) to the new place or bench. The legacy `/assignment` route still refuses a different bench (409 `equipment_already_assigned`). Removing an item from a bench without a destination is allowed; its location is then unknown (owner decision, 2026-11-10). Changing `condition` never moves a unit.

**`display_status`** is computed in SQL; the first matching row wins:

| Priority | When | `display_status` |
|---|---|---|
| 1 | `lifecycle_state` is not `in_service` | `on_order` (planned), `transferred`, `retired`, `lost` |
| 2 | `condition = out_of_service` | `broken` |
| 3 | `condition = in_maintenance` | `maintenance` |
| 4 | open loan | `borrowed` (the `loan` object carries `overdue`) |
| 5 | active bench placement | `in_use` |
| 6 | calibration required and overdue | `calibration_overdue` |
| 7 | otherwise | `available` |

**Who sees equipment:** only lab coordinators and administrators (and API keys) can read or change equipment, its catalog, placements and loans. Engineers cannot see equipment at all; the coordinator records everything for them. Departments and groups stay readable by every signed-in user.

**Loans** (custody, not a booking). A **loan slip** (`EquipmentLoanBatch`) holds the borrower and purpose for one or more items handed over together; each item is its own loan line, so items can come back at different times. The borrower is a user account **or**, for people without one, a name with an optional contact (email or phone).
- Lend several items in one request (`POST /api/labs/equipment-loans`, `Idempotency-Key` required): all or nothing; the 409 lists each unavailable item with its reasons.
- Hand-over needs an available item: `in_service`, `operational`, not on a bench, not on loan, calibration not overdue (otherwise 409 `equipment_not_available` with `details.reasons`). Its room, station or noted place is closed: an item with a person has no placement. An item resting in a room, at a station, at a noted place, or with no recorded place can be lent; an item on a bench cannot. An item reserved by someone else in the loan window cannot be lent either.
- While on loan: placing it is refused (409 `equipment_on_loan`); its condition may change ("broken while on loan" shows `broken` with a `loan`); `transferred_out` and `retired` are refused; `lost` closes the loan with reason `lost`; delete is refused.
- Return closes the loan (`condition_in`) and can record the new condition and place in the same request; several items at once through `POST /api/labs/equipment-loans/actions/return` (any subset of what is out). A repeated return is a no-op.
**Reservations** (keep items for a borrower over a later window; coordinator-only, created approved). One `EquipmentBooking` per item, grouped on a loan slip with the borrower and purpose.
- Reserve several items at once (`POST /api/labs/equipment-reservations`, `Idempotency-Key` required): all or nothing. Refused per item (409 `booking_conflict`) when the item is not in service, is on a bench, is on loan with a due time after the reservation starts, or overlaps another reservation (`equipment_booking_no_overlap`). An item on loan today can be reserved for after its due time. Condition is checked at hand-over, not at reservation.
- While reserved: the window can move and items can be added or dropped (`PATCH`); lines can be cancelled with a reason (all or some). An item reserved by someone else cannot be lent across that window.
- Hand over from a reservation (all or listed items, all or nothing; any time before the end): the booking becomes `in_progress` and a loan opens, due at the reservation end. Return completes the booking; extending the loan moves the booking end (refused into the next reservation); marking the item lost cancels the booking.
- Not collected: the task `labs.equipment.expire_uncollected_reservations` marks reserved lines whose start day (local time) has ended as `expired`. It is not scheduled by code: an operator adds it in Django admin under Django Celery Beat > Periodic tasks (suggested hourly).
- Equipment responses carry `reservations` (reserved windows that have not ended), prefetched once per page.

- Overdue is computed (open and past `due_at`), never stored; list filters `on_loan` and `loan_overdue`; the coordinator's overdue list is `GET /api/labs/equipment-loans?overdue=true`.
- **Overdue reminder emails** (one per slip, listing every overdue item): at the due time, one day later, then daily, capped at one week (slots 0 to 7; `equipment_loan_reminder_once_per_slot` makes each slot at most one email). A missed slot is not sent late. Recipient: the borrower's account email, else `borrower_contact` when it is an email address; otherwise no email (coordinator list only). A slip whose items are back is skipped. Failed sends are retried with backoff, up to 5 attempts. Each slip shows its `reminders` (slot, state, recipient).
- Reminder jobs are not scheduled by code; an operator adds them in Django admin under Django Celery Beat > Periodic tasks: `labs.equipment.collect_overdue_reminders` (suggested hourly) and `labs.equipment.deliver_overdue_reminders` (suggested every 5 minutes). Email uses the SMTP settings (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`); without them, sends fail and are retried, then marked failed.

The full design and its rationale are in `docs/proposals/equipment-management-redesign.md`.

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
  - No `condition` column: condition is computed from `ResourceDowntime` (design `docs/proposals/resource-status-and-downtime.md`).
  - `licenses` (ManyToManyField `License`, through `LicenseAssignment`).
  - Typed fields shared by categories (step 6, decision A), all optional: `mac_address`, `channels`,
    `power_rating`, `dimensions` (JSON), `material`, `size`, `resolution`, `protocol`, `customer` (FKs,
    PROTECT), `interfaces`, `characteristics` (many-to-many).
- **DB Invariants:**
  - Soft-deletion via `deleted_at`. Active SKUs must be unique.
  - Deletion of an active equipment kind or type referenced by an active equipment instance is protected (`on_delete=PROTECT`).
  - `equipment_lifecycle_valid`: values must be in the enumeration.
  - Downtime can be recorded only for an in-service unit; leaving service closes it (application rule).

### 2.2 One table for every category (redesign step 6)
- There are no category subclasses. The category of a unit is `kind.category`; a category created at runtime
  works with no model, migration or route.
- Which typed fields a category uses is `CATEGORY_TYPED_FIELDS` in `application/_category.py`:

  | Category | Typed fields |
  |---|---|
  | computing | `mac_address` (+ `ComputingProfile`) |
  | display | `size`, `resolution`, `interfaces` |
  | furniture, mechanical | `dimensions`, `material` |
  | instrument | `interfaces` |
  | networking | `protocol`, `mac_address` |
  | power | `channels`, `interfaces`, `power_rating` |
  | sample | `customer`, `interfaces`, `characteristics` |
  | any other | none |

  Create and update refuse a typed field the category does not use (422). Moving a unit to another category is
  refused while it still holds a value the new category does not use.
- `EquipmentCategory` flags, checked by the commands: `bookable` (lend and reserve), `placeable_on_bench`
  (bench assignment), `calibratable` (`calibration_required` allowed), `monitored` (computing profile, agent,
  activity). Seeded categories: all flags on except `monitored`, which is on for Computing only.
- `ComputingProfile` (`core.labs.models`): one-to-one with `Equipment`, primary key = equipment id,
  `related_name="computing_profile"`. Columns `hostname`, `ip_address`, `os_name`, `disk_usage`, `system_info`,
  `monitored_devices`, `rdp_file`, `technical_user`. A unit has a profile exactly when its category is
  `monitored`: `create_equipment` creates it with the activity record; `update_equipment` creates it when a unit
  moves into a monitored category and refuses to move a unit with a profile out of one. The .rdp file is written
  by `application/computing_profile.sync_rdp_file` on create and when the SKU, hostname or technical user
  changes (no longer in `save()`).
- `ComputingActivity.computing`, `LabSessionLog.computing_equipment`, `MonitoringEvent.computer` and
  `AgentIdentity.equipment` point at `Equipment`; "is computing" means `computing_profile__isnull=False`.

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

### 2.4 `core.labs.models.EquipmentLoan`
- **`EquipmentLoanBatch` (loan slip):** `borrower` (FK user, nullable), `borrower_name`, `borrower_contact`, `purpose`, `created_by`, idempotency key. Check `equipment_loan_batch_has_borrower` (user or name); unique (`created_by`, `idempotency_key`).
- **Fields:** `equipment` (FK, PROTECT), `batch` (FK `EquipmentLoanBatch`, PROTECT), `booking` (one-to-one `EquipmentBooking`, nullable), `handed_over_at`, `handed_over_by`, `due_at`, `returned_at` (null while open), `received_by`, `condition_out`, `condition_in` (CharField(255)), `close_reason` (`returned`, `lost`; null while open). No code (OD4).
- **PostgreSQL Invariants:** `one_active_loan_per_equipment` (unique `equipment` where `returned_at IS NULL`), `equipment_loan_closed_has_reason`, `equipment_loan_close_reason_valid`, `equipment_loan_due_after_handover`, `equipment_loan_returned_after_handover`.

### 2.5 `core.labs.models.EquipmentEvent`
Append-only history of lifecycle changes, written only by `change_lifecycle` and creation. Condition history is the downtime windows.
- **Fields:** `equipment` (FK, PROTECT), `axis` (`lifecycle`), `from_value` (empty for the initial state), `to_value`, `reason` (CharField(500)), `details` (JSON, for example `receiving_organisation`, `transfer_date`, `cancelled_booking_ids`), `actor` (FK user, nullable), `occurred_at`.
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

### One collection (step 6, decision B; breaking change approved by the owner)
- The 12 per-category route sets (`/equipment/<category>`, `/equipment/<category>/{pk}`, `.../sku/...`,
  `.../uid/...`, `.../filters`, `.../facets`, `.../options`, `.../summary`, `.../reference-data`,
  `.../actions/...`) are removed. Use `/equipment` with `category=<id>` (list, facets), `category_id` (options)
  or `category` (reference data, status summary).
- List and detail return every typed field; fields the category does not use are `null` or empty. `computing`
  is the `ComputingProfile` (`null` for other units); the detail adds `activity` and `details`.
- Write payloads: typed foreign keys as `<name>_id`, many-to-many as `<name>_ids`; `computing` is a nested
  object (`hostname` on create; `monitored_devices`, `technical_user_id` on update).

### Computing field ownership
- `ip_address`, `os_name`, `system_info`, and `disk_usage` are agent-owned snapshot fields and are never written
  through the API. `hostname` is entered at registration (it names the RDP host).
- The authenticated agent snapshot endpoint described in `docs/agent-platform/backend-api.md` is not implemented yet.
- `rdp_file` is server-generated. `mac_address` is a shared column; `computing.monitored_devices` and
  `computing.technical_user_id` are editable on update. Agent writes to `technical_user` are prohibited by the
  agent contract.
- Lifecycle state and condition are read-only in update and change only through `actions/change-lifecycle` and `actions/change-condition` (or the downtime API); history is `EquipmentEvent` and `ResourceDowntime`. `display_status` is computed, never written.
- Audit result/remarks are managed by the resource-audit API, not category payloads. Authenticated equipment creation currently still creates a server-generated `NOT_ASSESSED` audit record; this behavior is retained.
- Equipment `details`, shared-resource `remark`, `EquipmentEvent.details`, and per-audit `remarks` remain separate stored concepts. Do not consolidate them without an approved data and API compatibility plan.

| Method & Path | View Class | Request / Contract | Purpose |
|---|---|---|---|
| `GET /api/labs/equipment` | `EquipmentCollectionAPIView` | Filters incl. `category`, typed `*_id` filters, `q` | Paginated inventory of every category. |
| `POST /api/labs/equipment` | `EquipmentCollectionAPIView` | `EquipmentCreateSerializer` | Create a unit of any category. |
| `GET` / `PATCH` / `PUT` / `DELETE /api/labs/equipment/{pk}` | `EquipmentDetailAPIView` | `EquipmentUpdateSerializer` | Read, change or soft-delete one unit. |
| `GET` / `PATCH /api/labs/equipment/sku/{sku}`, `/api/labs/equipment/uid/{uid}` | `EquipmentBySKUAPIView`, `EquipmentByUIDAPIView` | `EquipmentUpdateSerializer` | Same, by business key. |
| `GET /api/labs/equipment/facets` | `EquipmentCollectionFacetsAPIView` | `dimension` + list filters | Counts per dimension. |
| `GET /api/labs/equipment/options` | `EquipmentOptionsAPIView` | Options query params | Dropdown selector `{id, sku, name}`. |
| `GET /api/labs/equipment/filters` | `EquipmentFiltersAPIView` | None | Available filter metadata schema. |
| `GET /api/labs/equipment/reference-data` | `EquipmentReferenceDataAPIView` | Optional `category` | Form catalogs and typed lookups, narrowed to one category. |
| `GET /api/labs/equipment/status-summary` | `EquipmentStatusSummaryAPIView` | Optional `category` | Count per display status. |
| `GET /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | Path `{equipment_id}` | Active bench assignment detail. |
| `POST /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | `EquipmentAssignmentSerializer` | Assign equipment to bench. |
| `DELETE /api/labs/equipment/{equipment_id}/assignment` | `EquipmentAssignmentAPIView` | Path `{equipment_id}` | Unassign equipment from current bench. |
| `GET /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | Path `{equipment_id}` | Active placement of any kind (bench, station, room, untracked place); 404 when the location is unknown. |
| `PUT /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | `EquipmentPlacementWriteSerializer` | Set where the item is; moves it in one call from its current place or bench. |
| `GET /api/labs/equipment/{equipment_id}/loan` | `EquipmentLoanAPIView` | Path `{equipment_id}` | Open loan; 404 when nobody holds the item. |
| `POST /api/labs/equipment/{equipment_id}/actions/hand-over` | `EquipmentHandOverAPIView` | `EquipmentHandOverSerializer` | Open a one-line slip (`borrower_id` or `borrower_name`, `borrower_contact`, `purpose`, `due_at`, `condition_out`). |
| `GET /api/labs/equipment-loans` | `EquipmentLoanListCreateAPIView` | Query `open`, `overdue`, `borrower_id`, `borrower_name`, `equipment_id`, `batch_id` | Loan lines, newest first. |
| `POST /api/labs/equipment-loans` | `EquipmentLoanListCreateAPIView` | `EquipmentLendBatchSerializer`; `Idempotency-Key` header | Lend several items to one borrower; all or nothing. |
| `POST /api/labs/equipment-loans/actions/return` | `EquipmentLoanReturnBatchAPIView` | `EquipmentReturnBatchSerializer` | Take several items back; all or nothing. |
| `POST /api/labs/equipment-loans/actions/extend` | `EquipmentLoanExtendBatchAPIView` | `EquipmentExtendLoansSerializer` | Move `due_at` for listed items or every open line of a slip. |
| `GET /api/labs/equipment-reservations` | `EquipmentReservationListCreateAPIView` | Query `status` (default `reserved`), `equipment_id`, `batch_id`, `starts_before`, `ends_after`, `borrower_name` | Reservation lines by start time. |
| `POST /api/labs/equipment-reservations` | `EquipmentReservationListCreateAPIView` | `EquipmentReserveSerializer`; `Idempotency-Key` header | Reserve several items for one borrower and window; all or nothing. |
| `GET` / `PATCH /api/labs/equipment-reservations/{batch_id}` | `EquipmentReservationDetailAPIView` | `EquipmentReservationUpdateSerializer` | The slip with its lines; move the window, add or drop items. |
| `POST /api/labs/equipment-reservations/{batch_id}/actions/cancel` | `EquipmentReservationCancelAPIView` | `EquipmentReservationCancelSerializer` | Cancel all or listed reserved lines with a reason. |
| `POST /api/labs/equipment-reservations/{batch_id}/actions/hand-over` | `EquipmentReservationHandOverAPIView` | `EquipmentReservationHandOverSerializer` | Hand over all or listed reserved items. |
| `GET /api/labs/equipment-loan-batches/{batch_id}` | `EquipmentLoanBatchAPIView` | Path `{batch_id}` | One slip with all its lines. |
| `POST /api/labs/equipment/{equipment_id}/actions/return` | `EquipmentReturnAPIView` | `EquipmentReturnSerializer` | Close the loan; optional `condition` and new place. |
| `POST /api/labs/equipment/{equipment_id}/actions/extend-loan` | `EquipmentExtendLoanAPIView` | `EquipmentExtendLoanSerializer` | Move `due_at` of a loan without a booking. |
| `DELETE /api/labs/equipment/{equipment_id}/placement` | `EquipmentPlacementAPIView` | Path `{equipment_id}` | Remove the active placement; 204 also when there is none. |
| `POST /api/labs/equipment/{id}/actions/change-condition` | `EquipmentChangeConditionAPIView` | `EquipmentChangeConditionSerializer` | Set operational / in maintenance / out of service now (in service only): opens or ends a downtime window; does not check reservations; refused when downtime is already planned for later. |
| `POST /api/labs/equipment/{id}/actions/change-lifecycle` | `EquipmentChangeLifecycleAPIView` | `EquipmentChangeLifecycleSerializer` | Move along the lifecycle transition table. |
| `GET /api/labs/equipment/{equipment_id}/status-changes` | `EquipmentStatusChangeListAPIView` | Page query only | `display_status` history, newest first: `previous_display_status` (null on the creation row), `display_status`, `occurred_at`, `actor`, `reason`, `details`. Replayed from lifecycle and condition events, loans and bench placements (`queries/status_history.py`); facts written by one command within 2 s are one step; calibration is not replayed; at most 500 newest rows per source. 404 for a missing or deleted unit. |
| `GET /api/labs/equipment/computing/activity-summary` | `ComputingActivitySummaryAPIView` | None | Summary of monitored computing units. |
| `GET /api/labs/equipment/{equipment_id}/activity` | `ComputingActivityAPIView` | Path `{equipment_id}` | Live activity of a computing unit, read-only (404 for other units). Agents write it through `PATCH /agent/equipment/activity` (agents app, signed request). |
