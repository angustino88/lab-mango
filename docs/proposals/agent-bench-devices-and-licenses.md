# Agent: monitored devices by registered PnP ID, and configurable license checks

**Status:** Approved by the owner (2026-11-18, D1–D9); phase 1 implemented
**Risk tier:** T2 (public agent API, migrations, matching semantics, license data written from an integration)
**Companions:** [device design](../agent-platform/device-design.md), [backend agent API](../agent-platform/backend-api.md),
[device connections](../../core/labs/features/monitoring/docs/device-connections.md),
[licenses spec](../../core/labs/features/licenses/docs/spec.md); agent side: `agent/docs/design/bench-device-and-license-monitoring.md`

## 1. Problem

1. **Matching on a human field.** `match_observed_devices`
   (`core/labs/features/equipment/queries/device_matching.py`) matches the serial an agent reports
   against `Equipment.serial_number`. In practice `serial_number` is typed by people: a part
   number, a USB product ID, a label. It is not what the hardware reports, so matches are wrong
   or missing. Inventory needs a separate, machine-read identity.
2. **Device scope.** Labs want only the equipment that belongs on the computer's bench, plus
   *additional* lab equipment plugged in from elsewhere; mice, keyboards, phones and personal
   sticks are noise and personal data.
3. **License state.** Tool licenses (for example Vector CANoe on a CANcase, a Vector Keyman or the
   computer itself) have a version range and an expiry date that coordinators type by hand.

## 2. Repository facts (verified by source reading)

| Fact | Evidence |
|---|---|
| Matching is exact `Equipment.serial_number` + compatible interface, across all inventory | `device_matching.py` `match_observed_devices` |
| `serial_number` is a free text inventory field (`blank=True`) | `core/labs/models/resource/equipment/equipment.py` |
| Bench placement is `EquipmentAssignment(bench, unassigned_at=None)` | `device_matching.py` `equipment_ids_on_bench` |
| `ComputingProfile.monitored_devices` is legacy JSON (Windows device IDs and names per computer), not linked to units | `core/labs/models/resource/equipment/computing.py` |
| `License` has `product`, `vendor`, `max_version`, `serial_number` (vendor serial, added by this change set), `identifier` (secret key), `expiry_date`; assigned via `LicenseAssignment` | `core/labs/models/resource/license/` |
| `EquipmentCategory.monitored`; `Equipment.product_model` → `EquipmentProductModel` | `reference_data.py`, `equipment.py` |

## 3. Monitored devices: what exists today (investigation, 2026-11-18)

| Where | What exists | Gap |
|---|---|---|
| Old agent (agent repo, `main`) | Per computer, a typed list `[{key: PNPDeviceID, value: label, status}]` in `ComputingProfile.monitored_devices`. The agent pulled it, watched those PnP IDs with WMI (3-scan debounce), pushed the status list and insert/remove events | Not linked to inventory units; its routes no longer exist |
| Matching | `match_observed_devices` (`equipment/queries/device_matching.py`): reported `serial_number` vs `Equipment.serial_number` | `Equipment.serial_number` is typed by people (part number, label, USB product ID), not read from hardware |
| Link action | `POST /api/labs/device-connections/{id}/actions/link` → `link_device_connection` (`monitoring/application/manage.py`) → `claim_equipment_serial` **writes the observed serial into `Equipment.serial_number`** (refused when the unit already has one) | Uses the human field as hardware identity |
| Expected devices | `ExpectedDevice(computing, equipment, notify_on_disconnect)`, presence `present` / `missing` / `unconfirmed` (`monitoring/queries/expected.py`); API `/api/labs/expected-devices` | Exactly "equipment mapped to this computer", but never sent to the agent |
| Frontend | Lab Monitoring devices tab, `MonitoredDevicesPopover`, link button, expected devices | Built on serial matching |

What the agent can read from Windows is the **PnP device instance ID** (`Win32_PnPEntity.PNPDeviceID`,
Device Manager → Details → *Device instance path*), e.g. `USB\VID_1248&PID_1073\007113-585343`. A
device with a USB serial keeps the same ID on every port and computer; a device without one gets a
Windows-generated last segment containing `&`, which changes with the USB port.

