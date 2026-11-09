# Feature Specification: Graphic Resource Mappings (`core/labs/features/resource_mappings`)

## 1. Domain Overview & Purpose
The Resource Mappings feature synthesizes multi-tier laboratory physical hierarchies into flat, cursor-paginated payloads designed for interactive 2D/3D canvas rendering without client-side deep joins.

---

## 2. Query Architecture & Projections

### 2.1 Multi-Collection Cursoring
- To prevent payload explosion in large facilities, the selector uses independent cursor markers for each entity tier:
  - `rooms_cursor`, `room_slots_cursor`, `stations_cursor`, `station_slots_cursor`, `benches_cursor`, `equipment_cursor`, `licenses_cursor`, `license_assignments_cursor`.
- Projections only retrieve graphic coordinates (`x`, `y`, `width`, `height`, `rotation`), identifiers, and essential labels.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/rooms/{resource_id}/mapping` | `RoomMappingAPIView` | Room layout with contained station placements. |
| `GET /api/labs/stations/{resource_id}/mapping` | `StationMappingAPIView` | Station docks with slot coordinates. |
| `GET /api/labs/benches/{resource_id}/mapping` | `BenchMappingAPIView` | Bench setup with mounted equipment hardware. |
| `GET /api/labs/equipment/{resource_id}/mapping` | `EquipmentMappingAPIView` | Equipment placement context within parent bench. |
