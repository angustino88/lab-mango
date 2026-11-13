# Frontend guide: resource status, downtime, availability and activity

Audience: the React/TypeScript frontend team. This guide says what the API returns and how to show it.
Design and owner decisions: [resource status and downtime](../proposals/resource-status-and-downtime.md).
Contract source of truth: the generated OpenAPI (`openapi/labs-downtime.yml`, `labs-locations.yml`,
`labs-benches.yml`, `labs-equipment.yml`). Response and error envelopes follow the
[response standard](response-standard.md) (`{"data": ...}`, `{"error": {...}}`).

## 1. The idea in one picture

A room, station or bench answers four separate questions. Never merge them into one value in the UI state.

| Question | Field | Stored or computed | Who changes it |
|---|---|---|---|
| Does the lab run it? | `lifecycle_status` | stored | a coordinator (change-lifecycle) |
| Who may use it? (rooms, stations) | `access_policy` | stored | a coordinator (change-lifecycle) |
| Does it work right now? | `condition` | computed from downtime windows | a coordinator (downtime API) |
| Can it be used now, given its parents? | `availability` | computed | nobody, it follows from the above |
| Is someone using it right now? | `activity_status` | computed from bookings and agent reports | nobody |

```
Room R101 ──────────────── problems pass DOWN (availability) ──────────▶
 └─ Station ST-01
     ├─ Bench B-Radar-01   ◀── activity passes UP (activity_status) ────
     └─ Bench B-Video-02
```

- If the room is in maintenance, every station and bench in it is `unavailable`, with `blocked_by` naming the room.
- If any bench is `active`, its station and its room are `active` too.
- **"Is it in work?"** = `activity_status.value === "active"`.

## 2. Values

All enum fields arrive as `{ "value": "...", "label": "..." }` (use `value` in code, `label` for display),
except `availability`, which is an object of its own.

| Field | Values | Notes |
|---|---|---|
| `lifecycle_status` | `planned`, `in_service`, `retired` | `retired` is final; it cannot go back |
| `access_policy` | `open`, `restricted` | Rooms and stations only. Not a status: a restricted room can be fully working |
| `condition` | `operational`, `in_maintenance`, `out_of_service` | From the downtime window covering now |
| `availability.value` | `available`, `unavailable` | See below |
| `activity_status` | `idle`, `scheduled`, `active` | `scheduled` = an approved booking starts later today |

`availability` object:

```json
{
  "value": "unavailable",
  "blocked_by": { "type": "room", "id": 12, "name": "R101" },
  "condition": "in_maintenance",
  "reason": "maintenance"
}
```

| Key | Meaning |
|---|---|
| `blocked_by` | The first resource that blocks: the resource itself, then its station, then its room. `null` when available |
| `condition` | `blocked_by`'s condition (`operational` when it is blocked by lifecycle) |
| `reason` | A downtime reason (`maintenance`, `fault`, `calibration`, `safety_hold`, `renovation`, `other`) or a lifecycle value (`planned`, `retired`) |

Equipment keeps its own `lifecycle_state` and `display_status`. Its `condition` now comes from the same
downtime windows, so the values and the badge logic you already have do not change.

## 3. TypeScript types

```ts
export type Choice<T extends string> = { value: T; label: string };

export type LifecycleStatus = "planned" | "in_service" | "retired";
export type AccessPolicy = "open" | "restricted";
export type Condition = "operational" | "in_maintenance" | "out_of_service";
export type ActivityStatus = "idle" | "scheduled" | "active";
export type ResourceType = "room" | "station" | "bench" | "equipment";
export type DowntimeReason = "maintenance" | "fault" | "calibration" | "safety_hold" | "renovation" | "other";
export type DowntimeKind = "planned" | "unplanned";
export type DowntimeState = "scheduled" | "current" | "ended" | "cancelled";

export interface Availability {
  value: "available" | "unavailable";
  blocked_by: { type: "room" | "station" | "bench"; id: number; name: string } | null;
  condition: Condition | null;
  reason: DowntimeReason | LifecycleStatus | null;
}

/** Shared by Room, Station and Bench reads. */
export interface ResourceState {
  lifecycle_status: Choice<LifecycleStatus>;
  condition: Choice<Condition>;
  availability: Availability;
  activity_status: Choice<ActivityStatus>;
  /** @deprecated use the fields above (section 9). */
  status: Choice<string> | null;
}
export interface LocationState extends ResourceState {
  access_policy: Choice<AccessPolicy>;
}

export interface Downtime {
  id: number;
  resource: { type: ResourceType; id: number };
  condition: Choice<"in_maintenance" | "out_of_service">;
  kind: Choice<DowntimeKind>;
  reason: Choice<DowntimeReason>;
  state: DowntimeState;
  starts_at: string;            // ISO 8601 with offset
  ends_at: string | null;       // null: end not known yet
  cancelled_at: string | null;
  notes: string;
  actor: { id: number; username: string; display_name: string } | null;
  ended_by: { id: number; username: string; display_name: string } | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleDowntimeRequest {
  resource_type: ResourceType;
  resource_id: number;
  condition: "in_maintenance" | "out_of_service";
  reason?: DowntimeReason;               // default "other"
  kind?: DowntimeKind | null;            // default: planned if it starts later, else unplanned
  starts_at?: string | null;             // default: now
  ends_at?: string | null;               // default: open-ended
  notes?: string;                        // max 2000
  cancel_conflicting_bookings?: boolean; // default false
}
```

