# Design: Downtime windows open to lab staff bookings

- Tier: T2 (migration and constraint, public API contract, booking/concurrency, authorization rule)
- Status: Implemented on branch `claude/gracious-cray-omxgvw`; needs human approval before merge.
- Builds on: [resource status and downtime](resource-status-and-downtime.md) (rule 3, RS4).
- Scope: `core/labs/models/resource/base/{downtime,availability}.py`, `core/labs/features/{downtime,bench_bookings,benches,locations/stations,base}`.

## Problem

A downtime window on a room, station or bench blocks every bench booking in the period (rule 3), for every
user. Lab coordinators and administrators run the maintenance, calibration or renovation themselves and need
to reserve the benches for that work, or keep using them while a room is closed to everyone else. Today they
must end or cancel the window, book, and record it again, which loses the downtime record and opens a gap in
which anyone can book.

## Decision

Each window says who may still book the benches it covers: `booking_access`.

| Value | Label | Who can book the covered benches during the window |
|---|---|---|
| `closed` (default) | Closed to all bookings | No one (the behavior before this change) |
| `lab_staff` | Lab staff only | Users holding the Labs `coord` role or a role that implies it (`admin`, superusers) |

"Lab staff" is `has_labs_role(user, LabsRole.COORDINATOR)`: the existing role hierarchy, resolved from URS
groups. No new role and no change to who may write downtime (`LABS_STAFF_ACCESS`).

Alternatives considered:

- *A global switch "staff ignore downtime".* Rejected: a safety hold or an out-of-service fault must still
  block staff; the person recording the window knows which case it is.
- *A per-user allowlist on the window.* Rejected for now: no stated need, and it would add a relation and a
  UI. `booking_access` is a choice field, so a later value (for example `approved_users`) stays additive.

## Rules

| # | Rule |
|---|---|
| BA1 | `closed` is the default for the API, the model and the database (`db_default`), so existing rows and every compatibility path (`change-status`, `change-condition`, workbook import, `start_now`) keep blocking everyone. |
| BA2 | A bench booking is refused when a window of the bench, its station or its room overlaps the period, unless that window is `lab_staff` **and** the booking holder is lab staff. Each window is checked on its own: a `closed` window at any level still blocks staff. The message for a refused non-staff holder ends with "Only lab coordinators and administrators can book it." |
| BA3 | Scheduling a `lab_staff` window (RS4) reports and, with `cancel_conflicting_bookings`, cancels only the overlapping bookings whose creator is not lab staff. Lab staff bookings are kept. |
| BA4 | The holder is the booking's creator, not the editor. Create checks the actor (who becomes the creator); update, agent extension and agent end-time change check `booking.creator`. A coordinator therefore cannot move a member's booking into a `lab_staff` window. |
| BA5 | `POST /api/labs/downtimes/{id}/actions/change-booking-access` changes a scheduled or current window. Opening (`closed` → `lab_staff`) never conflicts. Closing (`lab_staff` → `closed`) applies RS4 to the rest of the window (`max(starts_at, now)` to `ends_at`): reserving or in-progress bench bookings there are refused with 409 `downtime_booking_conflict`, or cancelled in the same transaction with `cancel_conflicting_bookings: true`. Ended or cancelled windows answer 409 `downtime_not_allowed`. The current value returns the window unchanged. |
| BA6 | Equipment windows are always `closed` (422 on create or change): equipment reservations are not bench bookings and keep their hand-over rules. |
| BA7 | Moving a bench or station (rule 6) applies BA2 to the existing bookings: a `lab_staff` window of the new parent does not block bookings created by current lab staff. |

## Data and constraints

- `ResourceDowntime.booking_access`: `varchar(16)`, `default` and `db_default` `closed`.
- Check constraint `downtime_booking_access_valid` (`booking_access IN ('closed', 'lab_staff')`).
- Migration `labs.0004_downtime_booking_access`: add column with a database default (no table rewrite on
  PostgreSQL 11+, no backfill) and add the check constraint. Reversible with the standard reverse operations.

## API (additive)

| Change | Where |
|---|---|
| `booking_access` (`{value, label}`) on every `Downtime` | `GET/POST /api/labs/downtimes`, `GET /api/labs/downtimes/{id}`, the `end`, `cancel` actions |
| Optional request field `booking_access` (default `closed`) | `POST /api/labs/downtimes` |
| Optional query filter `booking_access` | `GET /api/labs/downtimes` |
| New action `POST /api/labs/downtimes/{id}/actions/change-booking-access` with `booking_access` (required) and `cancel_conflicting_bookings` (default false); returns the `Downtime` | downtime feature |
| `availability.booking_access` (`{value, label}` or null): null when available; `lab_staff` when every blocking level is a current `lab_staff` window of an in-service resource; else `closed` | room, station and bench reads |

No route, field or code was removed or renamed. The OpenAPI files are regenerated in the same change.

## Authorization

- Writing downtime, including the new action, stays `LABS_STAFF_ACCESS` (coordinators and administrators).
- The booking exemption is decided server-side from the holder's current Labs roles in every booking write
  path; the client cannot request it. API keys and anonymous actors are never lab staff.

## Write safety

- Bench booking writers lock the bench row (`lock_benches`) and then read downtime, including
  `booking_access`.
- `change_downtime_booking_access` locks the window's target with `lock_target` (room → stations → benches,
  in PK order: the downtime lock order), then the window row, then reads bookings. A booking written
  concurrently either commits first and is reported or cancelled, or waits for the bench lock and then reads
  the new access. End and cancel lock only the window row, so no lock cycle is added.
- `schedule_downtime` keeps its lock order; the staff filter is a subquery in the same statement.

## Residual risks

- **Role changes after booking.** The exemption is checked when a booking is written. If a coordinator
  loses the role later, their existing booking inside a `lab_staff` window stays. Closing the window (BA5)
  or cancelling the booking removes it. Inactive users are not counted as lab staff when a window is
  scheduled or closed, so their bookings are reported as conflicts.
- **Availability is "now".** `availability.booking_access` describes the window covering now, like
  `condition`. A future window's access is read from the downtime list.
- **Read cost.** Bench reads add three correlated subqueries (bench, station, room access) and room/station
  reads one or two, the same pattern as `downtime_reason`. The query count per list does not grow with rows.
- **Agent sessions.** Agent login eligibility does not read downtime (unchanged); only staff can hold a
  booking inside a `lab_staff` window, so this adds no new path for non-staff use.
