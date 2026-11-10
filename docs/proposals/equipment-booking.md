# Design: Equipment booking

- Tier: T2 · Status: Draft, revision 2 below awaits owner approval; not approved for implementation · Date: 2026-11-10
- Domain: Labs (`core/labs/features/equipment_bookings`, a feature that does not exist yet)
- Depends on: [equipment management redesign](equipment-management-redesign.md), which owns the
  definitions of equipment state, `EquipmentPlacement`, `EquipmentLoan`, and "available". This document
  does not repeat them.

This revision replaces the earlier draft, which set the equipment status to `BORROWED` with JSON metadata.
The central rule now is: **a booking is a calendar entry; a loan is physical custody.** The booking
feature never writes equipment state directly.

## Revision 2 (2026-11-10): coordinator-only operation, borrowers without accounts, several items at once

This section replaces the parts of the document below that it contradicts (operating model, permissions,
routes, `requester` semantics). Equipment redesign steps 1 to 3 are implemented; `EquipmentLoan`,
hand-over, return, and extend exist for one item at a time.

### Owner answers recorded (2026-11-10)

| # | Answer | Consequence |
|---|---|---|
| R1 | Engineers cannot see or read equipment. The coordinator records everything on their behalf (old flow: coordinator set status `borrowed` and named the borrower). | No engineer request or approval flow. Every route here is coordinator-only. Bookings are created `approved`. |
| R2 | Not every borrower has a user account. | Borrower is a user **or** a name: `borrower` (FK, optional) and `borrower_name` (text), at least one; optional `borrower_contact` (email or phone, text). |
| R3 | Record the purpose of a loan. | `purpose` text on the loan batch. |
| R4 | Restrict equipment reads to coordinators and administrators (explicit authorization for this access-control change). | See "Read restriction". |
| R5 | People sometimes borrow a list of devices at once. | One request hands over, reserves, or returns several items; see "Loan batch". |

### Loan batch (one borrower, one or more items)

New `EquipmentLoanBatch` (owned by the equipment feature) is the paper slip: who, why, until when.
Loans and reservations are its lines.

| Model | Fields |
|---|---|
| `EquipmentLoanBatch` | `borrower` (FK user, nullable), `borrower_name`, `borrower_contact`, `purpose`, `created_by`, timestamps. Check `equipment_loan_batch_has_borrower`: `borrower` set or `borrower_name` not blank. No code (OD1). |
| `EquipmentLoan` (existing) | gains `batch` (FK, PROTECT, required). `borrower` moves to the batch; the loan keeps item facts: times, `due_at`, `condition_out`/`condition_in`, `close_reason`. |
| `EquipmentBooking` (existing) | gains `batch` (FK, PROTECT, required for new rows). `requester` stays null for borrowers without an account. |

A single-item hand-over is a batch with one line; the step 3 routes stay and create one implicitly.

### Flows

**Lend now (the old "set borrowed")**: `POST /api/labs/equipment-loans`

```json
{"equipment_ids": [12, 15, 31], "borrower_id": null, "borrower_name": "Anna Tran (Supplier X)",
 "borrower_contact": "anna@example.com", "purpose": "EMC test week", "due_at": "2026-11-17T17:00:00+07:00",
 "items": [{"equipment_id": 15, "condition_out": "Scratched lid"}]}
```

All or nothing: every item must be available (in service, operational, not on a bench, not on loan,
calibration not overdue, no reservation by someone else overlapping now to `due_at`). If any is not, nothing
is handed over and the response is 409 `equipment_not_available` with one entry per failing item and its
reasons. Maximum 50 items per request.

**Reserve for later**: `POST /api/labs/equipment-reservations`

Same body with `starts_at` and `ends_at` instead of `due_at`. Creates one `EquipmentBooking` per item
(`reserved`, `approved`) under one batch. PostgreSQL refuses a time overlap per item
(`equipment_booking_no_overlap`); the response is 409 `booking_conflict` listing the items and the
conflicting windows; nothing is reserved. A reservation shows on the item (`reservations` in the detail
response) and blocks lending it to someone else across that window.

