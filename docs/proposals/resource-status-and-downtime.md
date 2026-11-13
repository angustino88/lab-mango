# Design: Resource lifecycle, downtime, availability and activity

- Tier: T2 (migration, constraints, public API contract, booking/concurrency, cross-feature)
- Status: Owner decisions recorded below (2026-11-13); implemented on branch `claude/inspiring-mayer-5xgod0`;
  needs human approval before merge.
- Scope: rooms, stations, station slots, room slots, benches, equipment condition, bench bookings and
  equipment reservations (`core/labs/models/resource/**`, `core/labs/features/{locations,benches,bench_bookings,equipment,downtime,dashboard,resource_audit}`).

## Problem

Rooms and stations stored one `status` with seven values that mixed four concepts: lifecycle (`retired`),
condition (`issue`, `maintenance`, `closed`), access policy (`restricted`) and booking (`reserved`). There
were no room or station bookings, so `reserved` was set by hand and went stale. Nothing told a user
whether a room or station was being used. Slots stored `occupied`, which duplicated the bench and station
relations (`stations/queries/selectors.py` had to check both). Bench kept `out_of_service` inside its
lifecycle (OD3), while equipment split lifecycle from condition. No resource could have maintenance
planned in advance, and downtime could not be measured.

## Owner decisions (2026-11-13)

| # | Decision |
|---|---|
| RS1 | Use the full model: stored lifecycle, downtime records with time windows, computed condition, availability and activity. Implement in one change, not in phases. |
| RS2 | Equipment condition moves onto the shared downtime records too (one pattern for every resource). This revisits OD3 for benches. |
| RS3 | Keep old API fields read-only and computed (`status` on rooms and stations); old write endpoints map to the new model. |
| RS4 | A downtime window that overlaps reserving bookings is refused (409, bookings listed) unless the caller sends `cancel_conflicting_bookings: true`; the bookings are then cancelled in the same transaction. |
| RS5 | No deployed database: the schema is folded into `core/labs/migrations/0001_initial.py`. |

## Model

### Stored

| Concept | Where | Values |
|---|---|---|
| Lifecycle | `Room.lifecycle_status`, `Station.lifecycle_status`, `Bench.lifecycle_status` | `planned`, `in_service`, `retired` (`ResourceLifecycleStatus`) |
| Equipment lifecycle | `Equipment.lifecycle_state` (unchanged) | `planned`, `in_service`, `transferred_out`, `retired`, `lost` |
| Access policy | `Room.access_policy`, `Station.access_policy` | `open`, `restricted` |
| Downtime | `ResourceDowntime` (generic link to the root resource model, like `ResourceServiceRecord`) | `condition` (`in_maintenance`, `out_of_service`), `kind` (`planned`, `unplanned`), `reason` (`maintenance`, `fault`, `calibration`, `safety_hold`, `renovation`, `other`), `starts_at`, `ends_at` (null while open), `notes`, `cancelled_at` |
| Station slot | `StationSlot.status` | `in_service`, `out_of_service`, `retired` (`is_active` removed) |
| Room slot | `RoomSlot.status` | `usable`, `blocked`, `retired` |
| Lifecycle history | `RoomStatusRecord`, `StationStatusRecord` (`status` holds the lifecycle; an access change is recorded with `metadata.access_policy`) | |

Database guards on `ResourceDowntime`: `ends_at > starts_at`; condition, kind and reason in their enums;
exclusion constraint `downtime_no_overlap` (same resource, overlapping `[starts_at, ends_at)`, not cancelled).

### Computed (never stored)

| Field | Rule |
|---|---|
| `condition` | `out_of_service` or `in_maintenance` from the downtime window covering now (worst first), else `operational`. |
| `availability` | `available` when the resource and every parent (bench → station → room) are `in_service` and `operational`; otherwise `unavailable` with `blocked_by` (the resource that blocks) and `reason`. Problems pass **down**. |
| `activity_status` | `active` (a booking is in progress), `scheduled` (an approved reserved booking starts later today), `idle`. Rolls **up**: a station takes the strongest value of its benches, a room of its stations' benches. Monitoring activity is not used yet (no per-bench signal; not verified). |
| `status` (rooms, stations, deprecated) | `retired` → `retired`; `planned` → `closed`; condition `out_of_service` → `issue`; `in_maintenance` → `maintenance`; access `restricted` → `restricted`; activity `active`/`scheduled` → `reserved`; else `available`. |
| Slot occupancy | A station slot is occupied when a bench references it; a room slot when a station references it. The legacy slot `status` read value is derived from that. |

