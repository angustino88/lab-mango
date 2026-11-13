# Environment telemetry: real-time room and station power, temperature, humidity

> Status: **Proposed** (not approved, not implemented) · Risk tier: **T2** (new migrations and constraints,
> new device and operator API contracts, device authn, object-scoped authz, background jobs, cross-feature
> dependencies, retention) · Owner decision required before implementation.

IoT nodes in rooms and on stations push power, temperature and humidity samples. The backend stores them,
serves current values and history, and pushes changes to the React frontend in real time.

---

## 1. Repository facts (verified 2026-11-13)

What exists today. Everything else in this document is **Proposed**.

| Area | Verified state | Evidence |
|---|---|---|
| Room environment model | `RoomObservation`: `room`, `observed_at`, `source` (free text), `temperature_c`, `humidity_percent`, `power_usage_w`. DB checks: at least one value, temperature ≥ -273.15, humidity 0–100. Index `(room, -observed_at)`. | `core/labs/models/resource/location/room_observation.py:9-65` |
| Room environment API | `GET/POST /api/labs/rooms/{room_id}/observations`, paginated list, single-row create | `core/labs/features/locations/rooms/api/urls.py:22-24`, `.../rooms/api/views.py:169-194` |
| Room write path | `record_room_observation` does `full_clean()` + `save()` per row | `core/labs/features/locations/rooms/application/services.py:127-133` |
| Station environment data | **None.** `Station` has only design capacities (`power_capacity_w`, `power_reserved_w`, `cooling_capacity_w`), no measured values | `core/labs/models/resource/location/station.py:81-83` |
| Device identity | `AgentIdentity` with Ed25519 key, enrollment grants, revoke/decommission, signed `/agent/...` requests (`X-Agent-Id/Timestamp/Nonce/Signature`). **Bound to `labs.Equipment` only.** | `core/agents/models/agent_identity.py:30-35`, `core/agents/api/authentication.py:43-76` |
| Device ingest endpoints | heartbeat, equipment activity, session logs, booking actions. **No environment/telemetry endpoint.** | `core/agents/api/urls.py:22-58` |
| Generic agent events | `MonitoringEvent` (`METRIC_REPORTED` action, JSON payload) bound to a *computer* (`Equipment`) | `core/labs/models/monitoring/monitoring.py:8-36` |
| Real-time push | Django Channels + Redis pub/sub; `publish_service._publish(channel, data)`; WS routes registered by `register_route`. No room/station telemetry channel. | `core/websocket/publish_service.py:27-32`, `core/websocket/router.py:15-26`, `pyproject.toml:10-16` |

**Answer to "is it supported now?"** Partially. Rooms have a storage model and a manual HTTP API for the
three measurements. Stations have nothing. There is no node identity for room/station sensors, no ingest
path for nodes, no idempotency, no history aggregation, no retention, and no real-time push of this data.

### Drift found (report only; not changed by this proposal)

| Severity | Finding | Location |
|---|---|---|
| High | Any authenticated user or API key can create room observations; not object-scoped (AGENTS.md rule 5) | `core/common/api/command_views.py:36` via `core/labs/features/locations/api/views.py:7` and `.../rooms/api/views.py:169` |
| Medium | `RoomObservation` has no idempotency key; a node retrying a POST creates duplicates (write-safety §3) | `core/labs/models/resource/location/room_observation.py:9-29` |
| Medium | Monitoring WS dashboard admits every authenticated user; bench check is existence only, not object authz | `core/websocket/features/monitoring_dashboard/handler.py:17-27` |
| Low | WS messages are flat (`{"type", "bench_id", ...}`), not `{"type", "data"}` (STM-3) | `core/websocket/publish_service.py:44-53` |
| Low | `room_observations` selector has no time window; reads are bounded only by pagination | `core/labs/features/locations/rooms/queries/selectors.py:55-57` |

---

## 2. Requirements and quality attributes

**Functional**
- F1 A node measures one *scope*: a room or a station. A scope may have several nodes.
- F2 Nodes push samples with `observed_at`, any subset of `temperature_c`, `humidity_percent`, `power_w`.
- F3 Operators see the latest value per scope, history over a time window, and live updates.
- F4 Operators enroll, bind, rebind, revoke nodes and configure RS485 channels. A node never chooses its scope.
- F5 Node connectivity (online/stale/offline) is visible.

**Quality attributes (targets to confirm, see §10)**
- Volume: 500 nodes × 1 sample / 10 s ≈ 4.3 M rows/day raw.
- Ingest p95 < 200 ms per batch of ≤ 500 samples; live update to browser < 2 s after accept.
- At-least-once delivery from nodes; zero duplicates stored.
- Raw retention 30 days; aggregates kept 2 years.

