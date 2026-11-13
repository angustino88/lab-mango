# Feature specification: Downtime (`core/labs/features/downtime`)

Design and owner decisions: [resource status and downtime](../../../../../docs/proposals/resource-status-and-downtime.md).

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
| `starts_at`, `ends_at` | Half-open period; `ends_at` empty while the end is unknown |
| `cancelled_at`, `ended_by`, `notes` | Cancellation of a window that never started; who ended it |

Constraints: `downtime_ends_after_start`, `downtime_condition_valid`, `downtime_kind_valid`,
`downtime_reason_valid`, exclusion `downtime_no_overlap` (one resource, overlapping periods, not cancelled).

## API (coordinators and administrators, `LABS_STAFF_ACCESS`)

| Route | Behavior |
|---|---|
| `GET /api/labs/downtimes` | Paged, newest first. Filters: `resource_type` (`room`, `station`, `bench`, `equipment`), `resource_id` (needs `resource_type`), `state` (`scheduled`, `current`, `ended`, `cancelled`). |
| `POST /api/labs/downtimes` | 201 with the window. 409 `downtime_booking_conflict` (details `bench_booking_ids`, `equipment_booking_ids`) when reserving bookings overlap and `cancel_conflicting_bookings` is not true; 409 `downtime_overlap`; 409 `downtime_not_allowed` when the resource is not in service. |
| `GET /api/labs/downtimes/{id}` | One window. |
| `POST /api/labs/downtimes/{id}/actions/end` | Ends a started window now; an ended window is returned unchanged; 409 for a window that has not started or is cancelled. |
| `POST /api/labs/downtimes/{id}/actions/cancel` | Cancels a window that has not started; a cancelled window is returned unchanged; 409 once started. |

Booked resources covered by a window: a room covers every bench at its stations, a station its benches, a
bench itself, an equipment unit its equipment bookings. Reserving means `reserved` or `in_progress` and
`pending` or `approved`.

## Write safety

`schedule_downtime` locks the resource, then (room) its stations, then the covered benches, in PK order,
before reading bookings. Bench booking writers lock the bench and then read downtime; equipment reservation
writers lock the unit. Same-resource overlap is the exclusion constraint, mapped to `DowntimeOverlap`.
Cancelled bookings go through `bench_bookings.public.cancel_bench_bookings_for_downtime` (which records an
`updated` notification intent) and `equipment.public.cancel_equipment_bookings_for_downtime`.

## Dependencies

Imports `bench_bookings.public` and `equipment.public`. Nothing imports this feature (higher workflow owner).
Compatibility write paths (room/station `change-status`, equipment `change-condition`, condition at loan
return) use the model primitives `ResourceDowntime.objects.start_now` / `end_current` and do not check bookings.
