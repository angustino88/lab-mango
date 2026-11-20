# Feature specification: Downtime (`core/labs/features/downtime`)

Design and owner decisions: [resource status and downtime](../../../../../docs/proposals/resource-status-and-downtime.md),
[lab staff booking access](../../../../../docs/proposals/downtime-lab-staff-booking-access.md).
Frontend: [resource status frontend guide](../../../../../docs/api/resource-status-frontend-guide.md).

## Purpose

Records when a room, station, bench or equipment unit cannot be used, planned ahead or when it happens. A
resource's condition (`operational`, `in_maintenance`, `out_of_service`) is computed from these windows and
never stored. Problems pass down the hierarchy: a room window makes every station and bench in it unavailable.

## Model

`ResourceDowntime` (`core/labs/models/resource/base/downtime.py`), generic link to the root resource model.

| Field | Meaning |
|---|---|
| `condition` | `in_maintenance` or `out_of_service` during the window |
| `kind` | `planned` (default when it starts later) or `unplanned` |
| `reason` | `maintenance`, `fault`, `calibration`, `safety_hold`, `renovation`, `other` |
| `booking_access` | `closed` (default: no one books the covered benches) or `lab_staff` (coordinators and administrators still can) |
| `starts_at`, `ends_at` | Half-open period; `ends_at` empty while the end is unknown |
| `cancelled_at`, `ended_by`, `notes` | Cancellation of a window that never started; who ended it |

Constraints: `downtime_ends_after_start`, `downtime_condition_valid`, `downtime_kind_valid`,
`downtime_reason_valid`, `downtime_booking_access_valid`, exclusion `downtime_no_overlap` (one resource, overlapping periods, not cancelled).

## API (coordinators and administrators, `LABS_STAFF_ACCESS`)

| Route | Behavior |
|---|---|
| `GET /api/labs/downtimes` | Paged, newest first. Filters: `resource_type` (`room`, `station`, `bench`, `equipment`), `resource_id` (needs `resource_type`), `state` (`scheduled`, `current`, `ended`, `cancelled`), `booking_access` (`closed`, `lab_staff`). |
| `POST /api/labs/downtimes` | 201 with the window. 409 `downtime_booking_conflict` (details `bench_booking_ids`, `equipment_booking_ids`) when reserving bookings overlap and `cancel_conflicting_bookings` is not true; 409 `downtime_overlap`; 409 `downtime_not_allowed` when the resource is not in service. `booking_access: lab_staff` (rooms, stations, benches; 422 for equipment) leaves lab staff bookings out of the conflict. |
| `GET /api/labs/downtimes/{id}` | One window. |
| `POST /api/labs/downtimes/{id}/actions/end` | Ends a started window now; an ended window is returned unchanged; 409 for a window that has not started or is cancelled. |
| `POST /api/labs/downtimes/{id}/actions/cancel` | Cancels a window that has not started; a cancelled window is returned unchanged; 409 once started. |
| `POST /api/labs/downtimes/{id}/actions/change-booking-access` | `booking_access` (required), `cancel_conflicting_bookings`. Opening to `lab_staff` never conflicts; closing reports (409 `downtime_booking_conflict`) or cancels the bookings overlapping the rest of the window. The current value is returned unchanged; 409 `downtime_not_allowed` for an ended or cancelled window; 422 for equipment. |

Lab staff access: a bench booking is not blocked by a `lab_staff` window when its holder (the creator; the
actor on create) holds the Labs `coord` role or higher. A `closed` window at any level still blocks staff.

Booked resources covered by a window: a room covers every bench at its stations, a station its benches, a
bench itself, an equipment unit its equipment bookings. Reserving means `reserved` or `in_progress` and
`pending` or `approved`.

## Write safety

`schedule_downtime` locks the resource, then (room) its stations, then the covered benches, in PK order,
before reading bookings. `change_downtime_booking_access` takes the same locks, then the window row. Bench booking writers lock the bench and then read downtime; equipment reservation
writers lock the unit. Same-resource overlap is the exclusion constraint, mapped to `DowntimeOverlap`.
Cancelled bookings go through `bench_bookings.public.cancel_bench_bookings_for_downtime` (which records an
`updated` notification intent) and `equipment.public.cancel_equipment_bookings_for_downtime`.

## Dependencies

Imports `bench_bookings.public` and `equipment.public`. Nothing imports this feature (higher workflow owner).
Compatibility write paths (room/station `change-status`, equipment `change-condition`, condition at loan
return) use the model primitives `ResourceDowntime.objects.start_now` / `end_current`. Room/station
`change-status` refuses with 409 `downtime_booking_conflict` while reserving bench bookings end after now;
equipment paths keep the hand-over check.

Moves: a bench move to another station, or a station move to another room, is refused (409, details
`bench_booking_ids`) while future bookings would fall in the new parents' downtime or a parent is not in
service (`bench_bookings_blocked_by_parents`).