**Out of scope for v1**: threshold alerts, energy billing / expense linkage, MQTT transport, control
commands to nodes. §9 shows where each attaches later.

### 2.1 Field topologies (stated by owner 2026-11-13)

Both are supported at the same time, even in the same room.

**T-A: PC mode.** The station node plugs into a PC on the station (USB serial). The PC's existing Lab Mango
agent forwards the data.

**T-B: Master mode.** Station nodes join the room master over Wi-Fi. The master forwards for the room and may
carry room-level sensors itself.

```mermaid
flowchart LR
  subgraph "Station A (T-A: PC mode)"
    SA[RS485 sensors] -- RS485 --> NA[Station node]
    NA -- USB serial --> PC[Station PC<br/>Lab Mango agent<br/>+ telemetry bridge]
  end
  subgraph "Room 3 (T-B: master mode)"
    SB[RS485 sensors] -- RS485 --> NB[Station node<br/>Station B]
    SC[RS485 sensors] -- RS485 --> NC[Station node<br/>Station C]
    NB -- Wi-Fi --> M[Room node / master]
    NC -- Wi-Fi --> M
    RS[Room sensors<br/>temp, humidity, main meter] -- RS485 --> M
  end
  PC -- signed HTTPS --> API[Lab Mango backend]
  M -- signed HTTPS --> API
```

Consequences for the design:
- One abstraction covers both: a **gateway** is any signed agent that forwards node data. Kinds:
  `room_master` (scope = one room) and `station_pc` (scope = one station). Only gateways hold server
  credentials (`AgentIdentity`). Station nodes never reach the server in either topology.
- The PC gateway reuses the PC's **existing** `AgentIdentity` (bound to that PC's `Equipment`,
  `core/agents/models/agent_identity.py:31`). No second credential on the PC.
- A station node is identified by a factory **device UID** (MAC or chip ID). The server, not the firmware,
  decides which station it belongs to. Moving a node from PC mode to master mode, or swapping it, needs no
  reflash and keeps the station's history.
- RS485 sensors are **channels** of a node: a Modbus slave address plus a sensor profile (register map),
  configured in Lab Mango (D5).

---

## 3. Key decisions

### D1 Device identity: gateway (master or station PC) = signed agent; station node = registered device behind it (recommended)

| Option | For | Against |
|---|---|---|
| **A. Master and station nodes are `Equipment` (category `environment_gateway` / `environment_node`). Only gateways hold an `AgentIdentity` (the master's own, or the station PC's existing one). Station nodes are `TelemetryDevice` rows keyed by a unique `device_uid`.** (recommended) | No change to `core.agents`; one credential per room (master) or none new (PC mode); inventory/lifecycle/procurement of nodes come free; swapping a node is a server-side rebind | Server trusts the gateway to report honestly for nodes in its scope (room or station) |
| B. Every station node gets its own `AgentIdentity` and the master relays signed envelopes | End-to-end proof per node | Ed25519 + clock + key storage on every node; master can't batch-sign; much more firmware |
| C. Station nodes are not modeled; master reports "station id" directly | Simplest | Firmware decides the scope (breaks F4); rewiring needs reflash; no per-node health |

Constraint: the master signs with Ed25519 (ESP32-class MCUs support it via libsodium / mbedTLS;
**not verified** on the target hardware). Station-node ↔ master trust on Wi-Fi is a firmware concern;
the backend stores each node's key fingerprint so the master can enforce it (§5.0, Q7).

### D5 Sensor configuration: defined in Lab Mango, discovered by the node (recommended)

| Option | For | Against |
|---|---|---|
| **A. Lab Mango is the source of truth for *what is where and what it measures*; nodes scan the RS485 bus and report; staff confirm the profile** (recommended) | Swap/move without reflash; one place to audit; channels map to metrics with DB constraints; works identically in both topologies | Needs config sync (`GET /agent/telemetry/config`) and a profile library |
| B. Configured only in node firmware/local web UI | No server work | Server can't validate what a reading means; each swap is a field visit; config drifts per node |
| C. Fully automatic (node guesses sensor model from scan) | Zero touch | Modbus has no standard device-ID; wrong register map = silently wrong data |

Split of responsibility:

| Configured in Lab Mango | Stays on the device |
|---|---|
| Device registry, role, claim, fingerprint | Wi-Fi credentials, master SSID (provisioned locally via setup AP/BLE) |
| Gateway → room/station, node → station | Firmware, OTA (out of scope v1) |
| Channels: Modbus address → profile → metric, enabled | Serial driver, polling loop, retry |
| Sensor profiles (register map, baud, parity, scale) | Node ↔ gateway pairing key |
| Sample/push interval | Clock sync from gateway |

