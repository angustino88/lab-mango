# Monitored device connections

Implemented backend and frontend contract. The external agent collector and physical
hardware behavior are not verified in the selected repositories.

## Ownership and behavior

An enrolled computer agent reports device observations. Equipment matches exact,
nonblank serial numbers against the equipment-declared interfaces (interface names
are case-insensitive). Capability names alone never identify an asset. Unknown
serials remain `unmatched`; incompatible interfaces are `interface_mismatch`;
multiple compatible candidates remain `ambiguous`. Matching never creates inventory
or changes assignments, lifecycle, activity, bookings, RDP targets or session logs.

Equipment owns matching queries and frozen DTOs through `public.py`/`contracts.py`.
Monitoring owns observations, replay receipts and current connections. Agents owns
credential identity and revocation fencing. Legacy `computing.monitored_devices`
JSON and its operator write behavior are preserved; the UI uses the typed API.

```mermaid
flowchart LR
    A[Signed computer agent] --> I[Snapshot intake]
    E[Equipment serials and interfaces] --> M[Public matching query]
    I --> M
    I --> T[Monitoring transaction]
    T --> L[Immutable events]
    T --> C[Current connections]
    C --> U[Monitored Devices panel]
    R[Agent revoke or enrollment] --> F[Invalidate freshness]
    F --> C
```

## Endpoints and wire contract

| Endpoint | Access | Result |
| --- | --- | --- |
| `GET /agent/monitoring-policy` | Existing signed agent authentication | Current `generation_key`, limits and up to 200 catalog interface names |
| `POST /agent/device-observations/actions/report` | Existing signed agent authentication | Report action acknowledgment; UUID `Idempotency-Key` header required |
| `GET /api/labs/device-connections?computer_id=42` | Existing Labs coordinator/admin or enabled API key policy | Paginated typed connections, maximum page size 100 |

`/agent/info` advertises the new capability and paths. The server derives the
reporting computer from the signing identity. Client-selected computer/agent fields
and unknown nested fields are rejected. Catalog hints do not claim OS collector
support. Report network devices only through explicitly configured targets.

Example POST body; replace the generation with the actual policy result:

```json
{
  "generation_key": "be0cde7f-9d44-482e-9328-4aaf0cb92434",
  "collector_key": "usb",
  "sequence": 1,
  "collected_at": "2026-11-17T03:00:00Z",
  "is_complete": true,
  "devices": [{
    "observation_key": "usb:stable-instance",
    "interface_name": "USB",
    "name": "Measurement probe",
    "serial_number": "LAB-PROBE-001",
    "state": "connected"
  }]
}
```

Collector keys are lowercase slugs, maximum 32 characters. Device strings are
bounded to 255 characters. Send at most 200 records and 256 KiB, with at most 200
connected devices per computer/collector across partial updates. Sequence is a
persisted positive integer, maximum 9007199254740991. Collection time must be
timezone-aware and no more than five minutes in the future.

The first report per collector/enrollment generation must be a complete snapshot.
Incremental (`is_complete: false`) batches must continue the collector cursor exactly
(`sequence = cursor + 1`). An incremental batch that skips ahead returns 409
`snapshot_required` and writes nothing; the agent recovers by sending a complete
snapshot with a newer sequence. Complete snapshots may skip ahead because they are
self-contained. This guarantees a lost or delayed delta (for example a detach) is never
silently dropped.
A complete snapshot disconnects omitted currently connected devices only within
that collector. Partial updates never disconnect omitted devices. Empty complete
snapshots are valid. A detach without a serial preserves known evidence for that
instance; a reconnect without a serial remains unresolved. Multipart snapshots are
not supported: never mark a truncated
or failed collector result complete. Instance keys must be stable across snapshots.