| Reservation step | Route | Effect |
|---|---|---|
| Change window or items | `PATCH /equipment-reservations/{batch_id}` | reschedule, add or drop items while `reserved` |
| Cancel | `POST .../{batch_id}/actions/cancel` (reason) | all or selected items `cancelled` |
| Hand over | `POST .../{batch_id}/actions/hand-over` (optional `equipment_ids`, per-item `condition_out`) | bookings `in_progress`, loans open with `due_at = ends_at`; items not collected stay `reserved` |
| Not collected | task | `expired` after the grace period (open question 1) |

**Return**: `POST /api/labs/equipment-loans/actions/return`

```json
{"items": [{"equipment_id": 12, "condition_in": "ok", "room_id": 5},
           {"equipment_id": 15, "condition_in": "Cracked screen", "condition": "out_of_service", "room_id": 5}]}
```

Partial returns are normal: return 2 of 3 now, the third later. Each returned line closes its loan and
completes its booking; the batch is finished when no line is open. Items that are not on loan make the whole
request fail with 409 and a per-item list.

**Extend**: `POST /api/labs/equipment-loans/actions/extend` (`equipment_ids` or `batch_id`, `due_at`);
booking-linked loans move the booking end too, refused on overlap with the next reservation.

**Read**: `GET /api/labs/equipment-loans` (filters: `open`, `overdue`, `borrower_id`, `borrower_name`,
`equipment`, `batch`), `GET /api/labs/equipment-loan-batches/{id}` (the slip with all its lines),
`GET /api/labs/equipment-reservations` (calendar; filters by window and item).

### Write safety

| Write path | Race | Guard (constraint name / lock order) | Idempotency | Concurrency test |
|---|---|---|---|---|
| lend now (batch) | two batches sharing an item | lock all `Equipment` rows in one query ordered by pk; `one_active_loan_per_equipment`; reservation check under the locks | `Idempotency-Key` required (request standard RW-6) | two batches sharing one item: one 201, one 409, no partial loans |
| reserve (batch) | overlapping windows | same ordered lock; `equipment_booking_no_overlap` | `Idempotency-Key` required | two reservations sharing an item and window: one wins |
| hand over reservation | double hand-over; cancel racing hand-over | lock `Equipment` rows, then batch, then bookings; transition table | lines already `in_progress` are returned as they are | cancel and hand-over at once |
| return (batch) | double return | lock `Equipment` rows, then loans | already returned lines are returned as they are | repeat call is a no-op |
| expire uncollected (task) | task racing hand-over | `status = reserved` and grace passed; `skip locked` | re-run finds nothing | task racing hand-over |

Lock order: `Equipment` rows by pk, then `EquipmentLoanBatch`, then booking rows, then loan rows.

### Read restriction (R4)

**Evidence:** every equipment route uses `HasAPIKey | IsLabCoordinator`, whose reads are open to any
authenticated user (`core/users/access.py`).

**Proposed:** a `IsLabCoordinatorOnly` permission (read and write need the coordinator role or admin) on:
equipment lists, details, filters, facets, options, summaries, placement, loan, reservation, and category
routes, and the equipment catalog (kinds, types, manufacturers, product models). API keys keep access
(agents). **Kept open to authenticated users:** `departments` and `resource-groups` routes (served from
the equipment feature but used by other screens) and the computing activity routes used by the dashboard.

Not verified: which frontend screens used by engineers call equipment routes (the frontend is not in this
repository). Bench dashboards read equipment through backend queries, not these routes, so they keep working.

### Reminders

Borrowers may have no account, so reminders go to the **coordinator** (in-app list `overdue=true`). When
`borrower_contact` is an email address, or the borrower is a user, an email reminder is sent at the due
time, one day later, then daily for a week (OD4), deduplicated per loan and slot. Email delivery depends on
the existing notification delivery; if none is configured for email, only the list exists (to verify).

### Phasing

1. Read restriction (R4) and `purpose`, borrower name and contact, `EquipmentLoanBatch`, lend-now and return for several items. **Implemented.**
2. Reservations for several items, hand-over from a reservation, expiry task.
3. Overdue reminders.

### Owner decisions on the open questions (2026-11-10, "use your suggestions")

| # | Decision |
|---|---|
| R6 | An uncollected reservation expires at the end of its start day (replaces the 15 minutes of OD5). |
| R7 | OD3 is dropped: an item on loan today may be reserved for a later window; only overlapping windows are refused. |
| R8 | One batch may mix items of different departments (until department scope exists). |
| R9 | `departments` and `resource-groups` stay readable by all authenticated users. |
| R10 | Build phase 1 is approved to start. Placement rule to verify by test: an item can be lent from a room, a station, a noted place, or with no place recorded; never while on a bench. |

