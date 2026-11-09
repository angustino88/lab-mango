# Design: Equipment Booking & Equipment Lifecycle Architecture

- **Tier:** T2 · **Status:** Draft / Investigation Complete · **Date:** 2026-10-25
- **Domain:** Labs (`core/labs/features/equipment_bookings`)
- **Related Features:** `equipment`, `bench_bookings`, `users`

---

## 1. Executive Summary & Problem Statement

This document details the architectural investigation and design for the **Equipment Booking** feature in Lab Mango, focusing specifically on:
1. The interaction and invariants between **Equipment Booking Schedule** and **Equipment Operational Lifecycle Status**.
2. An evaluation of the **`BORROWED`** operational status, its metadata requirements, and whether a new status is needed.
3. The real-world **physical custody problem** (avoiding "phantom availability" caused by automated completion).
4. The **authorization and persona boundary**: how booking operates when regular engineers do not directly manage or view individual equipment devices, and only Lab Coordinators hold inventory permissions.

---

## 2. Current State (Repository Evidence)

### 2.1 Concrete Persistence Models
* **`labs.EquipmentBooking`** (`core/labs/models/booking/equipment_booking.py`):
  * Inherits from abstract `Booking` (`booking_code`, `starts_at`, `ends_at`, `status`, `approval_status`, `project`, `approved_by`, `reason`, `cancellation_reason`).
  * Foreign key: `equipment = ForeignKey("labs.Equipment", related_name="bookings", on_delete=models.PROTECT)`.
  * Indexes:
    * `equipment_booking_schedule_idx`: `(equipment, starts_at, ends_at)`.
    * `equipment_booking_state_idx`: `(equipment, status, approval_status)`.
  * Check Constraint: `ends_at > starts_at`.
* **`labs.EquipmentStatusRecord`** (`core/labs/models/resource/equipment/equipment.py`):
  * Append-only status log with `equipment`, `status`, `metadata: JSONField`, `creator`, `created`.
  * Indexed by `(equipment, -created, -id)` for deterministic tiebreakers.
* **`labs.EquipmentAssignment`** (`core/labs/models/resource/equipment/assignment.py`):
  * Links equipment to a `Bench`.
  * DB Constraint: `one_active_bench_per_equipment` (`UniqueConstraint(equipment, condition=unassigned_at IS NULL)`).

### 2.2 Operational Status Persistence & Validation
* **`_status_transition.py`** (`core/labs/features/equipment/application/_status_transition.py`):
  * `record_equipment_status(equipment, status, details, actor)`:
    * Validates status against `EquipmentStatus.values`.
    * If `status == IN_USE`: requires `bench_id`, manages `EquipmentAssignment`.
    * If `status != IN_USE`: closes any open `EquipmentAssignment` (`unassigned_at = now()`).
    * Appends `EquipmentStatusRecord` with metadata.
* **`BorrowedStatusDetailsSerializer`** (`core/labs/features/equipment/api/serializers.py`):
  * Requires explicit metadata fields: `borrower`, `borrow_date`, `expected_return_date`, `purpose`, `condition`, `responsible_person`, `notes`.

### 2.3 User Permissions & Roles
* **`IsLabCoordinator`** (`core/users/access.py` / `core/users/features/groups/docs/spec.md`):
  * Role hierarchy: `Admin` > `Coordinator` > `User`.
  * Specifically designated for: *"Equipment lifecycle management, booking approvals, status changes."*
  * Regular engineers/lab members do not have write access to equipment inventory or status transitions.

---

## 3. Relationship: Equipment Lifecycle vs. Booking Workflow

In Lab Mango, **Resource Lifecycle Status**, **Booking Workflow**, and **Bench Assignment** are three orthogonal, decoupled state tracks:

