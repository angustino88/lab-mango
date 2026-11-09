# Lab Mango models v2 - what changed

Built from your `models.zip`. Everything agreed in the review is in these files, and
the data-collection Excel template (`labmango_data_template.xlsx`) matches the final field names.

## How it was checked
- Django 5.2 system check on the whole package: **no issues** (original: no issues).
- `makemigrations` runs and shows the schema diff (`draft_0002_auto_generated.py`, reference only).
- Logic tests without a database: root content type of `ComputingEquipment` is `Equipment`,
  yearly equivalent, currency validator, room country/city/building sync, category key.
- **Not done:** no run against PostgreSQL, your real migration history, your test suite, or your
  services/serializers/admin (they were not in the zip). Expect to adjust code that uses removed names.

## New models
| Model | Purpose |
|---|---|
| `Department` | Organisation unit; `ResourceGroup.department` links teams to it |
| `ResourceServiceRecord` | Calibration / inspection / maintenance / safety-test history for ANY resource |
| `SpecificationDefinition`, `ProductModelSpecification` | Technical specs per product model (channels, CAN FD, max voltage ...) |
| `EquipmentInterface`, `Material` | One shared interface list and one material list |

## Changed models
| Area | Change |
|---|---|
| `ResourceModel` (all resources) | + `department`; group must belong to the department; `service_records`, `latest_service_record()`; audits use the root content type |
| `ResourceGroup` | + `department` |
| `City` / `Building` | `City.country`, `Building.city`, `Building.address`; names unique per parent (was globally unique) |
| `Room` | `operational_status` removed (use `RoomStatusRecord`); country/city/building kept but validated and derived from the building |
| `Station` | `operational_status` removed |
| `Bench` | help text separates `bench_group` (function) from `group` (team); inspection dates marked deprecated |
| `EquipmentCategory` | + `key` (stable slug). Category checks use it, so renaming a category cannot break validation |
| `EquipmentProductModel` | + `default_power_draw_w`, `default_weight_kg` (copied to new assets) |
| `Equipment` | + `firmware_version`, `power_draw_w`, `weight_kg`, `warranty_until`, `storage_room`, `calibration_required`; validates manufacturer / model / type / kind consistency; fills defaults from the model; `last_calibrated_at`, `next_calibration_due_at`, `calibration_overdue` read from service records |
| `ComputingEquipment` | + `hostname`, `mac_address`; RDP file uses `hostname` (falls back to SKU); `ip_address` is agent-reported, not collected |
| `NetworkingEquipment` | + `mac_address` |
| `DisplaySize` / `DisplayResolution` | + numeric `diagonal_in`, `width_px`, `height_px` |
| Display / Instrument / Sample | interfaces now point to `EquipmentInterface` |
| Power | `interface` points to `EquipmentInterface` |
| Mechanical / Furniture | `material` points to `Material` |
| `TechnicalUser` | `username` unique |
| `License*` lookups | required, unique (case-insensitive) names; `__str__` can no longer return `None`; `LicenseProduct.vendor` |
| `License` | + `seats`; vendor must match the product's vendor; `LicenseAssignment` enforces the seat limit |
| `Expense` | now valid for Room, Station, Bench, Equipment and License; new types calibration, repair, service_contract, license_fee, insurance; `set_resource()`, `for_resource()`, `yearly_amount` |
| Billing | one shared `BillingPeriod`, `PaymentTransactionType`, `default_currency()` (setting `LABS_DEFAULT_CURRENCY`), currency validator on all money models |
| `Purchase` | `items_total`, `is_balanced`; resource link must use the root model |
| `ResourceAudit` / `ResourceChangeLog` | `for_resource()` matches root and subclass content types (no history split) |
| Bookings | + `requester`, `approved_at`, `rejection_reason`; rejected needs a reason; database exclusion constraint against double booking (needs `btree_gist`); `approved_by` uses `AUTH_USER_MODEL` |
| `BookingNotification` | can belong to an equipment booking; exactly one booking is required |
| `LabProject` | `project_name` required text, + `code` (unique), `owner`, `starts_on`, `ends_on`, `active` |

## Removed
`DisplayInterface`, `InstrumentInterface`, `PowerInterface`, `SampleInterface` (-> `EquipmentInterface`);
`MechanicalMaterial`, `FurnitureMaterial` (-> `Material`).

## Deprecated (kept for one release)
`LicenseAgreement`, `LicensePayment`: license fees are now `Expense(expense_type="license_fee")`.
`Bench.last_inspected_at` / `next_inspection_due_at`: use `ResourceServiceRecord(kind="inspection")`.

## Breaking changes to check in your code
- `Room.objects.filter(operational_status=...)`, `Station...operational_status` no longer exist.
- Imports of the removed interface/material classes.
- `City.name` / `Building.name` are no longer globally unique.
- Code writing `ResourceAudit(resource=...)` should use `record_audit()` (writes the root content type).
- `Expense`/`PurchaseItemResource`: pass root models (`Equipment`, not `ComputingEquipment`); `Expense.set_resource()` does it.
- Saving a rejected booking without `rejection_reason` now fails.

## Deliberately NOT changed (decide later)
- `Room.country` / `Room.city` stay as fields (now validated); they can be dropped once everything reads `building.city.country`.
- `Bench.setup_location` stays (validated against `station_slot`); it is derivable and could be removed.
- Empty subclasses (`Accessory`, `Debugging`, `Laboratory`, `Other`) stay; converting them to proxies needs a careful migration.
- `Station.usable_surface_mm2`, `bench_capacity` stay stored.