## Problem and acceptance criteria

Engineers need portable equipment (oscilloscopes, cameras, debuggers) for a period. The lab needs to
prevent double allocation, know who holds each unit, and never show a unit as free while it is still in
someone's hands.

| # | Criterion |
|---|---|
| AC1 | A unit cannot have two reserving bookings that overlap in time. |
| AC2 | A booking can be created only when the unit is available at that moment (owner decision). |
| AC3 | Handing over a unit opens exactly one loan and closes its current placement. |
| AC4 | A booking never completes automatically; only a recorded return completes it. |
| AC5 | An uncollected reservation expires after a grace period and frees the calendar. |
| AC6 | Overdue loans trigger reminders at the due time, one day later, then daily, capped at one week. |
| AC7 | Marking a unit lost is a manual coordinator action; it closes the loan and cancels future bookings. |
| AC8 | A walk-up loan uses the same path: a booking that starts now with immediate hand-over. |

## Owner decisions recorded (2026-11-10)

| # | Decision |
|---|---|
| OD1 | No booking code or other code on the loan; nothing in the system reads one. |
| OD2 | Lost is manual only. |
| OD3 | Create is allowed only when the equipment is available. |
| OD4 | Reminder cadence as in AC6. |
| OD5 | An uncollected reservation expires 15 minutes after its start, matching bench bookings. |
| OD6 | Coordinators are scoped per department: a booking is handled by a coordinator of the unit's department. |
| OD7 | The first version is coordinator-operated. Engineer requests may be added later. |

Consequence of OD3, accepted unless the owner says otherwise: a unit that is on loan today cannot be
booked for next week, even if it is due back tomorrow.

## Current state (from repository evidence)

- `labs.EquipmentBooking` exists (`core/labs/models/booking/equipment_booking.py`). It inherits the
  abstract `Booking` (`booking_code`, `starts_at`, `ends_at`, `status`, `approval_status`, `project`,
  `requester`, approval and cancellation fields) and carries the exclusion constraint
  `equipment_booking_no_overlap` over reserving bookings, plus schedule and state indexes.
- `BOOKING_STATUS_TRANSITIONS` (`core/labs/models/booking/base.py`) defines
  `reserved → in_progress | cancelled | expired` and `in_progress → completed | cancelled`.
- `BookingNotification` (`core/labs/models/booking_notification.py`) already has an `equipment_booking`
  foreign key and a unique `dedupe_key`.
- No feature package, routes, commands, or tasks for equipment booking exist. `bookable` is advertised
  for every category (`core/labs/features/equipment/api/capabilities.py`).
- Roles: `IsLabCoordinator` is used by bench booking approval and by computing activity writes.

## Proposed behavior and invariants

### Flow

| Step | Who | Booking | Equipment side (through equipment `public.py`) |
|---|---|---|---|
| Create | coordinator | `reserved` | nothing changes |
| Not collected within 15 minutes of the start | task | `expired` | nothing changes |
| Cancel | coordinator | `cancelled` (reason required) | nothing changes if not handed over |
| Hand over | coordinator | `in_progress` | `hand_over_equipment`: loan opens, current placement closes |
| End time passes, not returned | none | stays `in_progress`; shown as overdue | loan stays open; reminders |
| Extend | coordinator | `ends_at` moves | loan `due_at` moves in the same transaction |
| Return | coordinator | `completed` | `return_equipment`: loan closes with condition; coordinator records the new placement |
| Marked lost | coordinator, on the equipment | `cancelled` with reason | loan closes with reason `lost`; future bookings cancelled with notice |

Overdue is computed (`status = in_progress` and `ends_at < now`), not a stored state.

The actions are named `hand-over` and `return`. The earlier draft called them "checkin" and "checkout",
which is the reverse of common usage.

### How equipment state gates booking

"Available" is defined in the redesign document: in service, operational, not placed on a bench, no
active loan, and calibration not overdue where required.

