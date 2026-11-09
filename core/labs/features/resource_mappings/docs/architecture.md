# Resource Mappings Feature

## Purpose

Expose graphic-only placement context for a selected room, station, bench, or equipment item. Responses use independent flat collections and actual foreign-key/assignment identifiers. This feature owns cross-resource read composition only; locations, benches, equipment, and licenses remain owners of their data and provide narrow mapping projections through their public facades.

## Contract

Routes are slashless: `/api/labs/rooms/{id}/mapping`, `/api/labs/stations/{id}/mapping`, `/api/labs/benches/{id}/mapping`, and `/api/labs/equipment/{id}/mapping`. All require authentication and use the same active-resource/soft-delete selectors as their owner features.

The response has flat `rooms`, `room_slots`, `stations`, `station_slots`, `benches`, `equipment`, `licenses`, and `license_assignments` arrays. Relation fields are primary-key identifiers, not nested general resource detail. Equipment items carry the one active `bench_id` and `bench_assignment` attributes inline. Equipment-to-equipment relationships are not modeled. License summary fields are limited to `id`, `uid`, `sku`, `name`, and category. No lifecycle/status, bookings, computing activity, general header fields, license identifier, owner, or price is returned.

Each array is independently cursor-paginated with stable primary-key ordering, a shared page size (default 25, maximum 100), signed tokens bound to root type/id, collection, and page size, and matching `meta.pagination` entries. Query parameters are allowlisted and repeated parameters are rejected. For exceptionally large closures, clients may follow one collection cursor at a time; roots and direct ancestry remain visible in their corresponding arrays.

## Placement closure

- Room: selected room and slots, contained active stations and station slots, configured active benches, active assigned equipment and license assignments.
- Station: its active room/room slots when present, itself and station slots, configured active benches and their active assigned equipment/license assignments.
- Bench: itself, active station/room ancestry and slots when present, its active equipment and active license assignments.
- Equipment: itself; when actively assigned, its active bench, station/room ancestry and slots, sibling equipment and licenses. Unplaced equipment has no placement context.

`Room.room`, `Station.room`/`Station.slot`, `Bench.setup_location`/`Bench.station_slot`, `EquipmentAssignment`, and `LicenseAssignment` are the authoritative links. Room-slot row/column and station-slot position are graphic ordering data; `Station.position` is not reinterpreted as a coordinate system.

## Compatibility and layering

This endpoint is separate from enriched bench detail and the operational dashboard. Composition imports only `public.py` APIs of owning features and queries live under this feature. No model or migration is introduced. The deliberate flattened-ID deviation from usual relation objects is bounded to this graphic read projection; IDs preserve actual relation semantics, and pagination is independently represented under `meta.pagination`.