## 4. Showing status

### 4.1 One badge for lists and cards

Show **one** badge, picked in this order (first match wins), and put the other facts in a tooltip or the detail panel:

```ts
export function badge(r: ResourceState) {
  const a = r.availability;
  if (r.lifecycle_status.value === "retired") return { text: "Retired", tone: "neutral" };
  if (r.lifecycle_status.value === "planned") return { text: "Planned", tone: "info" };
  if (r.condition.value !== "operational")
    return { text: r.condition.label, tone: r.condition.value === "out_of_service" ? "danger" : "warning" };
  if (a.value === "unavailable" && a.blocked_by)
    return { text: `Unavailable (${a.blocked_by.type} ${a.blocked_by.name})`, tone: "warning" };
  if (r.activity_status.value === "active") return { text: "In use", tone: "success" };
  if (r.activity_status.value === "scheduled") return { text: "Booked today", tone: "info" };
  return { text: "Available", tone: "success-subtle" };
}
```

Add a separate small lock icon when `access_policy.value === "restricted"`; do not use it as the badge.

### 4.2 Detail panel

Show the four questions as four rows, so a user sees *why*:

| Row | Content |
|---|---|
| Lifecycle | `lifecycle_status.label` |
| Condition | `condition.label`, plus the current downtime window (reason, until `ends_at` or "until further notice") |
| Availability | "Available", or "Unavailable: blocked by Room R101 (maintenance)" with a link to `blocked_by` |
| Activity | `activity_status.label` |
| Access | `access_policy.label` (rooms, stations) |

Add a **Downtime** tab with the windows of this resource (section 5.2) and, for coordinators, the actions of section 6.

### 4.3 Slots

| Field | Meaning |
|---|---|
| `service_status` | Stored. Station slot: `in_service`, `out_of_service`, `retired`. Room slot: `usable`, `blocked`, `retired` |
| `occupied` | Computed: a bench (station slot) or station (room slot) uses it |
| `status`, `is_active` | Deprecated (section 9) |

A slot can take a bench or station only when `service_status` is `in_service` / `usable` and `occupied` is false.

## 5. Reading

### 5.1 Resource lists and details

The new fields are on every list and detail response:
`GET /api/labs/rooms`, `/rooms/{id}`, `/stations`, `/stations/{id}`, `/benches`, `/benches/{id}`.

Filters, comma-separated for several values (repeating a parameter is rejected with 400):

| Resource | New filters |
|---|---|
| Rooms, stations | `lifecycle_status`, `access_policy`, `condition`, `activity_status` |
| Benches | `lifecycle_status`, `condition`, `activity_status` |

Example: `GET /api/labs/benches?condition=in_maintenance,out_of_service&activity_status=idle`.
Read `GET /api/labs/{rooms|stations|benches}/filters` to build filter UIs; it lists every filter with its choices.

Dropdown values: `GET /api/labs/stations/reference-data` returns `lifecycle_statuses`, `access_policies`
and `slot_statuses` (plus deprecated `statuses`); `GET /api/labs/benches/reference-data` returns
`lifecycle_statuses` (plus deprecated `statuses`).

### 5.2 Downtime windows

`GET /api/labs/downtimes` (paged: `page`, `page_size` up to 100). Filters:
`resource_type`, `resource_id` (needs `resource_type`), `state` (`scheduled`, `current`, `ended`, `cancelled`).

```http
GET /api/labs/downtimes?resource_type=room&resource_id=12&state=scheduled
```

