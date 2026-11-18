# Agent: device links, bench watch list and configurable license checks

**Status:** Proposed, needs owner approval (revised 2026-11-18)
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
| `License` has `product`, `vendor`, `max_version`, `identifier` (secret), `expiry_date`; assigned via `LicenseAssignment` | `core/labs/models/resource/license/` |
| `EquipmentCategory.monitored`; `Equipment.product_model` → `EquipmentProductModel` | `reference_data.py`, `equipment.py` |

## 3. Hardware identity and device links

### 3.1 What the agent can read

| Kind | Value example | Strength | Scope |
|---|---|---|---|
| `usb_serial` | `1248:1073:025123` (vendor ID, product ID, USB serial descriptor) | Unique per physical device | Global |
| `vector_device` | `007113-585343` (Vector device name, as the License Client and Hardware Config show it) | Unique per physical device | Global |
| `usb_port` | `USB\VID_046D&PID_C52B\5&2A3C0F1&0&2` (Windows ID of a device without a serial) | Tied to a port of one computer | That computer only |
| model | `1248:1073` | Not an identity, only the model | — |

Agents report every kind they can read for a device; one device can have several (a Vector
interface has `usb_serial` and `vector_device`).

### 3.2 Device link (new model)

`EquipmentHardwareLink(equipment, kind, value, computing=None, linked_by, linked_at, unlinked_at)`

- Created by a coordinator, once per physical unit, from the web app; never by an agent.
- `computing` is required for `usb_port` (the link is only valid on that computer) and empty otherwise.
- Constraint: one active link per `(kind, lower(value), computing)`. A unit may have several links.
- Unlinking keeps history (`unlinked_at`), like placements.

**Matching** becomes a link lookup: an observed device is `matched` to the unit linked to any of
its hardware IDs; `conflict` if its IDs are linked to different units; `unlinked` otherwise.
`Equipment.serial_number` is no longer used for matching; it stays a human label.

**Linking help.** For an `unlinked` device the backend computes *suggestions*: units on the
computer's bench whose product model lists the device's USB model (`usb_ids`, section 4) and that
have no link of that kind yet. One candidate → "link to CANcase 3?" one-click confirm; several →
pick from the short list. A coordinator can also link from the unit's page by choosing a device
currently seen on its bench.

### 3.3 Migration of current behaviour

- Existing `DeviceConnection` rows keep their history; their match status is recomputed from links
  (all start `unlinked`).
- The serial-based matcher is removed after links exist (decision D5: keep it as a suggestion
  source meanwhile, since a typed serial sometimes equals the hardware serial).
- `monitored_devices` JSON can seed suggestions on that computer (names + Windows IDs), not links.

## 4. Bench watch list in the monitoring policy (additive)

`GET /agent/monitoring-policy` gains:

```json
{
  "watched_devices": [
    {"equipment_uid": "…", "name": "CANcase 3",
     "hardware_ids": [{"kind": "vector_device", "value": "007113-585343"}]}
  ],
  "device_models": [
    {"vendor_id": "1248", "product_id": "1073", "product_model": "VN1630A"}
  ]
}
```

(Values are illustrative.)

- `watched_devices`: linked units placed on this computer's bench, in a `monitored` category (≤ 200).
- `device_models`: USB IDs of lab equipment models, from the new `EquipmentProductModel.usb_ids`
  (array of `{vendor_id, product_id}`, upper-case hex). A connected device of such a model that is
  not watched is reported as an *additional* device, which is also how new units get linked.

The agent reports watched devices and known-model devices only. This is a reporting scope, not
authorization: the backend still validates and bounds whatever a signed agent sends.

### 4.1 Observation payload (additive)

`DeviceObservation` gains `hardware_ids: [{kind, value}]` (≤ 4 per device) and
`vendor_id`/`product_id`. `serial_number` remains accepted for compatibility and is shown as
reported evidence only.

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
    "observation_key": "vector-license-client:serial:3f9c0d6e1a2b4c5d6e7f8a9b",
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
| `license_serial` | The license's serial / ID from the tool; the match key for `License.identifier`. Secret: never logged, compared by digest. The observation key uses a digest too, so it follows the license when it moves |
| Never sent | raw tool output, contract or activation IDs, user names |

