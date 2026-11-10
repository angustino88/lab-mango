# Design: Equipment booking

- Tier: T2 · Status: Draft, owner decisions recorded below, not approved for implementation · Date: 2026-11-10
- Domain: Labs (`core/labs/features/equipment_bookings`, a feature that does not exist yet)
- Depends on: [equipment management redesign](equipment-management-redesign.md), which owns the
  definitions of equipment state, `EquipmentPlacement`, `EquipmentLoan`, and "available". This document
  does not repeat them.

This revision replaces the earlier draft, which set the equipment status to `BORROWED` with JSON metadata.
The central rule now is: **a booking is a calendar entry; a loan is physical custody.** The booking
feature never writes equipment state directly.

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
| Not collected within the grace period | task | `expired` | nothing changes |
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
| Not in service (planned, retired, lost) | blocked | blocked | cancelled with notice |
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

- First version is coordinator-operated (operating model 1 of the earlier draft; **owner to confirm**).
  Engineers see only their own bookings. The existing `approval_status` fields allow adding an
  engineer-request flow later without a schema change.
- Object scope follows equipment scope (department or lab-wide), an open question in the redesign.
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

1. Confirm the first version is coordinator-operated, with engineer requests added later.
2. Grace period before an uncollected reservation expires (15 minutes, matching bench bookings?).
3. How close a booking must be to an overdue loan before its requester is warned (suggested: 24 hours).
4. Whether any booking length requires approval, or all coordinator-entered bookings are approved on creation.
5. Whether bookings may be built before the equipment state split, accepting the temporary bridge.
