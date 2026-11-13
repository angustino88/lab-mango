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
  - `room_status`: Enum (`planned`, `operational`, `maintenance`, `decommissioned`).
- **`RoomSlot`**: Represents a physical coordinate grid position inside a room (`slot_number`, `x_coord`, `y_coord`, `status`).

### 2.3 `core.labs.models.Station` & `StationSlot`
- **`Station`** (inherits `ResourceModel`):
  - `room` (FK `Room`, PROTECT).
  - `station_type` (FK `StationType`, PROTECT).
  - `station_status`: Enum (`operational`, `maintenance`, `inactive`).
  - Rated limits: `max_power_w`, `max_load_kg`, `max_cooling_w`, `available_utilities`.
- **`StationSlot`**:
  - `station` (FK `Station`, PROTECT), `slot_number` (IntegerField).
  - `status`: `StationSlotStatus` (`available`, `occupied`, `reserved`, `maintenance`).
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
| `POST /api/labs/rooms` | `RoomListCreateAPIView` | Create room. |
| `GET /api/labs/rooms/{id}` | `RoomDetailAPIView` | Room specs and contained stations. |
| `PATCH /api/labs/rooms/{id}` | `RoomDetailAPIView` | Update room attributes. |
| `GET /api/labs/rooms/options` | `RoomSelectAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/rooms/status-summary` | `RoomStatusSummaryAPIView` | Room operational status distribution. |
| `GET /api/labs/rooms/{room_id}/slots` | `RoomSlotListCreateAPIView` | Grid slots in room. |
| `GET /api/labs/rooms/{room_id}/history` | `RoomHistoryAPIView` | Status records, newest first; each row has `actor` (`{id, username, display_name}`, null when unknown). |
| `GET /api/labs/stations` | `StationListCreateAPIView` | Physical stations inventory. |
| `POST /api/labs/stations` | `StationListCreateAPIView` | Create physical station dock. |
| `GET /api/labs/stations/{id}` | `StationDetailAPIView` | Station technical specifications and slots. |
| `PATCH /api/labs/stations/{id}` | `StationDetailAPIView` | Update station capacity ratings. |
| `GET /api/labs/stations/options` | `StationSelectAPIView` | Selector `{id, sku, name}`. |
| `GET /api/labs/stations/status-summary` | `StationStatusSummaryAPIView` | Station status distribution. |
| `GET /api/labs/stations/{station_id}/slots` | `StationSlotListCreateAPIView` | Slots on station. |
| `GET /api/labs/stations/{station_id}/history` | `StationHistoryAPIView` | Status records, newest first; each row has `actor` (`{id, username, display_name}`, null when unknown). |
| `GET /api/labs/station-slots/options` | `StationSlotSelectAPIView` | Selector `{id, sku, name}`. |