### D2 Transport: signed HTTPS batch push now; MQTT later only if measured need

| Option | For | Against |
|---|---|---|
| **A. `POST /agent/telemetry/samples/bulk`, signed, batched** (recommended) | Reuses auth/throttling/observability; no new infra; works through the existing proxy | One TLS request per batch; ~1–10 s latency floor depending on push interval |
| B. MQTT broker (e.g. EMQX/Mosquitto) + bridge worker | Low overhead for thousands of constrained nodes; QoS 1 | New service, new dependency (rule 7), second auth scheme, bridge must still call the same ingest command |
| C. Node holds a WebSocket to the backend | Lowest latency | Long-lived connections per node in ASGI workers; reconnection storms; signing per message not designed |

"Real time" is defined end to end: node pushes every `push_interval_s` (default 10 s, a batch may hold one
sample), backend publishes on commit, browser receives within ~1 s. Option B can be added later behind the
same application command (`record_telemetry_batch`) without changing storage or the operator API.

### D3 Storage: new wide raw table + rollups + latest-value row; keep `RoomObservation` as is

| Option | For | Against |
|---|---|---|
| **A. New `TelemetrySample` (wide row) + `TelemetryRollup` + `TelemetryLatest`** (recommended) | Bounded queries; cheap dashboard reads; retention without touching rollups; existing room API unchanged (rule 1) | Two places for room environment data until owner decides the fate of `RoomObservation` (Q2) |
| B. Extend `RoomObservation` with `station` FK, node, sample id | One table | Changes a deployed model and API; manual and high-volume data mixed; retention would delete manual data |
| C. Narrow EAV `(scope, metric, value)` | Add metrics without migrations | 3× rows, weak DB typing, constraints per metric impossible |
| D. TimescaleDB hypertable / native partitioning | Best at very high volume | New extension/infra (rule 7); Django migrations need raw SQL |

Escalation trigger for D: raw table > ~200 M rows or retention delete > 5 min. Until then a BRIN index on
`observed_at` and batched deletes are enough (**not verified** with a load test; see §8).

### D4 Scope modeling: two nullable FKs with exactly-one DB check (not GenericForeignKey)

Keeps real foreign keys (`PROTECT`) and lets PostgreSQL enforce "room xor station". A station's room is
derivable, so room dashboards can optionally include station nodes in a query; they are not double-stored.

---

## 4. Ownership and placement

New feature `core/labs/features/telemetry/` following `docs/architecture/feature-template.md`.
Models in `core/labs/models/telemetry/` per `docs/conventions/django-models.md` (to verify against that
document during model-design).

| Concept | Owner | Used through |
|---|---|---|
| `TelemetryDevice`, `GatewayScopeBinding`, `NodeStationBinding`, `SensorProfile`, `TelemetryChannel`, `TelemetrySample`, `TelemetryRollup`, `TelemetryLatest`, `TelemetryNodeHealth` | telemetry (new) | `telemetry/public.py`, `telemetry/contracts.py` |
| Room, Station existence, view policy | locations | `core/labs/features/locations/public.py` |
| Node/master equipment, `environment_gateway` / `environment_node` categories | equipment | `core/labs/features/equipment/public.py` |
| Node identity, signature verification | `core.agents` | `core/agents/public.py` (`require_active_agent_identity`) |
| WS channel publishing | `core.websocket` | `publish_service` (new `publish_telemetry_update`) |

Boundary enforcement: add the telemetry package to the existing import contracts checked by
`tests/architecture/test_import_boundaries.py` (no import of another feature's `models`/`application`
outside `public.py`/`contracts.py`).

```mermaid
flowchart LR
  SN[Station nodes<br/>RS485 sensors] -- Wi-Fi --> N[Master node<br/>one per room]
  N -- "GET /agent/telemetry/config" --> AG
  N -- "signed HTTPS<br/>POST /agent/telemetry/samples/bulk" --> AG[core.agents<br/>signature auth]
  AG --> CMD[telemetry.application<br/>record_telemetry_batch]
  CMD -- resolve room + station bindings --> B[(GatewayScopeBinding<br/>NodeStationBinding)]
  CMD -- INSERT ... ON CONFLICT DO NOTHING --> S[(TelemetrySample)]
  CMD -- conditional upsert --> L[(TelemetryLatest)]
  CMD -- on_commit --> P[publish_service<br/>Redis pub/sub]
  P --> WS[ws/telemetry/rooms/:id<br/>ws/telemetry/stations/:id]
  WS --> FE[React dashboard]
  CEL[Celery beat] --> R[(TelemetryRollup 1m / 1h)]
  CEL -- batched delete > 30 d --> S
  CEL -- mark stale/offline --> H[(TelemetryNodeHealth)]
  FE -- "GET /api/labs/telemetry/..." --> Q[telemetry.queries]
  Q --> L & R & S
```

