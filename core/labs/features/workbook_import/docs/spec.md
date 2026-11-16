# Workbook import: spec

- Tier: T2 (new public API, cross-feature writes, data entry for every resource type)
- Status: slice 1 implemented on branch `claude/epic-mayer-a4p14n`; needs human approval before merge.
- Owner decisions (2026-11-16): one workbook; create only; Labs administrators only; reference data is
  imported from its own sheets, never created from a typo in an equipment row; the v1 data-collection
  template is a reference and may be improved to fit the system.

## 1. What it does

An administrator downloads the **data workbook template**, fills it in, uploads it with **Check** (a dry run that
lists every problem) and then with **Apply** (all rows are created, or nothing).

| Endpoint | Purpose | Success | Failure |
|---|---|---|---|
| `GET /api/labs/workbook-imports/template` | Template v2 (.xlsx) with the current reference data filled in | `200` binary | `403` |
| `POST /api/labs/workbook-imports/actions/check` | Dry run. Runs every write and rolls back | `200` report (also when the report has errors) | `403`, `413`, `415`, `422` (file unreadable) |
| `POST /api/labs/workbook-imports/actions/apply` | Import | `200` report | `422` `validation_failed`, one detail per error, field `Sheet[row].Column`; nothing saved |

Uploads are `multipart/form-data` with one `file` part (UPL-1), at most 10 MB, and at most 5,000 data rows per
sheet. The content must be an .xlsx (zip) archive (sniffed, UPL-3). A .xlsx that unpacks to more than 200 MB is
refused (zip bomb). Formulas are not evaluated: the cached value Excel saved is read.

Report (`data`): `is_dry_run`, `is_valid`, `template_version`, `summary {created, existing, error_count,
warning_count}`, `sheets[] {key, name, rows, created, existing, failed, ignored_columns}`,
`problems[] {sheet, row, column, severity {value,label}, code, message}`, `unknown_sheets[]`.
`row` is the Excel row number, and `column` is the column name as it appears in the template.

## 2. Design choices

| Choice | Why |
|---|---|
| The server parses the file (openpyxl, `core/infrastructure/spreadsheets`) | The rules (category fields, slot capacity, utilities, lifecycle) live in the backend. A single parser means the row numbers in the report are exact, and the frontend only uploads and renders the report |
| One declaration (`queries/sheets.py`) drives both the template and the importer | The template and the importer cannot drift apart |
| Check = run the real writes, then roll back | The preview shows exactly what Apply will do, including rows that depend on rows earlier in the same file |
| One transaction; each row in a savepoint | All or nothing (WRT-7), but one bad row does not hide the problems of the other rows (ERR-7) |
| Every write goes through the owner's public command | `create_room`, `create_station`, `create_station_slot`, `generate_room_slots`, `create_bench`, `create_equipment`, `update_equipment`, `change_condition`, `place_equipment`, `schedule_downtime`, `change_*_lifecycle`. Reference rows use `core.reference_data.public.create_reference` |
| Reference rows that exist are *matched*, never changed | A re-import of the template is safe. Create-only applies to spaces and equipment, where an existing asset tag is an error |
| Names are resolved case-insensitively and scoped by their parent | Kind within its category, type within its kind, model within its manufacturer, city within its country. A name that is still ambiguous is an error that names the column to fill in |
| A dependent row points at its cause | e.g. `'ST-001' is in Stations row 7, which has errors` instead of a cascade of "not found" errors |

Race guard: the owners' row locks and constraints (active-SKU uniqueness, slot uniqueness, one active placement,
downtime exclusion), all inside one transaction, so a concurrent duplicate fails the whole import.
Idempotency: an applied file cannot be applied twice, because the asset tags then exist (`422`). Reference writes
carry an idempotency key derived from the file digest, sheet and row.

Documented same-app reads (feature template 3.3): the importer reads Labs models only to resolve names to ids
(departments, groups, geography, catalogs, rooms, room slots, stations, station slots, benches, equipment,
computing profiles for the `.rdp` file clean-up). It never writes them directly.

Side effect outside the database: creating a computing unit writes its `.rdp` file. When a run rolls back (a check,
or an apply with errors), the importer deletes the files it wrote.

## 3. Template v2 (changes against the v1 data-collection template)

