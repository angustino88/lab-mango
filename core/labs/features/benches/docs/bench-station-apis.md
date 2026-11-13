# Bench and station APIs

## Scope, status and authority

Status: current source-level API compatibility reference, not canonical layout or
runtime certification. Scope: bench/station routes, payloads, placement and locks.
The [Feature Template Specification](../../../../../docs/architecture/feature-template.md) owns feature structure,
command/query boundaries, public interfaces and test ownership. Existing layouts
and imports described here are transitional; documentation does not migrate them.

This documents the current [bench feature](../api/urls.py)
and [location feature](../../locations/api/urls.py), not the retired
lab-management APIs. Routes below are relative to the host's API mount; the feature
URLconfs use **no trailing slash**. Root bench/station routing is now enabled via
the [labs URL aggregator](../../../api_urls.py). Generated OpenAPI artifacts
and database-backed rollout validation remain separate gates.

See also the [response contract guide](../../../../../docs/api/contracts.md).

## Bench resource and dashboard detail split (2026-10-20)

The latest approved T2 contract makes `GET /api/labs/benches/{bench_id}` a lean
resource detail response using the standard Bench fields only. It accepts no query
parameters; any query parameter returns 400. The historical `equipment` and
`booking_summary` enrichments are no longer emitted from this endpoint. The
`equipment_url` on this detail response points to the registered slashless
`/api/labs/benches/{bench_id}/equipment` subresource. List and write response URL
shapes remain unchanged.

The dashboard clicked-bench endpoint `GET /api/labs/dashboard/benches/{bench_id}`
is the operational detail view. It provides equipment grouped by category with
active license summaries, computing activity status and heartbeat freshness, and
current/upcoming booking schedule fields. It omits booking-user identity, host and
remote IP addresses, remote-user identity, OS and RDP URLs. Dashboard list behavior
is unchanged. Resource mapping endpoints remain separate and graphic-only.

The enriched read projection and its owner-facade rules remain available internally
pending reference cleanup; they are not the contract for ordinary bench detail.
The lean contract change is breaking. Coordinate frontend clients before release;
no new API version route or deprecation route was added.

## Current layout versus target boundaries

Benches currently use `application/services.py` and `queries/selectors.py`;
locations include nested `rooms`/`stations` application/query/API slices and a
`common` slice. These are existing compatibility paths, not a template for new
work. Target room/station capabilities live within the owning feature's `api`,
`application` and `queries` layers, without a second child-feature tree.

Current [bench views](../api/views.py) and
[station views](../../locations/stations/api/views.py) import their
own `public` facade. The target rule is the opposite: internal API calls import
their own `application`/`queries` directly; `public` is a leaf facade for outside
callers only. Migrate those imports and legacy boundary tests together.
Every business write, including reference-data and non-HTTP writes, enters an
application command owning policy and atomic persistence. API serializers map
input/output, never own business persistence or transactions. Cross-feature
behavior uses the other owner's public commands/queries; documented same-app
model reads are not permission to mutate another owner's state.

## Responsibilities

- `Station` is a physical fixture. It may have a `room` and one `RoomSlot` (`slot`).
- `Bench` is a virtual workspace. Its optional `setup_location` references a station;
  optional `station_slot` selects one stable bench position within that station.
  Multiple benches can share a station, but a station slot has at most one bench.
- `group` is cross-resource classification; `bench_group` is logical bench grouping.
  They are independent, and neither owns hardware.
- [EquipmentAssignment](../../../models/resource/equipment/assignment.py) owns
  hardware placement/history. There is no singleton `LabEquipment` mapping and
  no `Bench.station` field. Bench reads do not create equipment, status or audit rows.
- Favorites are user/bench memberships, not a bench ownership or visibility rule.

All exposed views require authentication. Current feature permissions do not add
owner/group-specific authorization. Authentication failures follow the configured
authentication backend, not the domain error table below.

## Routes and success codes

### Benches