---

## 5. Proposed models

### 5.0 `TelemetryDevice`: the hardware identity of a master or station node

| Field | Type | Notes |
|---|---|---|
| `equipment` | OneToOne `labs.Equipment`, PROTECT, null | null while `discovered` (not yet claimed into inventory) |
| `role` | char: `room_master` / `station_pc` / `station_node` | `station_pc` rows point at the PC's existing Equipment |
| `device_uid` | char(64), **unique** | factory ID: MAC or chip ID, normalized uppercase. `Equipment.mac_address` is not unique (`equipment.py:144`), so uniqueness lives here |
| `key_fingerprint` | char(128), blank | node's local key, reported by master on discovery, confirmed at claim (QR label) |
| `state` | `discovered` → `claimed` → `retired` | own state machine, not equipment lifecycle (rule 2) |
| `reported_by` | FK `TelemetryDevice` (gateway), null | the master that last saw it |
| `firmware_version`, `config_version_applied` | char, int | reported by master |
| `first_seen_at`, `last_seen_at` | datetime | |

DB: `CHECK (state = 'discovered' OR equipment_id IS NOT NULL)`.

### 5.1 Bindings: gateway → scope, station node → station

`GatewayScopeBinding`: `gateway` (FK `TelemetryDevice`), `room` (FK `labs.Room`, null), `station`
(FK `labs.Station`, null), `valid_from`, `valid_to`.
- `CHECK ((room_id IS NULL) <> (station_id IS NULL))`; `room_master` ⇒ room set, `station_pc` ⇒ station set
  (CHECK on a denormalized `gateway_role` column, or application check).
- Exclusion on `gateway` range — a gateway has one scope at a time.
- Exclusion on `room` range (partial `WHERE room_id IS NOT NULL`) — **one master per room** at a time.
- Several PCs may serve the same station; duplicates from two forwarders are removed by `UNIQUE (node, sample_id)`.
- PC gateway scope is set **explicitly**, not derived live from the PC's bench assignment
  (`EquipmentAssignment` → `Bench.station_slot` → `StationSlot.station`). Deriving it would silently move data
  to another station when someone reassigns the PC. The UI pre-fills the station from that chain and warns
  when they disagree.

`NodeStationBinding`: `node` (FK `TelemetryDevice`), `station` (FK `labs.Station`), `label`, `valid_from`, `valid_to`.
- Exclusion on `node` range — a node is on one station at a time.
- Exclusion on `station` range — one node per station (relax if a station gets two, Q8).
- The node binding does **not** name a gateway. Which gateway forwards is a transport fact; switching T-A ↔ T-B
  needs no rebind.