```
┌────────────────────────────────────────────────────────────────────────┐
│ TRACK 1: Equipment Lifecycle / Operational Status                      │
│ (Owner: core/labs/features/equipment, Model: EquipmentStatusRecord)    │
│ Values: available | in_use | in_storage | transferred | borrowed |     │
│         maintenance | broken | lost | on_order                         │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Validates eligibility at booking time
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ TRACK 2: Equipment Booking Schedule State Machine                      │
│ (Owner: Equipment Bookings, Model: EquipmentBooking -> Booking)        │
│ Values: reserved ──> in_progress ──> completed                         │
│             │              │                                           │
│             └──> cancelled └──> cancelled                              │
│             │                                                          │
│             └──> expired                                               │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Evaluation of the 9 Operational Statuses

| Status | Operational Meaning | Standalone Equipment Booking Behavior |
|---|---|---|
| **`AVAILABLE`** | On the shelf, operational, unassigned. | **Primary bookable status.** Eligible for reservations. |
| **`BORROWED`** | Checked out by a user (active booking or manual loan). | **Active booking state.** Non-bookable. Reverts to `AVAILABLE` on check-out/return. |
| **`IN_USE`** | Mounted to a `Bench` via `EquipmentAssignment`. | **Ineligible for standalone booking.** Reserved via `BenchBooking`. |
| **`IN_STORAGE`** | In warehouse/cabinet. | **Non-bookable.** Must be moved to `AVAILABLE` before booking. |
| **`MAINTENANCE`** | In calibration or repair. | **Non-bookable.** Any overlapping reservations are blocked. |
| **`BROKEN`** | Inoperative / hardware failure. | **Non-bookable.** Future reservations cancelled with notice. |
| **`LOST`** | Missing physical asset. | **Non-bookable.** Future reservations cancelled. |
| **`TRANSFERRED`** | Relocated to another site. | **Non-bookable.** |
| **`ON_ORDER`** | Procured, not yet delivered. | **Non-bookable.** |

### 3.2 Invariants Across Domains
1. **Unassigned Only:** Only equipment with **no active bench assignment** (`unassigned_at IS NOT NULL` or never assigned) is eligible for standalone `EquipmentBooking`. Bench-attached equipment is reserved as part of the workspace through `BenchBooking`.
2. **Deny-by-Default Terminal States:** Once a booking enters `completed`, `cancelled`, or `expired`, it can never transition back to an active state (`BOOKING_STATUS_TRANSITIONS` in `core/labs/models/booking/base.py`).
3. **Half-Open Interval Overlap Rule:** A reservation conflicts with an existing booking if:
   $$\text{existing.starts\_at} < \text{requested.ends\_at} \quad\land\quad \text{existing.ends\_at} > \text{requested.starts\_at}$$
   where existing booking is in an active reserving state (`is_reserving = status IN ('reserved', 'in_progress') AND approval_status IN ('pending', 'approved')`).

---

## 4. Evaluation of the `BORROWED` Status

### 4.1 Do We Need a New Status (e.g., `BOOKED`)?
**No. We should use `EquipmentStatus.BORROWED` directly.**

* **Domain Semantics:** When a portable device (oscilloscope, multimeter, camera) is handed to an engineer for an active booking, the physical reality is that the item is **borrowed** and off the shelf. "Booked" refers to a calendar reservation (which may be for next week), not physical custody today.
* **Database Stability:** `EquipmentStatus.BORROWED` is already a fully migrated PostgreSQL enum choice (`core/labs/migrations/0001_initial.py`). Adding a new status requires database schema migrations.
* **API & Serialization Parity:** `BorrowedStatusDetailsSerializer` is already implemented and tested in `core/labs/features/equipment/api/serializers.py`.
* **Analytics Compatibility:** Analytics modules (`core/labs/features/analytics/queries/utilization.py`) already count `BORROWED` as in-circulation equipment.

### 4.2 Metadata Construction on Check-In
When an equipment booking is checked in (activated), the command supplies all required fields to `record_equipment_status`:

```python
details = {
    "source": "booking",
    "booking_id": booking.pk,
    "booking_code": booking.booking_code,
    "borrower": booking.creator.get_full_name() or booking.creator.username,
    "responsible_person": actor.get_full_name() or actor.username,
    "borrow_date": timezone.now().date().isoformat(),
    "expected_return_date": booking.ends_at.date().isoformat(),
    "purpose": booking.reason or (f"Project: {booking.project.name}" if booking.project else "Equipment Booking"),
    "condition": command_input.condition or "Good",
    "notes": f"Checked out via booking {booking.booking_code}. {command_input.notes or ''}".strip(),
}
```

### 4.3 Coexistence of Manual Loans and Automated Bookings
Manual status changes and automated booking check-ins can safely coexist:
1. **Provenance Tracking:** `EquipmentStatusRecord.metadata["source"]` distinguishes `"manual"` vs. `"booking"`.
2. **Safe Reversion Guard:** On booking completion, before moving the equipment back to `AVAILABLE`, the system verifies that the current status record was generated by that specific booking (`metadata.booking_id == booking.id`). If an operator manually set the item to `MAINTENANCE` or `BROKEN` during the booking, the booking system **will not** overwrite the operator's decision.

---

## 5. Physical Custody & The Role of the Lab Coordinator

### 5.1 The Phantom Availability Risk
Unlike a bench (which is fixed/virtual and can automatically terminate sessions when time expires), equipment is **physical hardware**:
* If Celery automatically completes an `in_progress` booking when `ends_at` passes and sets equipment back to `AVAILABLE`, but the engineer hasn't physically brought the device back, the system creates **phantom availability**.
* A second engineer will see the item as `AVAILABLE`, attempt to reserve or retrieve it, and find an empty shelf.

### 5.2 Automation Rules for Equipment
* **Auto-Expire (Unclaimed Reservations): YES.** If an engineer does not pick up the equipment within a grace period (e.g. 15 minutes after `starts_at`), the reservation moves to `EXPIRED`. Because the device was never handed out, it remained `AVAILABLE` on the shelf. The calendar window is freed.
* **Auto-Complete (Scheduled End Reached): NO.** When `ends_at` arrives, the booking moves to an **Overdue** sub-state (still `status=in_progress`, but flagged `is_overdue=True`). The equipment **remains `BORROWED`** until a human coordinator confirms physical return.
* **Overdue Reminders: YES.** Celery periodic tasks email the borrower and coordinator when a device is overdue.

---

## 6. Three Operating Models (For Product Owner Confirmation)

Because regular engineers do not have permission to view individual equipment inventory directly, the equipment booking feature can be deployed under one of three operating models:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ MODEL 1: Coordinator-Only Planning & Allocation Tool                                   │
│                                                                                        │
│ • Audience: Lab Coordinators and Lab Admins only.                                      │
│ • Flow: Coordinators enter bookings on behalf of project teams to reserve critical     │
│   hardware in advance and prevent scheduling collisions across projects.               │
│ • Custody: Coordinator clicks "Issue" (check-in) and "Return" (check-out).             │
└────────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────────────────┐
│ MODEL 2: Engineer Request ──> Coordinator Allocation & Approval Flow                   │
│                                                                                        │
│ • Audience: Engineers request category/project needs; Coordinators approve & allocate. │
│ • Flow:                                                                                │
│   1. Engineer requests: "Need 1x Oscilloscope for Project X from 10:00 to 14:00".       │
│   2. Coordinator reviews request, selects specific device SKU (e.g. EQ-OSC-02), and    │
│      approves the booking.                                                             │
│   3. Coordinator hands over physical device at counter and activates check-in.         │
│   4. Coordinator receives returned device, inspects condition, and checks out.         │
└────────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────────────────┐
│ MODEL 3: Status-Only Management (No New Booking Feature Needed)                        │
│                                                                                        │
│ • If the lab only does immediate counter checkout without advance scheduling:          │
│ • The existing POST /api/labs/equipment/{id}/actions/change-status with status="borrowed"│
│   and BorrowedStatusDetailsSerializer already satisfies this completely.              │
│ • No equipment booking feature or booking codes are required.                          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Technical Architecture & Specification (For Models 1 & 2)

### 7.1 Package Layout
Following the project's strict layering rules ([feature template](../architecture/feature-template.md)):

```text
core/labs/features/equipment_bookings/
├── __init__.py
├── urls.py
├── contracts.py
├── exceptions.py
├── public.py
├── tasks.py
├── api/
│   ├── __init__.py
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
├── application/
│   ├── __init__.py
│   ├── locks.py                  # select_for_update() row lock on Equipment
│   ├── policies.py               # Pure duration, grace period, and status checks
│   ├── booking_codes.py          # Opaque SHA-256 unique code generation
│   ├── create_booking.py         # Atomic creation command
│   ├── update_booking.py         # Atomic reschedule / update command
│   └── state_transitions.py      # Check-in, check-out, cancel, and reconciliation
├── queries/
│   ├── __init__.py
│   └── equipment_bookings.py     # Filtered list, detail, code lookup, overlap checks, options
└── tests/
    ├── api/
    ├── application/
    └── queries/
