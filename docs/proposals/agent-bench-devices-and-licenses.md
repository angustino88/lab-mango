# Agent: device links, bench watch list and license observations

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
  ],
  "license_collectors": ["vector"]
}
```

(Values are illustrative.)

- `watched_devices`: linked units placed on this computer's bench, in a `monitored` category (≤ 200).
- `device_models`: USB IDs of lab equipment models, from the new `EquipmentProductModel.usb_ids`
  (array of `{vendor_id, product_id}`, upper-case hex). A connected device of such a model that is
  not watched is reported as an *additional* device, which is also how new units get linked.
- `license_collectors`: license sources the agent should read.

The agent reports watched devices and known-model devices only. This is a reporting scope, not
authorization: the backend still validates and bounds whatever a signed agent sends.

### 4.1 Observation payload (additive)

`DeviceObservation` gains `hardware_ids: [{kind, value}]` (≤ 4 per device) and
`vendor_id`/`product_id`. `serial_number` remains accepted for compatibility and is shown as
reported evidence only.

## 5. License observations (new route)

`POST /agent/license-observations/actions/report`, signed like device observations, UUID
`Idempotency-Key`, 256 KiB limit, complete-snapshot semantics per `collector_key`.

```json
{
  "generation_key": "…", "collector_key": "vector", "sequence": 1794990911406,
  "collected_at": "2026-11-18T08:35:11Z", "is_complete": true,
  "licenses": [{
    "observation_key": "vector:device:007113-585343:55100",
    "vendor": "Vector", "product_code": "55100", "product_name": "CANalyzer PRO",
    "vendor_license_id": "55100045010",
    "carrier": {"type": "device", "hardware_id": {"kind": "vector_device", "value": "007113-585343"}},
    "expires_at": "2027-04-09T23:59:59", "final_expires_at": null,
    "max_version": "15.0", "is_reactivatable": true, "state": "valid"
  }]
}
```

Source: `Vector.LicenseClient -listlicenses` (Vector KB0021758); the agent parser and a real sample
are in `agent/src/core/vendors/vector/` and `agent/tests/vendors/vector/fixtures/`.

| Field | Rule |
|---|---|
| `carrier.type` | `device` (Vector interface), `dongle` (Keyman), `computer` (the signing agent's equipment; no `hardware_id`) |
| `expires_at` | When the license stops working unless reactivated (`ExpirationDateString`); `null` = never |
| `final_expires_at` | End of the license (`FinalExpirationDateString`); `null` = perpetual (`9999-12-31`) |
| `vendor_license_id` | Vector license ID; secret like `License.identifier`: never logged, compared by digest |
| `state` | `valid`, `expired` |
| Never sent | contract IDs, ticket/activation IDs, license files, user names |

### 5.1 Matching and effects

1. Carrier equipment: `computer` → the agent's computing equipment; otherwise the unit **linked**
   to the carrier hardware ID (section 3.2). Unlinked carrier → `carrier_unlinked`, no effect.
2. License: the license whose `identifier` equals `vendor_license_id` (the ID coordinators already
   type from the Vector portal), compared by digest; else, among the carrier's active
   `LicenseAssignment`s, the one whose product has the same `vendor_product_code` (new field on
   `LicenseProduct`). One → `matched`; none → `unassigned`; several → `ambiguous`. A license found
   by ID but assigned to another unit is reported as `carrier_mismatch` (moved or misregistered).
3. Projection `LicenseObservation` (monitoring app): observation key, carrier, matched license,
   reported values, `observed_at`, `received_at`; cursor and batch receipts as for devices.
4. Effects on `matched` (decision D1), same transaction, recorded in the resource change log with
   the agent as actor: `expiry_date` := `expires_at` when different;
   `max_version` := reported value when non-blank and different; `state = expired` → existing
   license status command records `expired` (never revives `revoked` or `suspended`).
5. `unassigned` and `carrier_unlinked` observations are listed for coordinators.

### 5.2 Expiry warnings

Daily task: matched licenses whose observed `expires_at` is within 30 days (D4) notify
coordinators. The agent shows its own tray warning.

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
| D2 | Match by `vendor_license_id` against `License.identifier`, with `LicenseProduct.vendor_product_code` as fallback | Yes |
| D3 | `EquipmentProductModel.usb_ids` | Yes |
| D4 | Warning window | 30 days |
| D5 | Keep serial-number matching as a suggestion source during migration | Yes, suggestions only; remove once links cover the fleet |
| D6 | Allow automatic linking when exactly one bench candidate exists | No: one-click confirm keeps a human decision on inventory identity |

## 8. Delivery

| Phase | Backend | Agent |
|---|---|---|
| 1 | `EquipmentHardwareLink`, link commands + UI, suggestions, link-based matching, `usb_ids`, policy watch list | Hardware IDs in observations; report watched + known-model devices; Vector device collector |
| 2 | License observation route, projection, matching (no effects) | Vector license collector (legacy + New Vector License Model) |
| 3 | Effects (D1), expiry notifications | Tray warnings, licenses in the device dialog |

Each phase: OpenAPI regenerated, focused tests, the gates in `docs/ai-team/quality-gates.md`,
security and QA review, owner approval before merge.