Acknowledgment is `data: {batch_key, sequence, disposition: {value, label}, received_at}`.
Disposition is `applied` or `stale`. Canonically identical retry returns the original
body with `Idempotency-Replayed: true`, with no freshness or event side effects.
Missing Idempotency-Key returns 400 `idempotency_key_required`; malformed/overlength
keys return 400 `invalid_idempotency_key`. Reusing the header key with changed content
returns 422 `idempotency_key_reuse`.
Reusing a sequence with a different key returns 409 `observation_conflict`. Older
sequences are acknowledged as stale without changing current state. Receipts are
purged after `DEVICE_OBSERVATION_RECEIPT_RETENTION_DAYS` (default 14), so retries must
complete within that window; see [Retention](#retention).

Read rows contain computer/equipment references `{id, uid, name}` and lookup interface
references `{id, name}`, nullable unresolved
references, reported `interface_name`, serial/name evidence, collector/observation
keys, enum-shaped state/match/freshness, and observed/received timestamps.

## Integrity and freshness

| Invariant | Guard |
| --- | --- |
| Authenticated identity stays valid through commit | Equipment → identity locks; recheck ACTIVE, fingerprint, enrollment time and equipment |
| No cross-enrollment sequence reset | Server-derived generation from agent/key/enrollment; first generation report must be complete |
| One ordered collector cursor | `device_cursor_computer_collector`, positive-sequence check and parent lock |
| Durable batch/sequence identity | `device_batch_replay_key`, `device_batch_sequence`, content hash and original receipt |
| One projection per device instance | `device_connection_observation`, valid-enum and positive-sequence checks |
| No partial writes or side effects | One transaction for receipt, projections, cursor and existing `MonitoringEvent` |
| Bounded synchronous reconciliation | Active-count cap; SQL updates only connected omissions; no repeated historical disconnect updates |

Lock order is equipment → authenticated identity → monitoring cursor/projections.
Lifecycle commands already holding identity lock invalidate cursors in the same
transaction without acquiring equipment afterward. No external I/O runs under locks.
Concurrent exact retries return 409 `request_in_progress` while the first transaction
is active. A retry after completion returns the original acknowledgment. A transaction-scoped
nonblocking PostgreSQL advisory claim runs before resource locks; its SHA-256-derived
64-bit scope can conservatively report busy on a hash collision, never grant duplicate execution.

Observed connected/disconnected state is independent of freshness. `fresh` requires a
current-generation cursor whose last applied batch was both received and collected
within 120 seconds. Because applied incremental batches are contiguous, that batch
confirms every device of the collector, including ones it did not mention. Agents must
apply at least one batch per collector within `freshness_seconds` from the monitoring
policy; an incremental batch with no devices is a valid keep-alive.
Older evidence is `stale`; recovery/revocation/enrollment makes prior state `unknown`
immediately. Heartbeats and replay do not refresh device evidence. Loss of the agent
does not prove physical disconnection. New complete snapshots reconcile connected
devices; historical disconnected observations preserve their original timestamps.

Each accepted snapshot writes an immutable `inventory_snapshot` event with its
typed records and completeness flag. Inventory lookups use a bounded joined result
(4001 rows); saturation fails closed as ambiguity. The serial index is reasoned,
not measured on production data. Reads use one joined serialization query or two
with pagination, verified with multiple related rows. Rows are ordered connected first,
then by most recent observation, with collector/observation key as a stable tiebreak.
Only active (not soft-deleted) inventory is a match candidate, and a soft-deleted
computer cannot report. `equipment` and `interface` are derived matches: removing the
referenced inventory row clears them (`SET NULL`) instead of blocking the delete. The UI fetches only while
open, polls every 30 seconds, and provides pagination, loading, empty and retry states.

## Retention

Celery beat runs `labs.monitoring.purge_device_observation_history` daily at 02:40
(`CELERY_TIMEZONE`). It deletes, in chunks of 5,000 rows with one short transaction
each and at most 200,000 rows per table per run:

| Data | Kept for | Setting |
| --- | --- | --- |
| Batch receipts (`DeviceObservationBatch`) | 14 days | `DEVICE_OBSERVATION_RECEIPT_RETENTION_DAYS` |
| Disconnected projections (`DeviceConnection`) | 90 days since last observation | `DEVICE_CONNECTION_DETACHED_RETENTION_DAYS` |

Connected projections and cursors are current state and are never purged. A late
duplicate after its receipt is gone is either stale (at or behind the cursor) or needs
a complete snapshot, so it cannot rewind state. `inventory_snapshot` monitoring events
follow the monitoring-event history policy and are not purged here; each is bounded to
200 devices. Partial indexes on `received_at` keep both purge scans bounded.

## Compatibility and rollout

This is an additive T2 change. Apply `0002_device_observations` (new tables, five-second
lock timeout) and `0003_equipment_serial_lookup` (`CREATE INDEX CONCURRENTLY` on
`labs_equipment.serial_number`, non-atomic, five-second lock timeout that restores the
session setting), deploy backend, then frontend, then the agent collector. Development
databases that applied the earlier unmerged iterations of these migrations
(`0002`–`0006`, `_safe` variants) must run `migrate labs 0001` before migrating again.

Rollback frontend/API first; retaining new tables and index is compatible with old
code. Migration reversal deletes new monitoring/replay data and requires an archive
and owner approval in production. Existing initial migrations and field meanings
are preserved. No automatic backfill or production deployment occurs.

The external agent must persist queued batches/sequences, retry with stable keys
and fresh signature nonces, fetch policy after enrollment, report within the freshness
window, answer `snapshot_required` with a complete snapshot, and collect real serial
and interface evidence. Vendor/product-only matching and configurable detector
rules are not implemented. Do not log raw inventories or credentials. Physical
integration requires agent source and representative devices.

## API rule review

| Rule | Result | Implementation |
| --- | --- | --- |
| VER-2 | pass | Additive endpoints and capability; legacy JSON unchanged |
| ENV-1, ERR-1/3 | pass | Standard envelopes, strict semantic validation and malformed/query errors |
| TRN-4, NAM-3/8 | pass | No slash aliases; `_at` times and `_key` external identifiers |
| REL-3, ENU-1 | pass | Named references and enum value/label objects |
| RW-6 | pass | Required UUID header, canonical hash, durable replay body/header |
| COL-1/4/5, PRF-2 | pass | Required computer filter, capped pagination, stable order and query budgets |
| ACB/BLK | not applicable | One atomic reporting action, not generic bulk operations |


## Compliance corrections and verification scope

The report workflow now lives in the existing Agents application layer and takes a
frozen command. Agent generation is an intrinsic identity property; monitoring policy
is a read-only query. Equipment locking lives in its application layer, not queries.
Reporting and invalidation both require explicit neutral ActorContext scope and
capabilities. Invalidation has a frozen input and its own atomic boundary while
remaining within the lifecycle transaction. New adapters delegate authentication
failure mapping to the central handler, including the authentication challenge.

The two signed routes opt into bounded pre-authentication body reading and strict
JSON object parsing. Duplicate keys, invalid UTF-8/surrogates, non-finite constants,
excessive depth (32), and excessive object keys (1000) are rejected. Bodies are capped
at 256 KiB, and at most 100 semantic error details are returned. Unknown queries are
rejected on reads and writes. Strings normalize to NFC, reject control characters,
and preserve nonblank whitespace; whitespace-only required identifiers are rejected.
UUIDs must be hyphenated, and collection timestamps require RFC 3339 offsets.
Request schemas are closed objects; pagination parameters and 429 responses are
explicit in generated schemas. Connection/receipt timestamps use UTC Z with six
fractional digits.

Signed policy reads use strong content ETags and conditional 304 responses. Authenticated
reads declare private/no-cache; errors and POST responses declare no-store. Vary preserves
Accept and Accept-Language. Transport header, connection and slow-client deadlines remain
responsibilities of the deployed HTTP server/gateway; no production gateway was exercised.

Migrations are `0002_device_observations` and `0003_equipment_serial_lookup` only. A
failed concurrent index build may leave an INVALID index; inspect PostgreSQL metadata
and remove only the failed index concurrently before retry. Schema rollback requires
stopping writers and exporting new data first; application-only rollback can retain
the expanded schema.


The new intake is a collection-level reporting action under ACT-1/ACB-1:
`POST /agent/device-observations/actions/report`, returning 200 acknowledgment.
It does not expose a primary snapshot resource requiring 201/Location. The earlier
uncommitted prototype route was corrected before publication, with no legacy alias.
Existing deployed routes are unchanged. Migration 0004 records the explicit ORM
boolean default False without PostgreSQL schema operations or row rewrites; reversal
is also state-only.