Source of the Vector fields: `Vector.LicenseClient -listlicenses` (Vector KB0021758). Its
`ExpirationDateString` is when the activation ends (reactivatable licenses), `FinalExpirationDateString`
`9999-12-31` means perpetual; `expires_at` follows the first because that is when the tool stops.

### 5.4 Matching by license serial, and effects

The agent pushes every license it finds with its **license serial** (the tool's own license ID,
Vector `VectorLicenseId`); the backend routes each one to the `License` record and compares.

1. **Find the license** by serial: `License.identifier` (help text "License key or serial") equal to
   `license_serial`. The identifier is a secret, so the lookup uses a new indexed
   `identifier_sha256` column (digest of the normalised identifier) instead of the plain value.
   - one license → `matched`;
   - none → `unregistered` (listed under "Found on lab hardware" for a coordinator to register);
   - several (duplicate identifiers) → `ambiguous`, no effect.
   Fallback only when the tool reports no serial: the check's linked licenses with the same product,
   else the carrier's active `LicenseAssignment`s with the same `vendor_product_code`.
2. **Compare the carrier** (where the license sits) with Lab Mango: carrier equipment is the agent's
   computer (`computer`), the unit on the check (`equipment`), or the unit **linked** to the reported
   hardware ID (`device` / `dongle`, section 3.2). If the matched license has an active assignment and
   it is to a different unit → `carrier_mismatch` (moved or misregistered: shown, never reassigned
   automatically). An unlinked carrier device → `carrier_unlinked` (shown with a link suggestion).
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
| Licenses → **Found on lab hardware** | `unregistered`, `ambiguous`, `carrier_unlinked` and `carrier_mismatch` observations, with actions: register, assign, link the carrier device |
| Computing equipment → Agent dialog | Per check: last run status, error, license count, next expiry |

## 6. Invariants and guards

| Invariant | Guard |
|---|---|
| A hardware ID identifies at most one unit at a time | Partial unique index on active links `(kind, lower(value), computing)` |
| Port-scoped IDs never match on another computer | `computing` required for `usb_port` (check constraint); lookup filters by the reporting computer |
| Agents cannot create or change links | Links written only by authenticated coordinator commands |
| Exact retries repeat no effects; stale snapshots never overwrite newer | Batch receipts with content hash; apply only `sequence > cursor` |
| License writes never touch `identifier` or seats | Effects limited to `expiry_date`, `max_version`, status command |

## 7. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Apply observed expiry/version to `License` automatically, or review first | Automatic for `matched`, with change-log entry |
| D2 | Match by license serial (`License.identifier`, new `identifier_sha256` index); fall back to a check's linked licenses, then `LicenseProduct.vendor_product_code`, only for tools without serials | Yes |
| D3 | `EquipmentProductModel.usb_ids` | Yes |
| D4 | Warning window | 30 days |
| D5 | Keep serial-number matching as a suggestion source during migration | Yes, suggestions only; remove once links cover the fleet |
| D6 | Allow automatic linking when exactly one bench candidate exists | No: one-click confirm keeps a human decision on inventory identity |
| D7 | Who may create or change license checks | Admins only; coordinators may enable/disable and change targets |

## 8. Delivery

| Phase | Backend | Agent |
|---|---|---|
| 1 | `EquipmentHardwareLink`, link commands + UI, suggestions, link-based matching, `usb_ids`, policy watch list | Hardware IDs in observations; report watched + known-model devices; Vector device collector |
| 2 | License checks (model, admin UI, agent routes), runs, observations, matching (no effects) | Generic check runner with presets (**done**: `agent/src/core/licensing/`, Vector preset); uses the routes once `license_checks` is advertised |
| 3 | Effects (D1), expiry notifications | Tray warnings, licenses in the device dialog |

Each phase: OpenAPI regenerated, focused tests, the gates in `docs/ai-team/quality-gates.md`,
security and QA review, owner approval before merge.