| Area | v2 | Reason |
|---|---|---|
| Status columns | `Lifecycle`, `Access`, `Condition` replace the one `Status` | The system keeps these separately (resource-status design). Condition opens a downtime from now |
| Room/station lifecycle | In service or Retired | Rooms and stations are created in service; *planned* has no create path |
| Equipment lifecycle | Planned (on order) or In service | `create_equipment` accepts only these; Transferred, Lost and Borrowed are recorded in the app afterwards |
| Equipment placement | `Storage Room` on Equipment, or a row in **Bench Placements** (v1: Equipment Assignments) | One active placement per unit. Placements start now; history dates are not imported |
| Detail sheets | Asset tag plus category fields only | v1 auto columns (Name, Manufacturer, Product Model) are read and ignored |
| Computing | Hostname, MAC address, Technical User | The operating system is reported by the agent |
| Station Types | Its own sheet | v1 Lookups > Station Types is still read |
| Equipment Types / Product Models | Optional Category / Kind columns | Make repeated names unambiguous |
| Benches | No Department column | The department comes from the group (v1 column is checked against it) |
| Equipment | No Remarks; purchase and calibration columns removed | Not writable yet; v1 columns are reported as not imported |
| Users, Equipment Categories | Read-only, filled from the system | Users come from URS; categories are provisioned |
| Data Check / Summary / Field Map | Removed | The Check endpoint is the data check |
| Hidden sheets | `Lists` (choices for the dropdowns), `_Meta` (template version) | |

v1 files still import: v1 sheet and column names are aliases. A v1 `Status` is mapped:

| v1 value | Rooms / stations | Benches | Equipment |
|---|---|---|---|
| Available | in service, open | in service | in service |
| Reserved / Active | in service + warning (computed from bookings) | in service + warning | — |
| Issue / Closed | out-of-service downtime | — | — |
| Maintenance | in-maintenance downtime | in-maintenance downtime | in-maintenance (condition) |
| Out of service | — | out-of-service downtime | — |
| Restricted | restricted access | — | — |
| Retired | retired | retired | — |
| Planned / On Order | — | planned | planned |
| In-use / In-storage | — | — | in service (In-use without a bench placement is a warning) |
| Broken | — | — | out of service (condition) |
| Borrowed / Transferred / Lost | — | — | error: record it in the app after the import |

## 4. Sheets in slice 1

References: Departments, Groups, Countries, Cities, Buildings, Station Types, Bench Groups, Bench Types,
Screen Sizes, Resolutions, Lookups (interfaces, materials, network protocols, sample customers, sample
characteristics, technical users), Equipment Kinds, Equipment Types, Manufacturers, Product Models.
Spaces: Rooms (with Grid Rows × Grid Columns the room slots `R1C1 …` are created), Stations, Station Slots, Benches.
Equipment: Equipment, the eight detail sheets, Bench Placements.

Not yet imported (sheets with these names are reported as `sheet_not_imported`, never silently dropped):
Room Slots by hand, Specification Names, Specifications, Licenses, License Assignments, Purchases, Purchase Items,
Costs, and the equipment purchase and calibration columns. Each is a later slice through its owner's command.

## 5. Findings from the owner's v1 file (dry run, 2026-11-16, empty database)

457 rows would be created. The remaining errors are data questions:

- Category **Electronics** is used by 3 kinds and 18 manufacturers but does not exist in the system
  (`features/equipment/defaults.py` lists Accessory, Computing, Debugging, Display, Furniture, Instrument,
  Laboratory, Mechanical, Networking, Other, Power, Sample). Either add it to the defaults (equipment owner) or
  move those rows to an existing category.
- Owner IDs must be existing users (synced from URS); unknown logins are errors.
- Rooms: `Usable Square (m2)` has no model field (computed from length × width); reported, not imported.

## 6. Tests

`core/labs/features/workbook_import/tests/`: check vs apply, the full happy path through every sheet type, matching
existing references, all-or-nothing with error paths, create-only, the v1 headers and status mapping, administrator
access, a non-xlsx upload, the template round trip (download → check is valid with 0 created), and cell parsing
(numbers, decimals with a comma, Yes/No, `YYYY-Qn`, utilities, choices, the formula guard on export).