```

### 7.2 Concurrency & Race Protection
* **Pessimistic Locking:** `lock_equipment((equipment_id,))` issues `Equipment.objects.select_for_update().filter(id=equipment_id)`.
* **Atomic Boundary:** All booking creations and status transitions execute within an atomic transaction:
  ```python
  with transaction.atomic():
      equipment = lock_equipment(data.equipment_id)
      policies.ensure_equipment_accepts_bookings(equipment)
      conflicts = conflicting_equipment_bookings(
          equipment_id=data.equipment_id,
          starts_at=data.starts_at,
          ends_at=data.ends_at,
      )
      policies.ensure_no_conflicting_bookings(has_conflicts=conflicts.exists())
      ...
  ```

### 7.3 API Transport Contracts

| Method & Path | View Class | Permission | Purpose |
|---|---|---|---|
| `GET /api/labs/equipment-bookings` | `EquipmentBookingListCreateAPIView` | `IsAuthenticated` | Filtered list by equipment, user, project, status. |
| `POST /api/labs/equipment-bookings` | `EquipmentBookingListCreateAPIView` | `IsAuthenticated` / `IsLabCoordinator` | Create booking under row-level lock. |
| `GET /api/labs/equipment-bookings/{id}` | `EquipmentBookingDetailAPIView` | `IsAuthenticated` | Retrieve booking details. |
| `PATCH /api/labs/equipment-bookings/{id}` | `EquipmentBookingDetailAPIView` | `IsAuthenticated` | Reschedule booking window or update reason. |
| `POST /api/labs/equipment-bookings/{id}/actions/cancel` | `EquipmentBookingCancelActionAPIView` | `IsAuthenticated` | Cancel booking (`reserved`/`in_progress` $\to$ `cancelled`). |
| `POST /api/labs/equipment-bookings/{id}/actions/checkin` | `EquipmentBookingCheckinActionAPIView` | `IsLabCoordinator` | Issue hardware (`reserved` $\to$ `in_progress`, equipment $\to$ `BORROWED`). |
| `POST /api/labs/equipment-bookings/{id}/actions/checkout` | `EquipmentBookingCheckoutActionAPIView` | `IsLabCoordinator` | Return hardware (`in_progress` $\to$ `completed`, equipment $\to$ `AVAILABLE`). |
| `GET /api/labs/equipment-bookings/code/{booking_code}` | `EquipmentBookingCodeDetailAPIView` | `IsAuthenticated` | Public booking code lookup for kiosk/counter scan. |
| `GET /api/labs/equipment-bookings/options` | `EquipmentBookingOptionsAPIView` | `IsAuthenticated` | Flat `{id, sku, name}` selector standard ([ADR 002](../architecture/decisions/002-catalog-and-selector-api.md)). |
| `GET /api/labs/equipment-bookings/summary` | `EquipmentBookingSummaryAPIView` | `IsAuthenticated` | Status aggregate counts (`reserved`, `in_progress`, etc.). |

---

## 8. Summary of Open Decisions for the Owner

1. **Select Operating Model:** Does the lab intend to use **Model 1** (Coordinator-only advance scheduling), **Model 2** (User request $\to$ Coordinator approval), or **Model 3** (Status-only loans via existing `change-status` without bookings)?
2. **Grace Period for Unclaimed Reservations:** Confirm if the auto-expire threshold should be 15 minutes after `starts_at` (matching bench bookings).
3. **Approval Threshold:** Confirm if bookings exceeding 4 hours require coordinator approval (`approval_status=PENDING`).