## 3.1 Design: register PnP IDs on equipment, the agent watches the mapped list

1. **Register** (new model `EquipmentHardwareId(equipment, kind, value, computing=None, created_by, created_at)`):
   - `kind = pnp_id`: the instance ID, normalised (upper case, `\` separators). If its last segment
     contains `&` (port-bound) `computing` is required: the ID is only valid on that computer.
   - `kind = vector_device`: the Vector device name a license tool reports (License Client
     `DeviceName`, e.g. `007113-585343`), so licenses find their carrier (section 5.4). It is
     registered separately from the unit's PnP ID: the two are independent identifiers (confirmed
     by the owner, 2026-11-18), so a CANcase usually carries both.
   - Constraint: one row per `(kind, upper(value), computing)`; a unit may have several IDs.
   - Written only by coordinators: on the equipment form (paste the instance path), or with the
     existing **Link** button, which now stores the observation's PnP ID here instead of
     claiming a serial. `Equipment.serial_number` is never written by monitoring again.
2. **Map**: unchanged `ExpectedDevice(computing, equipment, notify_on_disconnect)`; created from the
   computer's page or the bench (equipment placed on the computer's bench are suggested).
3. **Watch list** in `GET /agent/monitoring-policy` (additive, ETag as today):

   ```json
   "expected_devices": [
     {"equipment_uid": "…", "name": "CANcase 3",
      "hardware_ids": [{"kind": "pnp_id", "value": "USB\\VID_1248&PID_1073\\007113-585343"}]}
   ]
   ```

4. **Agent**: scans WMI every 5 s, reports **only** devices whose PnP ID is on the watch list, as a
   complete snapshot per change (3-scan debounce) and every half `freshness_seconds`; every other
   device stays on the computer. Each observation carries `hardware_ids: [{kind: "pnp_id", value}]`.
5. **Backend**: matches by hardware ID (exact, port-bound IDs only for their computer) →
   `DeviceConnection.equipment`. `ExpectedDevice` presence and disconnect alerts then work unchanged.
6. **Discovery** (how a new device gets its PnP ID registered): the agent's Device Scan dialog
   (admin login) shows live devices with their instance paths; its **Push** button sends a one-off
   discovery snapshot (collector `discovery`, all connected devices). They appear in Lab Monitoring
   as unlinked, and **Link** registers the PnP ID on the chosen unit. The agent can also copy the
   path for pasting on the equipment form.
7. **Migration**: entries of the legacy `monitored_devices` JSON become link suggestions on that
   computer (label + PnP ID) in the web app; units are not guessed. Serial-based matching is removed
   once the link action stores hardware IDs; existing connections are re-matched (initially unlinked).

**Additional devices** (equipment from another bench plugged here): optional phase. The policy adds
`device_models` (USB vendor/product IDs of lab equipment models, from `EquipmentProductModel.usb_ids`);
the agent also reports devices of those models, and the backend matches their `pnp_id` against all
registered IDs, so a borrowed CANcase shows as "CANcase 7 (bench B7) connected here".

| Decision | Recommendation |
|---|---|
| D3 | `EquipmentProductModel.usb_ids` for additional devices: later phase |
| D5 | Remove serial-number matching and `claim_equipment_serial` from the link flow: yes |
| D6 | Never register an ID automatically: yes, a coordinator links |
| D9 | Store hardware IDs in `EquipmentHardwareId` (new) rather than reusing `Equipment.metadata`: yes (constraint, history, port scope) |

## 5. License checks (configured in the web app)

Licenses come from many tools (Vector License Client, FlexNet license servers and files, CodeMeter
dongles, registry or file based activations) and sit either **on the computer** or **on hardware
mounted to it** (a CANcase, a dongle). The backend therefore does not hard-code vendors: a
coordinator configures **license checks** in the web app; each agent fetches the checks that apply
to its computer, runs them read-only and reports one result per run.

### 5.1 What a check is

| Part | Content | Example (Vector preset) |
|---|---|---|
| Probe | One of a **closed catalog** the agent implements: `command` (installed tool, fixed arguments, stdout), `file` (license or status file), `registry` (values under one HKLM key) | `command`: `C:\Program Files\Vector License Client\Vector.LicenseClient.exe -listlicenses` |
| Extraction | Declarative mapping, no code: format `xml` / `json` / `text` (regex with named groups) / `values` (registry), a records selector and field sources for `product_name`, `product_code`, `max_version`, `expires_at`, `final_expires_at`, `carrier_id`, `license_serial`, `is_reactivatable`, `carrier_type`; date formats and "never" values | `.//VectorLicense`; `ExpirationDateString` → `expires_at`; `9999-12-31` = never |
| Carrier | What holds the licenses: `computer`, `device` / `dongle` (identified by a hardware ID kind read from `carrier_id`), `server` (floating), `equipment` (a unit picked in the web app when the tool names no hardware), or `mapped` per license from a tool field | `mapped`: `BindingType` DEVICE → device, DONGLE → dongle, PC → computer; hardware ID kind `vector_device` |
| Targets | Which computers run it: rooms, stations, benches, equipment categories or individual computers | all benches with Vector hardware |
| Interval | Minutes between runs (≥ 15) | 360 |
| Linked licenses | Optional: the `License` records this check is expected to confirm (for tools that report no license ID) | — |

The web app offers **presets** (templates): Vector License Client, and later FlexNet `lmutil lmstat`,
CodeMeter and license-file patterns, each written against captured output from a lab computer.
A preset is an ordinary check configuration; editing one never changes agent code. The agent's
parser and presets: `agent/src/core/licensing/` (tested with a real Vector License Client sample).

### 5.2 Model (new, licenses feature)

- `LicenseCheck(key, name, vendor, probe_type, probe JSON, extract JSON, carrier JSON,
  interval_minutes, enabled, revision, created_by, modified_by)`; `revision` increments on every
  change. JSON validated per probe type with the same rules the agent applies (section 5.5).
- `LicenseCheckTarget(check, room | station | bench | category | equipment)`; resolved to
  computing equipment when an agent asks.
- `LicenseCheckLicense(check, license)`: optional expected licenses.
- `LicenseCheckRun(check, agent identity, revision, sequence, status, error_code, error_message,
  started_at, duration_ms, license_count, received_at)`: latest run per check and agent, plus
  bounded history (30 days).
- `LicenseObservation`: one row per (agent, check, observation key) with reported values, matched
  license, carrier equipment, `first_seen_at`, `last_seen_at`; removed (kept as history) when a
  complete run no longer lists it.

### 5.3 Agent routes

| Route | Meaning |
|---|---|
| `GET /agent/license-checks` | Enabled checks targeting this computer, `{"data": {"checks": [...]}}`; strong ETag, `304` when unchanged. Advertised as capability `license_checks` in `/agent/info` |
| `POST /agent/license-checks/{key}/actions/report` | One run; UUID `Idempotency-Key`; 256 KiB; body below |

```json
{
  "revision": 3, "sequence": 1794990911406, "status": "ok",
  "started_at": "2026-11-18T15:35:11+07:00", "reported_at": "2026-11-18T08:35:12Z", "duration_ms": 412,
  "is_complete": true,
  "licenses": [{
    "observation_key": "vector-license-client:serial:55100045010",
    "vendor": "Vector", "product_code": "55100", "product_name": "CANalyzer PRO",
    "carrier": {"type": "device", "hardware_id": {"kind": "vector_device", "value": "007113-585343"}},
    "expires_at": "2027-04-09T23:59:59+07:00", "final_expires_at": null,
    "max_version": "15.0", "is_reactivatable": true, "license_serial": "55100045010"
  }]
}
```

| Field | Rule |
|---|---|
| `status` | `ok` (list complete), `not_installed`, `failed`, `rejected` (agent refused the configuration); with `error: {code, message}` otherwise |
| `is_complete` | Only `ok` runs replace the license set; other statuses only record the run |
| `revision` | Runs of an older revision are recorded but do not change observations |
| `sequence` | Increasing per agent and check; older runs are stale |
| `license_serial` | The license's serial / ID from the tool (Vector `VectorLicenseId`); the match key for `License.serial_number`. Not secret. The observation key is built from it, so it follows the license when it moves |
| Never sent | raw tool output, license keys, contract or activation IDs, user names |

Source of the Vector fields: `Vector.LicenseClient -listlicenses` (Vector KB0021758). Its
`ExpirationDateString` is when the activation ends (reactivatable licenses), `FinalExpirationDateString`
`9999-12-31` means perpetual; `expires_at` follows the first because that is when the tool stops.

### 5.4 Matching by license serial, and effects

The agent pushes every license it finds with its **license serial** (the tool's own license ID,
Vector `VectorLicenseId`); the backend routes each one to the `License` record and compares.

1. **Find the license** by serial: `License.serial_number` (added in this change set, folded into `labs.0001_initial` per ADR 005;
   unique per vendor among live licenses, case-insensitive, indexed) equal to
   `license_serial`. When several vendors use the same serial, the one whose vendor name matches the
   reported `vendor` wins.
   - one license → `matched`;
   - none → `unregistered` (listed under "Found on lab hardware" for a coordinator to register);
   - several left → `ambiguous`, no effect.
   `License.identifier` stays the secret license key and is never used for matching.
   Fallback only when the tool reports no serial: the check's linked licenses with the same product,
   else the carrier's active `LicenseAssignment`s with the same `vendor_product_code`.
2. **Check that the report belongs to this computer** before anything changes. The reporting
   computer `C` is the computing equipment bound to the signing agent identity (server-derived;
   never taken from the body). The check must target `C`, otherwise the run is refused (`404`).
   For each matched license `L`:

   | Step | Rule | Failure → status (no update) |
   |---|---|---|
   | Carrier unit `U` | `computer` → `C`; `equipment` → the unit on the check; `device` / `dongle` → the unit whose registered `EquipmentHardwareId` equals the reported hardware ID (section 3.1) | `carrier_unlinked` |
   | `U` is at `C` | `U = C`; or `U` is reported **connected** by `C`'s own fresh device observations; or `U` is placed on `C`'s bench | `carrier_not_at_computer` |
   | `L` belongs there | `L` has an active `LicenseAssignment` to `U` or to `C` | `carrier_mismatch` (assigned elsewhere) or `unassigned` (no assignment) |

   Only when all three pass is the license updated. Failures are stored on the observation and listed
   under "Found on lab hardware" with the suggested fix (link the device, assign the license, move the
   assignment); nothing is reassigned automatically (decision D8).

3. **Compare and update** a `matched` license (decision D1), in one transaction, with a
   change-log entry naming the agent as actor:

   | Reported | Compared with | Action when different |
   |---|---|---|
   | `expires_at` | `License.expiry_date` | update |
   | `max_version` | `License.max_version` | update (when reported) |
   | expired (`expires_at` in the past) | license status | record `expired` via the status command (never revives `revoked` / `suspended`) |
   | `final_expires_at`, `is_reactivatable` | — | stored on the observation, shown in the UI |

   Identical values change nothing (no change-log noise); every run updates `last_seen_at`.
4. Expected licenses of a check that no `ok` run reports on any target computer → "missing".

### 5.5 Security model

Configured checks make agents run programs, so the design limits what a configuration can do:

| Risk | Guard |
|---|---|
| Arbitrary code through a check | Closed probe catalog; no shell; fixed argument list (≤ 16 × 256 chars); timeout ≤ 60 s; output ≤ 4 MiB; registry HKLM read only |
| Running or reading outside tool folders | Agent-side: executables and files must be absolute paths under Program Files, Program Files (x86), ProgramData or roots in the computer's local settings |
| Tampered configuration in transit | Agent-side: while TLS to the backend is not verified, it ignores configured paths except its trusted defaults (presets and locally configured tool paths) |
| Misuse by a web account | Creating or changing `command`/`file`/`registry` checks needs an admin role (decision D7); every change is audited; the agent reports `rejected` with the reason |
| Data leakage | Only mapped fields leave the computer; raw output never does |

### 5.6 Web app (beauty)

| Where | What |
|---|---|
| Licenses → **License checks** (new tab) | List (name, vendor, probe, targets, last runs: ok / failed / not installed per computer); create from a preset or from scratch; edit probe, mapping, carrier, targets, interval; enable/disable |
| Check editor | Form per probe type; mapping editor with field sources; "Preview" that validates the configuration; revision history |
| License detail | "Observed" panel: carrier, observed expiry and version, last seen, check, match status; difference to the registered values |
| Licenses → **Found on lab hardware** | `unregistered`, `ambiguous`, `carrier_unlinked`, `carrier_not_at_computer`, `unassigned` and `carrier_mismatch` observations, each with its fix: register the license, link the carrier device, assign the license, or move the assignment |
| Computing equipment → Agent dialog | Per check: last run status, error, license count, next expiry |

## 6. Invariants and guards

| Invariant | Guard |
|---|---|
| A hardware ID identifies at most one unit at a time | Unique `EquipmentHardwareId(kind, upper(value), computing)` |
| Port-bound PnP IDs never match on another computer | `computing` required when the last segment contains `&` (validated on write); lookup filters by the reporting computer |
| Agents cannot register hardware IDs | Written only by coordinator commands (equipment form, Link); `Equipment.serial_number` is never written by monitoring |
| An agent reports only mapped devices | Watch list = `ExpectedDevice` of its computer; discovery snapshots only on an admin's Push in the agent |
| Exact retries repeat no effects; stale snapshots never overwrite newer | Batch receipts with content hash; apply only `sequence > cursor` |
| License writes never touch `identifier` or seats | Effects limited to `expiry_date`, `max_version`, status command |
| An agent can only update licenses that are at its own computer | Reporting computer derived from the signing identity; check must target it; carrier linked, at the computer (same unit, connected by its own observations, or on its bench) and the license assigned to the carrier or the computer (section 5.4) |

## 7. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Apply observed expiry/version to `License` automatically, or review first | Automatic for `matched`, with change-log entry |
| D2 | Match by license serial (`License.serial_number`, **done**: field, unique per vendor, API, search); fall back to a check's linked licenses, then `LicenseProduct.vendor_product_code`, only for tools without serials | Yes |
| D3 | `EquipmentProductModel.usb_ids` for additional devices | Later phase |
| D4 | Warning window | 30 days |
| D5 | Replace serial-number matching and `claim_equipment_serial` in the Link flow by registered hardware IDs | Yes |
| D6 | Register hardware IDs automatically | No: a coordinator links or pastes the ID |
| D7 | Who may create or change license checks | Admins only; coordinators may enable/disable and change targets |
| D8 | Update a license only when its carrier is at the reporting computer and it is assigned to that carrier or computer | Yes; otherwise record and show, never update or reassign automatically |
| D9 | Store hardware IDs in a new `EquipmentHardwareId` model (not `Equipment.metadata` or `serial_number`) | Yes: constraint, port scope, audit |

## 8. Delivery

| Phase | Backend | Agent |
|---|---|---|
| 1 | **Done:** `EquipmentHardwareId` (+ API), Link stores PnP IDs, hardware-ID matching (serial matching removed), `expected_devices` in the policy, legacy `monitored_devices` as suggestions (`GET /api/labs/expected-devices/legacy-suggestions`) | Watch list from the policy; report only mapped PnP IDs with `hardware_ids`; Push = discovery snapshot from the Device Scan dialog |
| 2 | License checks (model, admin UI, agent routes), runs, observations, matching (no effects) | Generic check runner with presets (**done**: `agent/src/core/licensing/`, Vector preset); uses the routes once `license_checks` is advertised |
| 3 | Effects (D1), expiry notifications | Tray warnings, licenses in the device dialog |

Each phase: OpenAPI regenerated, focused tests, the gates in `docs/ai-team/quality-gates.md`,
security and QA review, owner approval before merge.
