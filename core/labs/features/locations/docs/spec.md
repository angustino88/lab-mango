# Feature Specification: Physical Locations — Rooms & Stations (`core/labs/features/locations`)

## 1. Domain Overview & Purpose
The Locations feature represents geographic and facility real-estate topology: countries, cities, buildings, rooms, room grid slots, physical workbench stations, and station slots.

---

## 2. Data Models & Database Invariants

### 2.1 Geographic Reference Hierarchy
- `Country`: `code` (unique, e.g. "DE", "VN"), `name`.
- `City`: `name` (unique).
- `Building`: `name` (unique).
- `PhysicalLocationNode` (Abstract): Common polymorphic tree attributes (`parent`, `country`, `city`, `building`, `floor`).

### 2.2 `core.labs.models.Room` & `RoomSlot`
- **`Room`** (inherits `ResourceModel` and `PhysicalLocationNode`):
  - `room_type`, `capacity`, `area_sqm`, `operating_hours`, `room_manager`.
  - `lifecycle_status`: `planned`, `in_service` (default), `retired` (terminal). `access_policy`: `open` (default), `restricted`.
  - Computed, never stored: `condition` (downtime windows), `availability`, `activity_status` (bench bookings at its
    stations), and the deprecated seven-value `status`. See `docs/proposals/resource-status-and-downtime.md`.
- **`RoomSlot`**: A grid cell inside a room (`row_index`, `col_index`, `slot_code`, `status`). `status` is `usable`
  (default), `blocked` or `retired`; "occupied" is computed from `Station.slot`.

### 2.3 `core.labs.models.Station` & `StationSlot`
- **`Station`** (inherits `ResourceModel`):
  - `room` (FK `Room`, PROTECT).
  - `station_type` (FK `StationType`, PROTECT).
  - `lifecycle_status`, `access_policy`, and the computed fields as for rooms; availability also follows its room.
  - Rated limits: `max_power_w`, `max_load_kg`, `max_cooling_w`, `available_utilities`.
- **`StationSlot`**:
  - `station` (FK `Station`, PROTECT), `slot_number` (IntegerField).
  - `status`: `StationSlotStatus` (`in_service`, `out_of_service`, `retired`); "occupied" is computed from
    `Bench.station_slot`. API: `service_status` (stored), `occupied`, deprecated `status` and `is_active`.
  - Invariant: `UniqueConstraint(fields=("station", "slot_number"))`.

---

## 3. Options Standard Compliance (ADR 002)
- `GET /api/labs/rooms/options`: Flat `{id, sku, name}` room dropdown selector.
- `GET /api/labs/stations/options`: Flat `{id, sku, name}` station dropdown selector.
- `GET /api/labs/station-slots/options`: Flat `{id, sku, name}` slot dropdown selector.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/rooms` | `RoomListCreateAPIView` | Paginated room inventory. |
| `POST /api/labs/rooms` | `RoomListCreateAPIView` | Create room; `lifecycle_status` defaults to `in_service`, first history record written in the same transaction. |
| `POST /api/labs/rooms/{id}/actions/change-lifecycle` | `RoomLifecycleAPIView` | Set `lifecycle_status` and/or `access_policy`; retiring needs every station retired and ends or cancels downtime. |
| `POST /api/labs/rooms/{id}/actions/change-status` | `RoomStatusAPIView` | Deprecated seven-value write, mapped onto lifecycle, access policy and downtime; `reserved` is refused. |
| `GET /api/labs/rooms/{id}` | `RoomDetailAPIView` | Room specs and contained stations. |
| `PATCH /api/labs/rooms/{id}` | `RoomDetailAPIView` | Update room attributes. |
| `GET /api/labs/rooms/options` | `RoomSelectAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/rooms/status-summary` | `RoomStatusSummaryAPIView` | Distribution of the deprecated computed `status`. |
| `GET /api/labs/rooms/{room_id}/slots` | `RoomSlotListCreateAPIView` | Grid slots in room. |
| `GET /api/labs/rooms/{room_id}/history` | `RoomHistoryAPIView` | Lifecycle records (`status` holds the lifecycle; access changes in `metadata.access_policy`), newest first; each row has `actor` (`{id, username, display_name}`, null when unknown). Downtime history: `GET /api/labs/downtimes?resource_type=room&resource_id=`. |
| `GET` / `PUT` / `DELETE /api/labs/rooms/{room_id}/image` | `RoomImageAPIView` | Read, replace (multipart, one `file` part: JPEG/PNG/GIF/WebP, at most 5 MB) or remove the image; room reads return `image_url` (see `core/labs/features/base/docs/resource-images.md`). |
| `GET /api/labs/stations` | `StationListCreateAPIView` | Physical stations inventory. |
| `POST /api/labs/stations` | `StationListCreateAPIView` | Create physical station dock; `lifecycle_status` defaults to `in_service`, first history record written in the same transaction. |
| `POST /api/labs/stations/{id}/actions/change-lifecycle` | `StationLifecycleAPIView` | As for rooms; retiring needs every bench at the station retired. |
| `POST /api/labs/stations/{id}/actions/change-status` | `StationStatusAPIView` | Deprecated seven-value write (as for rooms). |
| `GET /api/labs/stations/{id}` | `StationDetailAPIView` | Station technical specifications and slots. |
| `PATCH /api/labs/stations/{id}` | `StationDetailAPIView` | Update station capacity ratings. |
| `GET /api/labs/stations/options` | `StationSelectAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/stations/status-summary` | `StationStatusSummaryAPIView` | Distribution of the deprecated computed `status`. |
| `GET /api/labs/stations/{station_id}/slots` | `StationSlotListCreateAPIView` | Slots on station. |
| `GET /api/labs/stations/{station_id}/history` | `StationHistoryAPIView` | Lifecycle records as for rooms; each row has `actor` (`{id, username, display_name}`, null when unknown). |
| `GET` / `PUT` / `DELETE /api/labs/stations/{station_id}/image` | `StationImageAPIView` | As for rooms; station reads return `image_url`. |
| `GET /api/labs/station-slots/options` | `StationSlotSelectAPIView` | Selector `{id, sku, name}`. |