Use it for the Downtime tab and a maintenance calendar. A window with `ends_at: null` is open-ended; draw it
to the edge of the visible range and label it "until further notice". Windows of one resource never overlap.

A room window also blocks every station and bench in it. To show "everything affecting bench 7", request
the bench, its station (`setup_location.id`) and its room (from the station) and merge the lists.

`GET /api/labs/downtimes/{id}` returns one window.

## 6. Writing (coordinators and administrators only)

Hide these controls for other users; the API answers 403 to them.

### 6.1 Schedule or start downtime

```http
POST /api/labs/downtimes
{
  "resource_type": "room",
  "resource_id": 12,
  "condition": "in_maintenance",
  "reason": "maintenance",
  "starts_at": "2026-11-20T08:00:00+07:00",
  "ends_at": "2026-11-20T17:00:00+07:00",
  "notes": "Air conditioning repair"
}
```

`201` returns the `Downtime`. Leave out `starts_at` for "starting now"; leave out `ends_at` when the end is unknown.

**If bookings overlap**, the API refuses with `409`:

```json
{
  "error": {
    "code": "downtime_booking_conflict",
    "message": "Bookings overlap this downtime window. Cancel them or choose another period.",
    "details": [
      {
        "field": "bench_bookings.41",
        "code": "booking_overlaps_downtime",
        "message": "Booking BK-7Q2M (2026-11-20 09:00 to 2026-11-20 11:00) overlaps the downtime."
      }
    ],
    "request_id": "1a56dc6b2bb44c1b9dfae7c3751e4166"
  }
}
```

Each `details` entry is one booking: `field` is `bench_bookings.<id>` or `equipment_bookings.<id>`.
Recommended flow:

1. Show a confirmation dialog listing the `details[].message` lines ("These 3 bookings will be cancelled").
   Link each to the booking by the id after the dot in `field`.
2. On confirm, resend the same body with `"cancel_conflicting_bookings": true`. The bookings are cancelled in
   the same transaction and their owners get the normal booking notification.
3. Or let the user pick another period.

```ts
const bookingIds = (details: { field: string | null; code: string }[]) =>
  details
    .filter((d) => d.code === "booking_overlaps_downtime" && d.field)
    .map((d) => {
      const [kind, id] = d.field!.split(".");
      return { kind: kind as "bench_bookings" | "equipment_bookings", id: Number(id) };
    });
```

Other errors:

| Status, code | Meaning | UI |
|---|---|---|
| 409 `downtime_overlap` | Another window of this resource overlaps | "This resource already has downtime in that period"; show its windows |
| 409 `downtime_not_allowed` | The resource is not in service (planned or retired) | Disable the action for non-in-service resources |
| 404 | Resource does not exist | Refresh the list |
| 400 / 422 `validation_failed` | Bad input, e.g. `ends_at` before `starts_at` | Field errors from `details[].field` |

### 6.2 End or cancel

| Action | Allowed when | Request |
|---|---|---|
| End now | `state` is `current` | `POST /api/labs/downtimes/{id}/actions/end` |
| Cancel | `state` is `scheduled` | `POST /api/labs/downtimes/{id}/actions/cancel` |

Both return the updated `Downtime` and are safe to retry (a second call returns the same result).
The wrong action returns 409 `downtime_not_allowed`. Show "End now" only for `current` and "Cancel" only for `scheduled`.

### 6.3 Change lifecycle or access

```http
POST /api/labs/rooms/{id}/actions/change-lifecycle      { "lifecycle_status": "retired" }
POST /api/labs/stations/{id}/actions/change-lifecycle   { "access_policy": "restricted" }
POST /api/labs/benches/{id}/actions/change-lifecycle    { "lifecycle_status": "in_service" }
```

Rooms and stations accept `lifecycle_status` and/or `access_policy` (and optional `metadata`). Benches accept
`lifecycle_status`. The response is the updated resource.

- Allowed moves: `planned → in_service`, `planned → retired`, `in_service → retired`. Anything else is 422.
  Offer only the allowed targets.
- Retiring is final: ask for confirmation. It ends current downtime and cancels planned windows.
- A room can be retired only after all its stations are retired; a station only after its benches are (409).
- "Out of service" is not a lifecycle value: use downtime (6.1).

## 7. Effects elsewhere in the UI