| Equipment state | Create | Hand over | Existing future bookings |
|---|---|---|---|
| Category not bookable | blocked | n/a | n/a |
| Not in service (planned, transferred out, retired, lost) | blocked | blocked | cancelled with notice |
| In maintenance or out of service | blocked | blocked | flagged for the coordinator |
| Calibration overdue (when required) | blocked | blocked | flagged for the coordinator |
| Placed on a bench | blocked (reserved through the bench booking) | n/a | n/a |
| On loan, including overdue | blocked | blocked by the one-active-loan rule | flagged when the next booking is near |
| Available | allowed, subject to the overlap rule | allowed | n/a |

Related rule on the equipment side: placing a unit on a bench is refused while it has reserving future bookings.

### Invariants

1. Overlap: `equipment_booking_no_overlap` (existing exclusion constraint, half-open interval).
2. Terminal booking states never revive (existing transition table).
3. At most one active loan per unit (`one_active_loan_per_equipment`, defined in the redesign).
4. A booking in `in_progress` has exactly one loan; a loan linked to a booking is closed before the booking completes.
5. The booking feature changes equipment only through equipment's public commands.

## Module ownership and allowed dependencies

```text
core/labs/features/equipment_bookings/
├── public.py, contracts.py, exceptions.py, urls.py, tasks.py
├── api/            views, serializers, urls
├── application/    create_booking, update_booking, cancel_booking,
│                   hand_over, return_booking, expire_uncollected, policies
├── queries/        equipment_bookings (list, detail, overdue, affected-by-state-change)
└── tests/
```

Allowed imports: `equipment.public` and `equipment.contracts` (availability, custody commands, lock
helper), `users` public, `core.common`. Not allowed: equipment models for behaviour, `bench_bookings`
internals. Shared booking code that both booking features need (code generation, notification delivery)
is extracted to a common Labs module, not imported across features.

## API contract (endpoints, errors, breaking?)

