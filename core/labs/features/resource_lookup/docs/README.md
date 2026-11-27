# Resource lookup

`GET /api/labs/resources/lookup?q=&types=&limit=` turns a name, UID or SKU into typed resource references:
room, station, bench, equipment, license. People and the Lab Assistant type "A-12" or "SC-07" without
knowing the type.

- **Matching:** exact UID, exact SKU, exact name, then prefix, then contains (`match`). At most `limit`
  (1–10, default 5) rows per type, one query per type.
- **Access:** lab operators only (`lab_operations.manage`), like every other read of rooms, stations, equipment and
  licenses. Members find benches with `GET /api/labs/benches/booking-choices?q=` and
  `GET /api/labs/benches/availability?q=`, which are open to them.
- **Composition:** each owner feature exposes a `lookup_*` selector through its `public.py` (benches,
  equipment, locations, licenses); ranking is `core.labs.features.base.lookup.lookup_rows`.
- **Context:** bench → station · room; station → room; equipment → current bench, station, room or location
  note; license → product.