| Screen | What to handle |
|---|---|
| Bench booking form | Creating or changing a booking now fails with 409 `bench_booking_conflict` ("The bench is unavailable for the requested period: Room is in maintenance ...") when the period overlaps downtime of the bench, its station or its room, and with 422 when the station or room is not in service. Pre-check with the bench's `availability` and the downtime list, and grey out blocked time in the calendar |
| Agent booking extension | New refusal reason `bench_unavailable` next to `bench_not_in_service` |
| Moving a bench or station | 409 (`bench_conflict` for a bench, `location_conflict` for a station) with `details` entries `bench_bookings.<id>` (code `booking_overlaps_downtime`) when its future bookings would fall in the new parent's downtime; the same codes without details when the target station or room is retired. Cancel or move the listed bookings, then retry |
| Equipment | `change-condition` works as before. Reservations are refused when a downtime window with a known end overlaps the period. Equipment can also get windows from the downtime API (`resource_type: "equipment"`) |
| Room / station history | `GET .../history` rows now hold the lifecycle value in `status`; an access change has `metadata.access_policy`; an old change-status call has `metadata.legacy_status`. Use the downtime list for condition history |

## 8. Freshness

Computed fields are calculated when you request them. Nothing is pushed.

- After any write (downtime, lifecycle, booking), refetch the affected resource and its parents and children
  (for a room: its stations and benches).
- On boards that show "in use" (rooms, stations, benches), poll the list every 30 to 60 seconds while the tab
  is visible. `activity_status` changes when bookings start or end and when agents report activity.
- A scheduled window becomes `current` at `starts_at` with no write. Refetch at that moment if a window starts
  while the page is open.

## 9. Deprecated fields and how to move off them

They still work, so the current frontend keeps running. New screens should not use them. No removal date
is set yet; the repository owner decides it.

| Deprecated | Where | Use instead |
|---|---|---|
| `status` (7 values) | rooms, stations: reads, `?status=` filter, `status-summary` | `lifecycle_status`, `access_policy`, `condition`, `activity_status` |
| `POST .../actions/change-status` | rooms, stations | `change-lifecycle` and `/api/labs/downtimes`. Mapping: `available` ends current downtime and opens access; `maintenance`, `issue`, `closed` open a window from now (refused with 409 `downtime_booking_conflict` while bookings remain); `restricted` sets access; `retired` retires; `reserved` is refused |
| `status` (4 values) | benches: reads, `?status=`, `status-summary`, dashboard `lifecycle_status` | `lifecycle_status` plus `condition` (`out_of_service` now means an in-service bench with downtime) |
| slot `status`, `is_active` | station and room slots | `service_status`, `occupied` |

Old `status` values are computed as: retired → `retired`; planned → `closed`; condition out of service →
`issue`; in maintenance → `maintenance`; restricted → `restricted`; active or scheduled → `reserved`; else `available`.

Name clash: the dashboard's existing `activity_status` filter is **computing** activity (`free`, `active`,
`inactive`, `offline`, `maintaining`). It is not the resource `activity_status` of this guide.

## 10. Checklist for the frontend change

- [ ] Types from section 3; badges from section 4.1; detail rows from section 4.2.
- [ ] Downtime tab with list, schedule form, conflict dialog (6.1), end and cancel buttons by `state` (6.2).
- [ ] Lifecycle and access actions with allowed targets only and a confirmation for retiring (6.3).
- [ ] Booking calendar greys out downtime and handles the new 409 messages (7).
- [ ] Refetch after writes and poll boards (8).
- [ ] No new code reads deprecated fields (9).
- [ ] Controls hidden for users who are not coordinators or administrators.

## 11. Scenarios to test against a real backend

| # | Do | Expect |
|---|---|---|
| 1 | Schedule room maintenance tomorrow 08:00 to 17:00 with no bookings | 201; window `scheduled`; room, its stations and benches show downtime in their Downtime tabs |
| 2 | Same, with a booking at 09:00 on a bench in the room | 409 with one `bench_bookings.<id>` entry; confirm; booking cancelled; 201 |
| 3 | Try to book that bench at 10:00 tomorrow | 409 "The bench is unavailable for the requested period: Room is in maintenance ..." |
| 4 | Start an unplanned fault on a station now, no end | Its benches read `availability.value = "unavailable"`, `blocked_by.type = "station"` |
| 5 | End that window | Benches read `available` again after refetch |
| 6 | Start a booking (check-in) on a bench | Bench, station and room read `activity_status = active` |
| 7 | Retire a room with a station still in service | 409; retire the station first, then the room; room `retired`; no way back |
| 8 | Move a bench with a booking into a station that is down | 409 with the booking in `details` |