**Ingest authorization rule** (application, under `select_for_update` on the gateway's binding): a gateway may
forward a sample from node *n* at time *t* only if *n*'s station binding at *t* is inside the gateway's scope:
`room_master` → `station.room_id == scope.room_id`; `station_pc` → `station_id == scope.station_id`.

Room-level sensors wired to the master are channels of the `room_master` device, scoped to its room. A PC
gateway has no own channels in v1.

All exclusion constraints use `btree_gist`, already installed by `core/labs/migrations/0001_initial.py`.
Common: `CHECK (valid_to IS NULL OR valid_to > valid_from)`; audit via `TimeStampedModel`, `UserStampedModel`.

### 5.1b `SensorProfile` and `TelemetryChannel`: RS485 configuration

`SensorProfile` (reference data, staff-managed): `key` (e.g. `eastron_sdm120`, `sht30_modbus`), `name`,
`register_map` JSON (per metric: function code, register, word count, data type, scale, unit), `baud_rate`,
`parity`, `stop_bits`. Validated against a JSON schema on write.

`TelemetryChannel`: `device` (FK `TelemetryDevice`), `bus_address` (1–247, Modbus slave ID), `profile`
(FK `SensorProfile`), `metric` (`temperature_c` / `humidity_percent` / `power_w`), `enabled`.
- `UNIQUE (device, bus_address, metric)`; `CHECK (bus_address BETWEEN 1 AND 247)`.
- One device's channels on the same bus must share serial settings (application check at config build).

`config_version` (int, on the gateway's `TelemetryDevice`) increments in the same transaction as any change to
that room's bindings or channels (`select_for_update` on the gateway row), so the master knows when to re-pull.

### 5.1c Node and gateway design (firmware/agent, for the device team)

One station-node hardware and firmware for both topologies; the uplink is chosen at provisioning.

| Device | Hardware (suggested) | Responsibilities | Holds server credential? |
|---|---|---|---|
| **Station node** | MCU with Wi-Fi + USB (ESP32-S3 class), RS485 transceiver, optional local temp/humidity | Poll RS485 channels per config; stamp `sample_id` (UUID) and `seq`; ring buffer (≥ 1 h); send frames up the uplink; report bus scan and firmware version | No |
| **Room node (master)** | Same MCU class or small Linux SBC; Wi-Fi AP/STA, Ethernet preferred for uplink; RS485 for room sensors; secure key storage | Run room SSID or join lab Wi-Fi; authenticate nodes (pairing key, Q7); time source for nodes; buffer (≥ 24 h); batch + sign to backend; pull config and fan out to nodes | Yes (`AgentIdentity`) |
| **PC telemetry bridge** | Software module in the existing PC agent ("Collectors", `docs/agent-platform/device-design.md` §2) | Read node frames over USB serial; same buffering/batching/config pull as master, scoped to its station; no access to the agent's private key outside the backend client | Uses the PC's existing identity |

**Node frame** (identical on Wi-Fi and USB, so the gateways share one parser):

```json
{"v": 1, "device_uid": "A4:CF:12:9B:00:21", "seq": 18233, "sample_id": "6f1c…",
 "observed_at": "2026-11-13T09:00:10Z", "clock": "synced",
 "config_version": 17,
 "readings": [{"bus_address": 1, "metric": "power_w", "value": "1830.5"},
              {"bus_address": 2, "metric": "temperature_c", "value": "22.40"}]}
```

- `clock: "unsynced"` + `uptime_ms` instead of `observed_at` when the node has no time yet; the gateway
  converts using its own clock and marks the sample `quality = suspect` if the offset is uncertain.
- The gateway acknowledges by `seq`; the node deletes from its buffer only after ack.
- A reading for a channel not in the node's config is dropped at the gateway and counted, never forwarded.

Node lifecycle as seen by the backend: `discovered` → `claimed` (+ station binding) → `retired`. Connectivity
(`online/stale/offline/unknown`) is separate (§5.5).

### 5.2 `TelemetrySample`: raw, append-only

| Field | Type | Notes |
|---|---|---|
| `id` | BigAutoField | |
| `node` | FK `TelemetryDevice`, PROTECT | station node, or the gateway for room sensors |
| `gateway` | FK `TelemetryDevice`, PROTECT | master or PC that forwarded it (first accepted copy) |
| `node_binding` | FK `NodeStationBinding`, null | scope resolved server-side at `observed_at`; null for room sensors |
| `room` | FK `labs.Room`, null | denormalized from binding for indexed reads |
| `station` | FK `labs.Station`, null | denormalized from binding |
| `sample_id` | UUID | generated by node; idempotency key |
| `observed_at` | datetime | node clock, UTC |
| `received_at` | datetime | server clock |
| `temperature_c` | Decimal(6,2), null | |
| `humidity_percent` | Decimal(5,2), null | |
| `power_w` | Decimal(10,2), null | instantaneous active power |
| `quality` | char(16), default `ok` | `ok` / `suspect` (clock corrected, sensor flag) |

DB constraints (same physical rules as `RoomObservation`): at least one value; temperature ≥ -273.15;
humidity 0–100; `power_w ≥ 0`; exactly one of room/station; `UNIQUE (node, sample_id)`.

Indexes: `(room, observed_at DESC)` partial where room not null; `(station, observed_at DESC)` partial;
BRIN on `observed_at` for retention deletes. No `full_clean()` per row on ingest; DB constraints are the
guard (same reasoning as `core/labs/models/base/agent_report.py:27-38`), serializer validates shape first.

### 5.3 `TelemetryRollup`: aggregates for charts

`scope (room|station)`, `bucket_start`, `resolution` (`1m`, `1h`), and for each metric `min`, `max`, `avg`,
`count`. `UNIQUE (room, station, resolution, bucket_start)` with `NULLS NOT DISTINCT` (PostgreSQL 15+; CI runs
`postgres:16` per `.github/workflows/ci.yml:22`, production version not verified) or two partial unique indexes. Recomputed idempotently by upsert.

### 5.4 `TelemetryLatest`: one row per scope (and per node) for dashboards

`scope`, `node`, latest `observed_at` and values. `UNIQUE (node)`. Room/station "current" values are a
read over the scope's nodes (few rows). Keeps the dashboard off the raw table.

### 5.5 `TelemetryNodeHealth`: connectivity, a separate state machine

`node` (unique), `connectivity` ∈ {`online`, `stale`, `offline`}, `last_sample_at`, `changed_at`.
This is **not** the equipment lifecycle status and **not** computing live activity (AGENTS.md rule 2).

```mermaid
stateDiagram-v2
  [*] --> offline
  offline --> online: sample accepted
  online --> stale: no sample for 3 x push_interval
  stale --> online: sample accepted
  stale --> offline: no sample for 10 min
  online --> offline: binding ended / identity revoked
```

---

## 6. Proposed API

All operator responses use the envelope and error rules in `docs/api/response-standard.md`.

### 6.1 Device ingest (signed, `core.agents` auth)

Only gateways call these (room master or station PC; same endpoints, scope differs). Identity comes from the
signature; the body never carries a room or station id. In the examples below "master" means either gateway kind.

**Config pull** — `GET /agent/telemetry/config` with `If-None-Match: "<config_version>"` → `304` or `200`:

```json
{"data": {
  "config_version": 17, "room_id": 3, "push_interval_s": 10,
  "nodes": [
    {"device_uid": "A4:CF:12:9B:00:21", "key_fingerprint": "…", "station_label": "Station A",
     "channels": [
       {"bus_address": 1, "metric": "power_w", "profile": "eastron_sdm120"},
       {"bus_address": 2, "metric": "temperature_c", "profile": "sht30_modbus"},
       {"bus_address": 2, "metric": "humidity_percent", "profile": "sht30_modbus"}]}],
  "gateway_channels": [],
  "profiles": {"eastron_sdm120": {"baud_rate": 9600, "parity": "N", "register_map": {…}}}
}}
```

The master pushes each node's channel list to that node over Wi-Fi. Nodes not in `nodes` are ignored by
the master except for discovery reports. The config never contains server credentials. The master polls
every 60 s and also when an ingest response carries a newer `config_version`.

**Discovery** — `POST /agent/telemetry/discoveries` `{"devices": [{"device_uid", "key_fingerprint",
"firmware_version", "rs485_scan": [1, 2]}]}`: idempotent upsert of `discovered` devices (`UNIQUE device_uid`).
A UID already claimed by another room's gateway is recorded but not reassigned (operator sees a conflict).

**Ingest** — `POST /agent/telemetry/samples/bulk` — BLK-1/2/3, partial mode, max 500 operations, max 256 KiB body.

```json
{
  "mode": "partial",
  "operations": [
    {"data": {"device_uid": "A4:CF:12:9B:00:21", "sample_id": "6f1c…",
              "observed_at": "2026-11-13T09:00:10Z", "config_version": 17,
              "temperature_c": "22.40", "humidity_percent": "41.0", "power_w": "1830.5"}}
  ]
}
```

`device_uid` omitted = the master's own room sensors. `sample_id` is generated where the reading is taken
(station node) so a retry from node → master → server stays deduplicated end to end.
`200` with per-item result in `data`: `accepted` | `duplicate` | `rejected` (+ ERR-1 error object), and the
current `config_version`. `Idempotency-Key` header replays the original response for the whole batch.

Validation and rejection:
- `observed_at` more than 2 min in the future, or older than raw retention → `rejected` (`observed_at_out_of_range`).
- Unknown/unclaimed `device_uid`, or node not bound to a station in **this master's room** at `observed_at`
  → `rejected` (`node_not_bound`). Never silently re-attributed.
- Master with no active room binding → `409` for the whole batch (`gateway_not_bound`).
- Revoked / decommissioned identity → `401` for the whole request (existing behavior).
- The master buffers rejected-retryable and unsent samples per `docs/agent-platform/device-design.md` §5.

### 6.2 Operator read

| Method and path | Purpose | Bounds |
|---|---|---|
| `GET /api/labs/rooms/{room_id}/telemetry/latest` | current values per node in the room (`include_stations=true` adds the room's station nodes) | ≤ 200 nodes |
| `GET /api/labs/stations/{station_id}/telemetry/latest` | current values for the station | |
| `GET /api/labs/rooms/{room_id}/telemetry?from=&to=&resolution=raw\|1m\|1h&metrics=` | history series | raw ≤ 24 h, 1m ≤ 31 d, 1h ≤ 2 y; else `422` |
| `GET /api/labs/stations/{station_id}/telemetry?…` | same for stations | same |

### 6.3 Operator write: commissioning and configuration

| Method and path | Purpose |
|---|---|
| `GET /api/labs/telemetry/devices?state=discovered&room_id=` | devices with state, binding, connectivity, config version applied |
| `POST /api/labs/telemetry/gateways` | register a gateway: `room_master` (new Equipment) or `station_pc` (existing PC Equipment with an active agent) |
| `POST /api/labs/telemetry/gateways/{device_id}/actions/bind-scope` | bind to a room (master) or station (PC); ends previous binding |
| `POST /api/labs/telemetry/devices/{device_id}/actions/claim` | `discovered` → `claimed`: confirm fingerprint, create or link Equipment |
| `POST /api/labs/telemetry/devices/{device_id}/actions/bind-station` | bind station node (must be inside a gateway's scope to be accepted at ingest) (ends previous binding) |
| `POST /api/labs/telemetry/devices/{device_id}/actions/unbind` | end the current binding (node removed or broken) |
| `GET/POST/PATCH/DELETE /api/labs/telemetry/devices/{device_id}/channels` | RS485 channels |
| `GET/POST /api/labs/telemetry/sensor-profiles` | register-map reference data |

Master enrollment itself stays on the existing `POST /api/agents`, `/enrollment-grants`, `/agent/enrollments`.

### 6.5 Commissioning flow (how a station gets its node)

```mermaid
sequenceDiagram
  actor Tech as Lab staff
  participant UI as Lab Mango UI
  participant API as Backend
  participant M as Master node (room)
  participant N as Station node
  Note over Tech,M: Once per room
  Tech->>UI: Register master as Equipment, create enrollment grant
  Tech->>M: Enter grant code (setup AP / BLE)
  M->>API: POST /agent/enrollments (existing)
  Tech->>UI: Bind master to Room 3
  Note over Tech,N: Once per station
  Tech->>N: Wire RS485 sensors, provision Wi-Fi to master's SSID
  N->>M: Hello (device_uid, key fingerprint, RS485 scan)
  M->>API: POST /agent/telemetry/discoveries
  Tech->>UI: Scan node QR label at Station A
  UI->>API: claim (fingerprint must match) + bind-station(Station A)
  API->>API: config_version 16 → 17
  Tech->>UI: Pick sensor profiles per bus address (prefilled from RS485 scan)
  M->>API: GET /agent/telemetry/config (If-None-Match 16)
  API-->>M: 200 config v17
  M->>N: Channel list
  N->>M: Samples (sample_id per reading)
  M->>API: POST /agent/telemetry/samples/bulk
  API-->>UI: ws/telemetry/stations/{id} live values
```

**PC mode (T-A)** differs only in the first part: no new hardware enrollment. Staff enable the telemetry
bridge on the station PC (already enrolled), register it as a `station_pc` gateway, and bind it to the station
(pre-filled from the PC's bench assignment). Plugging the node into USB triggers the same discovery → claim →
bind-station → config steps.

**Switching a station from PC mode to master mode**: unplug from PC, provision the node onto the room Wi-Fi.
No server change; the station binding is unchanged and the master's scope already covers the station.

Swapping a broken node: unbind old → new node is discovered → claim + bind-station. History stays on the
station because samples carry the binding. Moving a station to another room requires rebinding its node under
the new room's master (the old master's samples for it start being rejected).

### 6.4 Real-time push

| WS route | Channel |
|---|---|
| `ws/telemetry/rooms/{room_id}` | `ws:telemetry:room:{room_id}` |
| `ws/telemetry/stations/{station_id}` | `ws:telemetry:station:{station_id}` |

Message (STM-3): `{"type": "telemetry.latest", "data": {"scope": {"type": "room", "id": 7}, "node_id": 42,
"observed_at": "…", "temperature_c": "22.40", "humidity_percent": "41.0", "power_w": "1830.5"}}` and
`{"type": "telemetry.connectivity", "data": {…}}`. Published in `transaction.on_commit`, one message per
node per batch (the newest sample), so a 500-sample backfill sends one message, not 500. Messages are
best-effort; on (re)connect the client calls `…/telemetry/latest` (documented per STM-4). Heartbeat every 30 s.

---

## 7. Write safety and authorization

| Write path | Race guard | Safe to run twice |
|---|---|---|
| `record_telemetry_batch` | `UNIQUE (node, sample_id)` + `bulk_create(ignore_conflicts=True)`; binding resolved by exclusion-constrained range lookup | Yes: duplicates reported as `duplicate`, no extra rows |
| `TelemetryLatest` upsert | `INSERT … ON CONFLICT (node) DO UPDATE … WHERE excluded.observed_at > telemetry_latest.observed_at` | Yes: older or equal samples never overwrite newer |
| Bind node | `select_for_update` on the node's open binding + exclusion constraint | Same request twice: second sees identical open binding and returns it |
| Rollup task | upsert on `(scope, resolution, bucket_start)`; recompute from raw | Yes |
| Retention task | delete in batches of 10 k by `observed_at < cutoff` | Yes |
| Connectivity task | conditional update `WHERE connectivity = old AND last_sample_at = seen` | Yes |

Authorization (deny-by-default, object-scoped):
- Device writes: signed master identity → its `TelemetryDevice` → active room binding → only nodes bound to
  stations in that room. A compromised master can at worst forge data for its own room.
- Connectivity has two layers: master (from agent heartbeat) and each node (last sample via the master).
  When the master is offline, its nodes are `unknown`, not `offline` (matches the repo rule that missing
  telemetry is unknown, `core/labs/features/equipment/queries/summaries.py:19`).
- Operator reads: the caller must be allowed to view the room/station, via a locations policy exposed in
  `locations/public.py`. **No such object-level policy exists today** (drift table §1), so the owner must
  decide the rule (Q3). WS handshakes apply the same check, not "exists".
- Binding management: lab staff only (`LABS_STAFF_ACCESS`, already used at
  `core/labs/features/locations/api/reference_data.py:24`).

---

## 8. Verification plan (when implemented)

- Model tests: every DB constraint rejects bad rows at the database (bypass `full_clean`).
- Ingest: duplicate batch, duplicate sample in one batch, out-of-order samples, unbound node, revoked node,
  future timestamp, 501 operations, oversized body.
- Concurrency: two concurrent batches with overlapping sample ids; latest never regresses.
- Query budgets: `latest` endpoint constant queries for 1 vs 200 nodes; history endpoint ≤ 3 queries.
- WS: unauthorized user closed with 4003; message shape STM-3; one message per node per batch.
- Load test before approval of the D3 escalation trigger: 4.3 M rows/day for 30 days, measure history p95
  and retention delete duration.
- Quality gates per `docs/ai-team/quality-gates.md`; regenerate `openapi/` in the same change.

---

## 9. Later extensions (not in v1)

| Extension | Attaches at |
|---|---|
| Threshold alerts (temp/humidity bands; `power_w > Station.power_capacity_w`) | Rule table in telemetry; evaluated in `record_telemetry_batch` after commit; notify via `core.websocket` user notifications |
| Energy (`energy_wh` monotonic counter) for expense/billing | New nullable column + rollup delta; money logic is its own T2 change |
| MQTT transport | Bridge worker calling `telemetry.public.record_telemetry_batch` |
| Long-range storage | TimescaleDB or native partitioning (D3 option D) |

---

## 10. Assumptions and open questions for the owner

Assumptions (not verified): node hardware can do Ed25519 and HTTPS; ~500 nodes at 10 s; production
PostgreSQL ≥ 15 (CI uses 16).

| # | Question | Recommended default |
|---|---|---|
| Q1 | Approve node-as-Equipment (D1-A)? | Yes |
| Q2 | Fate of `RoomObservation` and `/rooms/{id}/observations`: keep for manual entries, or deprecate after telemetry ships? | Keep in v1; decide after adoption |
| Q3 | Who may view a room's/station's telemetry? | Same users who can view the room; staff for all |
| Q4 | Push interval, raw retention, rollup retention | 10 s; 30 d; 1m for 90 d, 1h for 2 y |
| Q5 | Is `power_w` per node real power at the PDU/meter, and is energy (kWh) needed for expenses? | `power_w` only in v1 |
| Q6 | Fix the drift items in §1 (esp. room observation write authz) as separate tasks? | Yes, separate T2 task for authz |
| Q7 | Node ↔ master link security: dedicated per-room WPA2 SSID only, or also a per-node key checked by the master against `key_fingerprint`? | Both |
| Q8 | Exactly one node per station, or allow several (e.g. two PDUs)? | One; drop the station exclusion if needed |
| Q9 | Which RS485 sensor models are used (needed to write the first `SensorProfile` register maps)? | Owner to list |
| Q10 | Should RS485 config live on the server (pulled by master) or stay in firmware? | Server (D5-A), so swaps need no reflash |
| Q11 | PC mode: does the station PC always run the Lab Mango agent? If a station has no enrolled PC, should the node push directly over Wi-Fi with its own identity (a third topology)? | Not in v1; use master mode |
| Q12 | PC bridge ships in the existing agent (needs `docs/agent-platform/device-design.md` update and agent release) or as a separate service? | Existing agent, as a collector |
