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
| `GET /api/labs/resource-mappings` | `BenchMappingListAPIView` | Bench-rooted mapping list: one page of benches and only the rows they reference. |

### 3.1 Bench mapping list (`GET /api/labs/resource-mappings`)

Replaces the client pattern "list benches, then one `/benches/{id}/mapping` call per row" (N+1 requests, filters
and totals computed on one page only).

- Query (allowlisted, COL-3/COL-4; unknown or repeated keys are `400 invalid_query`): `q` (bench, station, room or
  placed unit, SKU or name), `room_id`, `station_id`, `bench_id`, `equipment_category_id`, `state`
  (`fully_mapped` | `needs_equipment` | `needs_placement`), `page`, `page_size` (1 to 100; more is `400`).
- `data`: the flat collections of the mapping reads. `benches` is the page (ordered by SKU); the other collections
  hold only what those benches reference (occupied station and room slots only, not whole grids).
- `meta.pagination`: page style (`count`, `page`, `page_size`, `next`, `previous`, ready-to-call URLs).
- `meta.summary`: `benches`, `fully_mapped`, `needs_equipment`, `needs_placement`, `equipment` over every bench that
  matches the filters, before `state` (the overview does not depend on the page or on the chosen state).
- State rule (`benches.queries.selectors.bench_mapping_list`): no live station in a live room → `needs_placement`;
  placed with no unit → `needs_equipment`; otherwise `fully_mapped`. The client applies the same rule to single reads.
- Query budget: summary 1 + page 1 + one per related collection (7), whatever the page size (asserted in tests).
- Access: Labs staff, like the other mapping reads.