| Route | Methods and success codes | Meaning |
| --- | --- | --- |
| `/benches` | GET 200, POST 201 | List or create workspaces |
| `/benches/{bench_id}` | GET 200, PUT 200, PATCH 200, DELETE 204 | Read, update, soft-delete |
| `/benches/{bench_id}/place` | PATCH 200 | Change only station association/slot |
| `/benches/{bench_id}/favorite` | POST 200, DELETE 204 | Idempotently add/remove the caller's membership |
| `/benches/options` | GET 200 | Compact workspace choices (OPT-1 selector; `id`, `sku`, `name` only) |
| `/benches/reference-data` | GET 200 | Active types/groups, live stations, lifecycle choices |
| `/bench-groups` | GET 200, POST 201 | List/create reference data |
| `/bench-groups/{reference_id}` | GET 200, PATCH 200, DELETE 204 | Update/retire reference data |
| `/bench-types` | GET 200, POST 201 | List/create reference data |
| `/bench-types/{reference_id}` | GET 200, PATCH 200, DELETE 204 | Update/retire reference data |

Both bench list routes accept `setup_location`, `bench_group`, `type` (positive
integer IDs), `lifecycle_status`, `favorite` (boolean), and `search` (up to 255
characters). Search matches SKU, name or description; ordering is SKU then PK.
List responses are unpaginated in these handlers. Selector-level `favorite=None`
means no bookmark filter, `True` selects the caller's bookmarks, and `False`
selects other live benches. Omitting `favorite` applies no bookmark filter on
either list route, including HTML/`QueryDict` requests.

### Stations and station slots

| Route | Methods and success codes | Meaning |
| --- | --- | --- |
| `/stations` | GET 200, POST 201 | List/create physical fixtures |
| `/stations/{station_id}` | GET 200, PUT 200, PATCH 200, DELETE 204 | Read/update/soft-delete |
| `/stations/{station_id}/place` | PATCH 200 | Room/room-slot/coordinate placement |
| `/stations/{station_id}/slots` | GET 200, POST 201 | List/create bench positions |
| `/stations/{station_id}/slots/{slot_id}` | GET 200, PUT 200, PATCH 200, DELETE 204 | Read/update/hard-delete a position |
| `/stations/{station_id}/status` | POST 201 | Append a status record |
| `/stations/{station_id}/history` | GET 200 | Newest status first, PK breaks timestamp ties; `actor` names who recorded it |
| `/stations/reference-data` | GET 200 | Station types, active bench types, rooms, status/slot choices |
| `/station-types` | GET 200, POST 201 | List/create station types |
| `/station-types/{type_id}` | GET 200, PATCH 200, DELETE 204 | Update/hard-delete an unreferenced type |

Station lists accept `room`, `type` (positive IDs), and `search`; search matches
SKU, name or label. Slot detail lookup is scoped to its station, not just slot PK.
Unsupported verbs return 405; `Allow` includes only implemented verbs plus OPTIONS.

## Bench fields

The [explicit serializers](../api/serializers.py) accept:

| Fields | Transport and semantics |
| --- | --- |
| `sku`, `name`, `remark` | SKU required on create; trimmed, nonblank, unique among live benches. Name/remark may be blank. SKU uniqueness is per resource model, not across all equipment/stations. |
| `group`, `owner`, `type`, `bench_group` | Nullable positive IDs; transport maps to command `_id` arguments, without serializer DB lookups. Selecting an inactive type/group is rejected; unrelated edits retain existing retired references. |
| `image` | Image upload, not an arbitrary nested resource |
| `description`, `documentation_url`, `criticality` | Workspace text, validated URL, free-form classification; criticality is not a fixed enum |
| `setup_location`, `station_slot` | Nullable positive IDs; station slot requires a matching station |
| `lifecycle_status` | Not writable here (drift fixed in docs): set with `POST /api/labs/benches/{id}/actions/change-lifecycle` to `planned`, `in_service` or `retired` (terminal). Out of service is a downtime window (`/api/labs/downtimes`). Reads add `condition`, `availability` (follows station and room) and `activity_status`; `status` is the deprecated four-value field |
| `requested_power_w`, `requested_load_kg`, `requested_cooling_w` | Nullable nonnegative integers; zero is valid; null contributes zero to station aggregates |
| `required_utilities` | JSON object describing requirements, not a list |
| `commissioning_date` | Nullable date |
| `last_inspected_at`, `next_inspection_due_at` | Nullable date-times; no inspection ordering policy currently enforced |

