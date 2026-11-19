# License checks

**Status:** implemented (phases 2 and 3 of `docs/proposals/agent-bench-devices-and-licenses.md`, D1, D2, D7, D8)
**Owner of the wire contract with the agent:** this feature + `core/agents/api/license_checks.py`;
agent side `agent/src/core/licensing/`.

A coordinator configures **license checks** in the web app. Agents on the targeted computers fetch
them, run them read-only on a schedule and report each run. The backend matches every license found
to the inventory by its serial, verifies that the license's carrier is at the reporting computer, and
keeps the inventory's expiry date, maximum version and expired status current.

## Model (`core/labs/models/resource/license/check.py`)

| Model | Meaning |
|---|---|
| `LicenseCheck` | `key` (slug, unique), `name`, `vendor`, `probe`, `extract`, `carrier` (JSON, validated), `interval_minutes` (≥ 15), `is_enabled`, `is_lab_wide`, `revision` (+1 on every change the agent receives), `preset_key` |
| `LicenseCheckTarget` | Exactly one of `room`, `station`, `bench`, `category` (equipment category) or `equipment` (a computer) |
| `LicenseCheckRun` | One reported run per `(computing, check, idempotency_key)`: revision, sequence, status, error, duration, license count, `is_applied`, content hash |
| `LicenseObservation` | Current state of one license per `(check, computing, observation_key)`: reported values, carrier (type, hardware ID, resolved unit), matched `license`, `status`, `first_seen_at`, `last_seen_at`, `removed_at` |

A computer is targeted when the check is lab-wide, or a target names the computer, its equipment
category, a bench it is assigned to, the station of that bench (or of its own station placement), or
the room of that station (or of its own room placement).

## Configuration rules (`config.py`)

The backend applies the agent's rules on write, so a coordinator sees the problem as a field error
(422) instead of a `rejected` run:

| Part | Rule |
|---|---|
| `probe` | `command` (absolute Windows `.exe` path, ≤ 16 args × 256 chars), `file` (absolute Windows path) or `registry` (HKLM, one key, named values); no `..`; `timeout_s` 1–60; `encoding` from a fixed list |
| `extract` | `format` `xml` / `json` / `text` / `values` (`values` with, and only with, registry); `fields` from the fixed target list, `product_name` required; a `text` regex must name every source group |
| `carrier` | `computer`, `device`, `dongle`, `server`, `equipment` or `mapped` (`type_map` + `default_type`, needs a `carrier_type` field); device/dongle need `hardware_id_kind` from the license-carrier kinds (today only `vector_device`; a PnP ID is for device monitoring, never a carrier) and a `carrier_id` field; equipment needs `equipment_uid` of an active unit |

Agent-only rules: allowed folders on the computer (Program Files, ProgramData, local roots) and, while
TLS to the backend is not verified, only trusted executables (presets, local settings).

**Presets** (`presets.py`, `GET /api/labs/license-checks/presets`): Vector License Client
(`Vector.LicenseClient.exe -listlicenses`, XML, `VectorLicenseId` → serial, `DeviceName` →
`vector_device` carrier, `BindingType` → carrier type).

## Staff API (Labs staff policy)

| Endpoint | Purpose |
|---|---|
| `GET /api/labs/license-checks` | Paginated; `q`, `is_enabled`. Rows add `targets`, `license_count`, `attention_count` |
| `POST /api/labs/license-checks` | **Admins.** From scratch (`key`, `name`, `probe`, `extract`, `carrier`, …) or `{preset_key, targets?, key?, name?}`. 409 `license_check_key_exists` |
| `GET/PATCH/DELETE /api/labs/license-checks/{id}` | Coordinators may change `name`, `interval_minutes`, `is_enabled`, `is_lab_wide`, `targets` (`[{kind, target_id}]`); `vendor`, `probe`, `extract`, `carrier` and delete are admin-only (403 `license_check_admin_only`) |
| `GET /api/labs/license-checks/{id}/runs` | Newest run per computer |
| `GET /api/labs/license-observations` | Paginated; `status`, `check_id`, `license_id`, `computing_id`, `is_attention_required`, `include_removed`, `q`. Each row has `license` and `inventory` (registered serial, expiry, version) for comparison |

## Agent API (signed, `ObservationSignatureAuthentication`)

| Route | Meaning |
|---|---|
| `GET /agent/license-checks` | `{"data": {"checks": [{key, revision, name, vendor, interval_minutes, probe, extract, carrier}]}}`; strong ETag, 304 when unchanged. Capability `license_checks` in `/agent/info` |
| `POST /agent/license-checks/{key}/actions/report` | UUID `Idempotency-Key`; ≤ 256 KiB; ≤ 500 licenses. Body as `agent/src/core/licensing/report.py`. Ack `{idempotency_key, sequence, result, received_at}`, `result` ∈ `applied`, `recorded`, `stale`, `outdated_revision`. 404 when the check is not enabled for this computer; 409 `idempotency_key_reused` / `request_in_progress`; 422 when `is_complete` ≠ (`status` = `ok`) or a non-`ok` run lists licenses |

The reporting computer is the identity's computing unit, never read from the body; the identity is
rechecked under its lock (`core.agents.application.report_license_check`, lock order computing →
identity → check rows, as device observations).

## Matching and effects (`application/report.py`)

1. **License** by `license_serial` = `License.serial_number` (case-insensitive, live licenses; vendor
   name breaks a tie). Without a serial: the one license of that product assigned to the carrier or the
   computer. None → `unregistered`, several → `ambiguous`.
2. **Carrier unit** `U`: `computer`/`server` → the computer; `equipment` → the configured unit;
   `device`/`dongle` → the unit with that registered `EquipmentHardwareId` (e.g. `vector_device`
   `007113-585343`; independent of the unit's PnP ID). Not found → `carrier_unlinked`.
3. **At the computer**: `U` is the computer, is on the computer's bench, or the computer's own agent
   reports it connected (fresh `pnp` observation). Otherwise `carrier_not_at_computer`.
4. **Assigned there**: the license has an active `LicenseAssignment` to `U` or the computer; to another
   unit → `carrier_mismatch`; none → `unassigned`. Nothing is reassigned automatically (D8).
5. **Matched** (D1): a different `expires_at` → `License.expiry_date`, a reported different
   `max_version` → `License.max_version`, each with a `ResourceChangeLog` entry (no user; metadata
   names the check, computer, agent and observation). A past expiry records `expired` (never over
   `revoked` / `suspended`); a renewed expiry ends an `expired` status this feature recorded
   (back to `assigned` or `available`). Identical values write nothing.

Only `ok` runs with the current revision and a newer sequence change observations; licenses a complete
run no longer lists get `removed_at`. Raw tool output, license keys, contract and activation IDs are
never sent or stored.

## Alerts (`application/alerts.py`)

When a found license first needs attention, comes back after being gone, or its reason changes,
the check's owner (creator, else last editor) gets one in-app warning notification (kept 14 days,
pushed after commit). Matched licenses and repeated runs with the same outcome never notify. The
web app shows the open count on Licenses → Found on lab hardware.

## Not done

- Expected licenses per check (`LicenseCheckLicense`, "missing" when no run reports them).
- Retention of `LicenseCheckRun` history (30 days) as a scheduled task.
- Backend expiry notifications (the agent shows tray warnings 30 days ahead, D4).