New routes only; nothing existing changes. Shapes follow `docs/api/response-standard.md`.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/labs/equipment-bookings` | coordinator; requester sees own | list, filter by equipment, requester, project, status, `overdue` |
| `POST /api/labs/equipment-bookings` | coordinator | create; `hand_over_now=true` for a walk-up loan |
| `GET /api/labs/equipment-bookings/{id}` | coordinator; requester for own | detail including loan |
| `PATCH /api/labs/equipment-bookings/{id}` | coordinator | reschedule while `reserved`; extend while `in_progress` |
| `POST .../{id}/actions/cancel` | coordinator | cancel with reason |
| `POST .../{id}/actions/hand-over` | coordinator | open loan; body: `condition_out`, notes |
| `POST .../{id}/actions/return` | coordinator | close loan; body: `condition_in`, new placement, optional condition change |
| `GET /api/labs/equipment-bookings/summary` | coordinator | counts by status and overdue |

Dropped from the earlier draft: `GET /equipment-bookings/code/{booking_code}` (OD1; no kiosk or agent
reads it). `booking_code` is still generated, because the shared `Booking` base requires it, and is used
only as a human reference in notifications.

Errors: `equipment_not_available` (409), `booking_conflict` (409), `invalid_state_transition` (409),
`equipment_on_loan` (409), validation (422), not found (404), permission denied (403).

## Data model, constraints, concurrency

No change to `EquipmentBooking` columns. `EquipmentLoan` is defined in the redesign document and owned by
the equipment feature.

| Write path | Race | Guard (constraint name / lock order) | Idempotency (key or natural target state) | Concurrency test |
|---|---|---|---|---|
| create | two bookings for one window; availability changes during the check | lock `Equipment` first, check availability under the lock; `equipment_booking_no_overlap` | client idempotency key per request standard, or none for a first version (state which) | two simultaneous creates for one window: one 201, one 409 |
| reschedule / extend | overlap with a later booking | lock `Equipment`, then booking row; exclusion constraint; loan `due_at` updated in the same transaction | same window is a no-op | extend into a neighbouring booking is refused |
| hand over | double hand-over; hand-over while another loan is open | lock `Equipment`, then booking; `one_active_loan_per_equipment`; transition table | already `in_progress` with its loan returns it | two bookings handed over at once: one wins |
| return | double return | lock `Equipment`, then booking, then loan | already `completed` returns it | repeat call is a no-op |
| cancel | cancel racing hand-over | lock `Equipment`, then booking; transition table | already `cancelled` returns it | cancel and hand-over at once |
| expire uncollected (task) | task racing hand-over | filter `status = reserved` and start plus grace passed; lock rows `skip locked`; transition table | re-run finds nothing | task racing hand-over leaves one consistent state |
| lost (equipment command) | lost racing return | lock `Equipment`; closes loan and cancels bookings in one transaction | already lost is a no-op | lost and return at once |

Known gap, closed by OD3: the exclusion constraint covers only scheduled windows, so the database alone
would allow a booking right after an overdue one. The create command refuses any unit with an active
loan, under the equipment row lock.

## Read paths and query budget

| Endpoint | Query function | `select_related` / `prefetch_related` / annotations | Budget (N queries) | Page cap |
|---|---|---|---|---|
| list | `list_equipment_bookings` | equipment, requester, project, loan | 2 (page + count) | 100 |
| detail | `get_equipment_booking` | same | 1 | n/a |
| summary | `equipment_booking_summary` | one aggregate | 1 | n/a |
| overdue sweep (task) | `overdue_loans` | keyset by id | 1 per batch | 100 per batch |

## Authorization and threat notes

- First version is coordinator-operated (OD7; operating model 1 of the earlier draft).
  Engineers see only their own bookings. The existing `approval_status` fields allow adding an
  engineer-request flow later without a schema change.
- Object scope follows equipment scope: the unit's department (OD6). Until the coordinator-to-department
  assignment exists (see the redesign), the global coordinator role applies.
- `requester` is who the booking is for; `creator` is the coordinator who entered it. Reminders go to the requester.
- Free-text fields (`reason`, conditions, notes) are length-capped and treated as untrusted on output.

## Async/integration behavior

- Celery tasks, scheduled by an operator in Django Celery Beat as the computing offline sweep is today:
  expire uncollected reservations; overdue reminders; warn the coordinator and the next requester when
  an overdue unit has a booking starting soon.
- Reminders are written to `BookingNotification` with a `dedupe_key` derived from booking id and reminder
  slot (due, +1 day, +2 … +7), so a re-run cannot send twice. After the cap, the loan stays on the
  coordinator's overdue list; nothing escalates automatically.
- Notifications are created in the same transaction as the state change and delivered after commit.

## Migration, rollout, rollback

- Prerequisites, in order: placement, equipment state split, `EquipmentLoan` (redesign steps 1 to 3).
- If bookings are wanted before the state split, hand-over can also set legacy status `borrowed` and
  return can set `available` as a temporary bridge. That bridge is removed when the split lands; this
  costs throwaway code and is not the recommended order.
- The feature adds routes and tasks only. Rollback is removing the routes and disabling the tasks; open
  loans would then be closed by hand.

## Observability

Log booking id, equipment id, actor id, action, and outcome for every command and task run. Counters:
bookings created, expired, overdue loans, reminders sent, reminder delivery failures.

## Test plan (criterion → test)

| Criterion | Test |
|---|---|
| AC1 | overlapping create returns 409 from the constraint, including under concurrency |
| AC2 | create matrix over each row of the gating table |
| AC3 | hand-over opens one loan, closes the placement; second hand-over is refused |
| AC4 | no task moves `in_progress` to `completed` |
| AC5 | reservation past the grace period expires; one handed over in time does not |
| AC6 | reminder slots produce one notification each across repeated task runs; none after the cap |
| AC7 | lost closes the loan with reason `lost` and cancels future bookings; no task sets lost |
| AC8 | `hand_over_now` creates the booking and loan in one transaction |
| permissions | denied-access tests per endpoint; requester sees only own bookings |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Set equipment status `BORROWED` with JSON metadata and compare `metadata.booking_id` before reverting (earlier draft) | custody as free text; fragile guard; cannot express "broken while on loan" |
| Auto-complete at the end time | shows a unit as free while it is still out |
| Status-only loans with no booking | no advance scheduling; a second path beside bookings |
| Allow booking a unit that is on loan if windows do not overlap | rejected by OD3; simpler to reason about, at the cost of no back-to-back advance booking |
| Auto-mark lost after N days overdue | rejected by OD2 |

## Open questions / decisions needed from the owner

1. How close a booking must be to an overdue loan before its requester is warned (suggested: 24 hours).
2. Whether any booking length requires approval, or all coordinator-entered bookings are approved on creation.
3. Whether bookings may be built before the equipment state split, accepting the temporary bridge.