Ordinary bench resource read responses include the standard bench fields plus `id`,
`uid`, `created_at`, `updated_at`, `setup_location_path`, `is_favorite`,
`equipment_count`, and `equipment_url`. They do not inline assignment collections.
The dashboard clicked-bench endpoint returns category-grouped equipment, active
license summaries, activity freshness, and booking schedule data. Resource mapping
endpoints return graphic-only placement relationships and license summaries. All
response fields are read-only.
The compact select projection exposes only `id`, `sku`, `name`; its `status`/`lifecycle_status` filter uses the deprecated four values.
Favorites expose `id`, `bench`, `created` (not the user's personal fields).

The bench equipment subresource contains live assignments to non-deleted equipment,
ordered by `position`, then assignment ID. Its equipment fields include assignment
`id`, `equipment_id`, `equipment_uid`, equipment `sku`, `name`, `kind` (kind FK ID
rendered as text), `role`, `position`, `monitor`, and `assigned_at`. Graphic mapping
uses the separate resource-mappings endpoint. Equipment editing belongs to the
assignment/equipment APIs, not these bench write payloads.

Unknown, legacy and read-only write fields are rejected with 400; they are not
silently ignored. Examples include `station`, `uid`, `creator`, `deleted_at`,
`is_favorite`, `equipment`, and raw command names such as `setup_location_id`.
Type/group writes accept only `name`, optional `description`, optional `active`.
Direct reference lists include retired rows; reference-data lists exclude them.
DELETE on bench types/groups sets `active=False`, preserving references.

PUT uses the update command: omitted fields remain unchanged, not reset to
defaults. Bench PUT/PATCH currently accept an empty object as a revalidated no-op.
This differs from placement PATCH, which requires at least one placement field.

## Placement, lifecycle and deletion

- Bench placement accepts only `setup_location` and `station_slot`. Missing keys
  preserve existing values. Full detach sends both explicitly as null. Sending
  only `station_slot=null` keeps the station association. Sending only
  `setup_location=null` while a slot remains assigned fails domain validation.
- A slot must belong to the selected station and be active. `available` and
  `reserved` slots may be occupied; an `occupied` slot is allowed only when
  staying in that same slot and no other current/historical bench owns it.
  `maintenance`, `out_of_service`, `retired` and inactive slots reject placement.
- A nonempty compatible-type set requires the bench's type, including rejecting
  an untyped bench. Empty compatibility means unrestricted. Slot power/load and
  utilities are checked in addition to station totals. Slot dimension/network
  fields are not additional bench-demand checks; there is no slot cooling limit.
- Moving/detaching releases the old slot only if its status is `occupied`;
  successful placement changes the new slot to `occupied` atomically.
- Lifecycle is an explicit bench field, not equipment-derived status. No
  transition graph or lifecycle-based placement exclusion currently exists.
  `retired` is not soft deletion: every non-deleted configured bench still
  contributes to capacity and selector counts, regardless of lifecycle.
- Bench DELETE rejects any assignment with `unassigned_at=null`, even if its
  equipment is deleted. Unassign first. Historical assignments are retained.
  Successful deletion clears placement, stamps `deleted_at`, and releases an
  occupied slot. Favorite rows survive; live bench selectors hide the deleted
  bench. Removing one's retained favorite remains allowed after deletion;
  adding a favorite to a deleted bench returns 404. An active SKU can be reused.
- Station DELETE requires all live configured benches to be moved/detached,
  clears room placement, soft-deletes, and releases an occupied room slot.
  Station-slot DELETE rejects current **or historical** bench references.

## Station fields, capacities and observations

Station writes accept `sku`, `name`, `group`, `owner`, `remark`, `label`, `type`,
`room`, `slot`, `position`, `height_mm`, `width_mm`, `depth_mm`,
`orientation_degrees`, `max_load_kg`, `bench_capacity`, `max_concurrent_users`,
`usable_surface_mm2`, `power_capacity_w`, `power_reserved_w`, `cooling_capacity_w`,
`network_port_capacity`, `utilities`, `safety_classification`.
`image` is a read field here, not a station create/update field.

Station placement accepts only `room`, `slot`, `position`, `orientation_degrees`.
Coordinates are nullable or exactly three finite values in [-1000000, 1000000];
orientation is 0–359. A room slot requires the same room and a station-position
slot type; dimensions, load, utility and allocated room capacity must fit.
Explicitly clear both `room` and `slot` to detach an occupied room placement.

Station-slot writes accept `position_index` (zero-based), `slot_code`, `label`,
`is_active`, `status`, `width_mm`, `depth_mm`, `height_mm`, `max_load_kg`,
`power_capacity_w`, `network_port_count`, `utilities`, `compatible_bench_types`
(list of positive IDs). Codes are trimmed/uppercased and unique per station,
as are position indexes. Configured positions, including inactive ones, must
fit a finite station `bench_capacity`. Editing an occupied/referenced slot
cannot invalidate its existing bench's type, utilities, power/load or usability.

All finite station limits apply to the **aggregate** of non-deleted configured
benches: count, sum of requested load, cooling, and requested power **plus**
station reserved power. Null capacities mean unspecified/unbounded; zero is a
real limit. Station reductions check current benches and all slot positions
under the same parent-lock protocol as bench writes. Required utilities must
be supported independently by the station and selected slot: false/null
requirements are ignored, true requires a truthy value, numbers require a
numeric value at least as large, and other values require equality. This is a
simple object policy, not a typed engineering-units schema.

Station projections include `status`, `active_bench_count`,
`allocated_power_w`, `available_power_w`, `available_slot_count`, `location_path`,
and nested `bench_slots`. Available power subtracts reserved and allocated bench
power; null station capacity yields null available power. Available-slot count
requires active, `available`, unreferenced slots. Separate correlated subqueries
prevent equipment/bench/slot join fan-out from inflating aggregates.

Station `status` is a stored column (like equipment `lifecycle_state`), default
`available`, limited to the choices below by the `station_status_valid` check
constraint. Creating a station writes a first history record with that value in the
same transaction. Station status POST accepts `status` (`available`, `reserved`,
`issue`, `restricted`, `closed`, `maintenance`, `retired`) and optional object
`metadata`; under the station row lock it appends a history record and updates the
column. Reading station projections does not create history. Stations have no
`operational_status` field.
Station types accept only `name`; DELETE is blocked by live or historical stations.

## Errors and response envelopes

Success payloads follow the shared envelope (`data` plus contract metadata).
DELETE returns **204 with no body**. The operation contracts declare:

| Status | Causes | Domain payload |
| --- | --- | --- |
| 400 | Unknown/read-only fields, invalid IDs/values, utility/type/capacity mismatch, empty or inconsistent placement | `application/problem+json`, field `errors`; domain validation uses `code=validation_error` |
| 404 | Missing/deleted live resource, missing station/slot/type/group, wrong parent-scoped slot | `application/problem+json`, not-found contract |
| 409 | Active SKU/name duplicate, unavailable/occupied or historically assigned slot, stale placement, live equipment on deletion, referenced location/type, integrity/protected-reference failure | `code=bench_conflict` or `location_conflict`, descriptive detail |

Problems contain `type`, `title`, `status`, `detail`, and applicable `code`/`errors`.
Transport validation uses the shared validation message code; do not depend on
English detail strings or assume every authentication/405 error uses this domain
mapping. Unexpected programming errors are not
converted to 400/404/409.

## Transactions, locks and query ownership

- Bench create locks the target station; update/place/delete locks old and new
  stations in sorted, deduplicated PK order, **then the bench**, then station slots
  in sorted PK order. A preliminary station association is reread after locking;
  concurrent movement returns 409 instead of silently validating stale placement.
- Station mutations lock rooms in sorted PK order, then the station, then room
  slots. Station-slot commands lock station before slot and do **not** lock bench
  rows; they read bench allocations/references under the station lock. Bench
  capacity commands and station reductions serialize on that parent station.
- Equipment assignment commands must lock the bench before adding a live
  assignment; this coordinates with bench deletion's live-assignment check.
- Favorites lock their bench and use the unique `(user, bench)` constraint and
  `get_or_create`. Removal locks through `all_objects` so retained memberships
  remain removable. References retire inside transactional commands.
- Integrity/protected-reference exceptions escape the atomic block before
  mapping to a domain conflict; partial bench/slot writes must roll back together.
  Direct ORM saves/bulk updates do not provide this cross-row command protocol.
- Selectors use ordinary read queries, not write locks. User favorite state is a
  correlated `Exists`, not a multiplying join; assignment prefetch selects live
  equipment with kind/type and orders by position/ID. Read-committed projections
  are not a promise of a single locked snapshot across all prefetch queries.
- Atomic persistence and event delivery are distinct guarantees. Best-effort
  dispatch uses `transaction.on_commit`; required delivery needs an outbox row in
  the command's transaction, retryable dispatch and idempotent consumers. Neither
  locks nor an after-commit callback alone prove durable delivery. This reference
  does not claim the current bench/station implementation has an outbox.

## Known limitations and rollout gate

Root bench/station routing is present in the source aggregator. Earlier work
reported isolated system-check and regression-test results; these are historical
results, not re-executed or certified by this documentation update. Source reads
do not establish a deployable schema or PostgreSQL certification.

1. **Migration imports require validation:** the inspected users migrations now
  reference infrastructure upload helpers, not the previously reported
  `core.utils.upload_utils` path. Revalidate the full graph in isolation;
  passing system checks alone does not validate migration imports. Earlier reported
  `showmigrations --plan` failures are not a current execution result here.
2. **Fresh-schema work remains:** [labs migrations](../../../migrations) are
  currently empty in the inspected working tree. A coherent reviewed migration
  graph and isolated test/database setup are required before database-backed tests;
  a fresh initial graph is permitted only within an approved isolated rebuild;
   legacy databases require a separate reviewed data-transfer/migration plan.
   PostgreSQL `ArrayField` and locking semantics are not certified by SQLite.
3. **Historical external-integration caveat:** an earlier report mentioned a
  charts dependency on `labs.Computer`; that path is not a current inventory or
  established blocker. Re-inventory actual enabled apps and dependencies.
  Legacy fixtures, old routes and generated schemas may also require integration
  work; successful OpenAPI generation alone does not certify those integrations.
4. **PostgreSQL tests pending, not concurrency certification:**
  Existing bench feature tests (`tests/unit/test_bench_feature.py`) and
  station feature tests (`tests/unit/test_station_feature.py`) exercise local routes,
   serializers, policies, SQL structure and every real async bench/location handler
  with only boundary I/O mocked. Marked direct-model database cases cover
   idempotency, isolation, deletion/slot release, capacity and transactional
  rollback, SKU uniqueness and prefetches, but require an isolated reviewed
  PostgreSQL test schema. No PostgreSQL execution is claimed by this update;
   simultaneous-transaction/deadlock tests remain a rollout requirement.

Target test ownership follows the [template's test scope](../../../../../docs/architecture/feature-template.md#45-tests):
private feature API/application/query tests stay with the owning feature; model
integrity and app registration tests live under `core/labs/tests/`. Existing
top-level feature-only suites are transitional, not the location for new tests;
cross-feature integration and architecture tests remain top-level.

For DB-free testing, use the workspace virtual environment with
`DJANGO_READ_DOT_ENV_FILE=False`, `DATABASE_URL=sqlite:///:memory:`,
`DJANGO_SECRET_KEY=obvious-synthetic-test-value`, and a synthetic in-memory Celery
broker; select `pytest -m 'not django_db'`. Do not load environment files or point
these tests at an existing PostgreSQL database. Database-backed validation remains
pending an isolated reviewed PostgreSQL setup and validation of migration imports.
