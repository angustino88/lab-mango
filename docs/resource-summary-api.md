# Independent resource summary APIs

Risk: T2 (additive public API). Human approval and independent review required
before merge. No migration or existing response contract change.

## Ownership and endpoints

All paths below are relative to `/api/labs/`. All use GET, are safe and
idempotent, and require no request body, idempotency key, or concurrency token.

| Path | Owner | Output | Access inherited from |
|---|---|---|---|
| equipment/status-summary | Equipment | Lifecycle status counts | EquipmentAPIView |
| equipment/computing/activity-summary | Equipment | Stored activity counts | EquipmentAPIView |
| equipment/{category}/summary | Equipment category | That category's lifecycle status counts | EquipmentAPIView |
| licenses/status-summary | Licenses | Recorded status counts | FeatureAPIView |
| licenses/categories/summary | Licenses | Paginated category counts | FeatureAPIView |
| benches/status-summary | Benches | Stored lifecycle counts | BenchAPIView |
| rooms/status-summary | Locations/rooms | Recorded lifecycle counts | RoomAPIView |
| stations/status-summary | Locations/stations | Recorded lifecycle counts | StationAPIView |

Views and serializers live in each owner's existing API modules, not separate
summary API modules. Queries remain in the owning feature's query layer.
Only technical aggregation and count wire shapes are shared. No dashboard coupling.
Equipment and licenses retain user/API-key access; benches and locations retain
their existing authenticated-user access. No new permission policy is introduced.

## Contracts and semantics

Status responses use the existing success envelope with `data.total_count`,
`data.unknown_status_count`, and `data.statuses`. Each bucket has
`status: {value, label}` and `resource_count`. All declared choices are included,
even with zero inventory. Clients must tolerate future status values.
No query parameters are accepted. Invalid queries return 400 `invalid_query`.

Each registered equipment category has an independent route under its existing
category namespace, for example `/api/labs/equipment/computing/summary` and
`/api/labs/equipment/debugging/summary`. Each route counts only its registered
equipment subtype and returns lifecycle status buckets in the standard success
envelope. These fixed-size summaries accept no query parameters. The generic
`equipment/categories/summary` route is not provided. License category counts
remain a separate paginated collection at `/api/labs/licenses/categories/summary`.

All aggregates exclude soft-deleted resources. Equipment subtypes count once in
the parent inventory. Latest recorded states use descending `created` then ID.
Missing or unrecognized states are unknown, not assumed available or offline.
Computing activity includes unassigned assets and uses stored telemetry status;
heartbeat freshness is not recalculated. License assignment and expiry do not
override recorded status. Bench lifecycle is not booking or computing status.
Room/station recorded lifecycle is not operational configuration.
No individual user activity, license identifiers, or financial details are returned.
Aggregates are live reads, not a transactionally consistent cross-endpoint snapshot.

## Validation and schema expectations

API tests cover independent routing for every registered equipment category,
response envelopes, query rejection, authentication denial, license category
pagination, bounds, and nullable categories.
PostgreSQL tests cover latest-record tiebreaks, soft-deleted inventory, missing
telemetry, unassigned computing assets, lifecycle separation, and one-query budgets.

OpenAPI adds the category-scoped summary paths and distinct named summary schemas to equipment,
licenses, benches, and locations modules. Existing dashboard paths are unchanged;
the experimental combined dashboard/resource-summary path is removed before release.

## Known integration gap

Default test settings do not enable the existing request-correlation middleware
or shared exception handler. Contract tests explicitly enable both. Runtime
settings wiring must be verified separately; this change does not alter global
middleware, permissions, or exception handling.

## Review and handoff

Response standard review areas: success envelope, explicit output fields,
bounded collections, strict query parameters, extensible enum references,
error envelopes, correlation headers, and schema/runtime agreement. Full
section-15 Rule-ID review and independent review remain required before merge.
Broader license/location SQL coverage and concurrent-update tests remain follow-ups.