Equipment `display_status` keeps its priority table; its `broken` and `maintenance` rows now read the
computed condition.

## Rules

1. Downtime can be recorded only for a resource whose lifecycle is `in_service`.
2. Leaving service (`retired`, or equipment `transferred_out`/`retired`/`lost`) ends the open downtime and
   cancels future windows. A found equipment unit (`lost` → `in_service`) opens an `in_maintenance` window.
3. A booking (bench) or reservation (equipment) is refused when the resource, or a parent, is not
   `in_service`, or when any downtime window of the resource or a parent overlaps the requested period.
4. Ending a downtime window sets `ends_at` to now (only an open or current window). Cancelling is for a
   window that has not started; it keeps the row with `cancelled_at`.
5. The old write paths keep their old behavior and do not check bookings: room/station `change-status`,
   bench `lifecycle_status=out_of_service`, equipment `change-condition` and the condition recorded at loan
   return. They open or end an unplanned window starting now.

## API

| Route | Purpose |
|---|---|
| `GET /api/labs/downtimes?resource_type=&resource_id=&active=` | List windows (paged). |
| `POST /api/labs/downtimes` | Schedule or start a window: `resource_type` (`room`, `station`, `bench`, `equipment`), `resource_id`, `condition`, `kind`, `reason`, `starts_at` (default now), `ends_at` (optional), `notes`, `cancel_conflicting_bookings`. 409 `downtime_booking_conflict` lists the bookings. |
| `GET /api/labs/downtimes/{id}` | One window. |
| `POST /api/labs/downtimes/{id}/actions/end` | End a current window now. |
| `POST /api/labs/downtimes/{id}/actions/cancel` | Cancel a window that has not started. |
| `POST /api/labs/rooms/{id}/actions/change-lifecycle`, `.../stations/{id}/actions/change-lifecycle` | Set `lifecycle_status` and/or `access_policy`. |
| Room, station, bench reads | Add `lifecycle_status`, `access_policy` (room/station), `condition`, `availability`, `activity_status`. |

Access: all downtime routes use `LABS_STAFF_ACCESS` (coordinators and admins), the same as every
location, bench and equipment write. No access-control change.

## Ownership and locks

- `ResourceDowntime` is a shared model in `core/labs/models/resource/base/downtime.py`. Its manager holds
  the read expressions (condition, overlap) and two persistence primitives used by the old write paths
  (`start_now`, `end_current`), following `ResourceModel.record_audit`.
- The new `core/labs/features/downtime` feature owns the API and the conflict workflow. It is the higher
  workflow owner: it imports `bench_bookings.public` and `equipment.public`; nothing imports it, so no
  feature cycle is added. Booking writers read downtime through the model manager.
- Lock order for a downtime write: room → stations → benches (PK order) for a location; the equipment row
  for equipment. Bench booking writers already lock the bench row and then read downtime; equipment
  reservation writers already lock the equipment row. Whichever commits first is seen by the other.
- Same-resource overlap is guarded by the exclusion constraint (mapped to 409 `downtime_overlap`).

## Residual risks

- Moving a bench (new setup location) into a station that has downtime does not re-check that bench's
  future bookings; availability shows it, but those bookings stay. Not handled in this change.
- Activity uses bookings only. A bench used without a booking shows `idle`.
- Old write paths open windows without booking checks (RS3 compatibility); new clients should use
  `/api/labs/downtimes`.
- `retired` is terminal for rooms, stations and benches (`LIFECYCLE_TRANSITIONS`); before this change any
  value could be set. A resource that comes back is registered again.
- Bench `lifecycle_status` reads no longer return `out_of_service`; the deprecated `status` field (and the
  `status` filter, status summary and dashboard field) still do, computed from downtime.
- Equipment condition changes are no longer `EquipmentEvent` rows; the display-status history replays
  downtime windows instead.
