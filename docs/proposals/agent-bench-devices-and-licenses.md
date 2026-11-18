# Agent: bench device watch list and license observations

**Status:** Proposed, needs owner approval (2026-11-18)
**Risk tier:** T2 (public agent API, migrations, license data written from an integration)
**Companions:** [device design](../agent-platform/device-design.md), [backend agent API](../agent-platform/backend-api.md),
[device connections](../../core/labs/features/monitoring/docs/device-connections.md),
[licenses spec](../../core/labs/features/licenses/docs/spec.md); agent side: `agent/docs/design/bench-device-and-license-monitoring.md`

## 1. Problem

1. **Device scope.** Today the agent reports every USB device and
   `match_observed_devices` (`core/labs/features/equipment/queries/device_matching.py`) compares
   each serial against *all* inventory. Labs want only the equipment that belongs on the
   computer's bench, plus *additional* lab equipment plugged in from elsewhere. Mice, keyboards,
   phones and personal sticks are noise and personal data.
2. **License state.** Tool licenses (for example Vector CANoe on a CANcase, or on a Vector Keyman
   or the computer itself) carry a version range and an expiry date. Today a coordinator types
   `License.expiry_date` and `max_version` by hand; the computer that holds the license knows the
   real values.

## 2. Repository facts (verified by source reading)

| Fact | Evidence |
|---|---|
| Matching is by exact serial + compatible interface, across all non-deleted equipment | `device_matching.py` `match_observed_devices` |
| Bench placement is `EquipmentAssignment(bench, unassigned_at=None)` | `device_matching.py` `equipment_ids_on_bench` |
| Monitoring policy returns generation, limits and interface catalog only | `core/agents/queries.py` `monitoring_policy` |
| `License` has `product`, `vendor`, `max_version`, `identifier` (secret), `expiry_date`, `seats` | `core/labs/models/resource/license/license.py` |
| A license is assigned to equipment through `LicenseAssignment` | `core/labs/models/resource/license/assignment.py` |
| `Equipment` has `serial_number`, `manufacturer`, `product_model`, `firmware_version`, `interfaces` | `core/labs/models/resource/equipment/equipment.py` |
| `EquipmentCategory.monitored` marks categories whose units are monitored | `core/labs/models/resource/equipment/reference_data.py` |

Not verified: Vector tool output formats (see the agent design, section 4).

## 3. Proposed design

### 3.1 Watch list in the monitoring policy (additive)

`GET /agent/monitoring-policy` gains two bounded fields. Existing fields and ETag behavior stay.

```json
{
  "data": {
    "generation_key": "…", "max_devices": 200, "max_body_bytes": 262144, "freshness_seconds": 120,
    "interface_names": ["USB", "CAN"],
    "watched_equipment": [
      {"uid": "…", "name": "CANcase 3", "serial_number": "025123", "interface_names": ["USB"],
       "product_model": "VN1630A", "manufacturer": "Vector"}
    ],
    "device_models": [
      {"vendor_id": "1248", "product_id": "1073", "interface_name": "USB", "product_model": "VN1630A"}
    ],
    "license_collectors": ["vector"]
  }
}
```

Values are illustrative (serials, USB vendor/product IDs); real IDs are entered per product model.

- `watched_equipment`: non-deleted units with an active placement on the **same bench as this
  computer**, in a `monitored` category, with a non-blank serial (at most 200). This is the
  "devices plugged in the bench".
- `device_models`: hardware identifiers of product models that are lab equipment. A connected
  device of such a model whose serial is **not** watched is an *additional* device: the agent
  reports it, and the existing global matching says which unit it is (or `unmatched`). At most 200.
- `license_collectors`: which license sources the agent should read (empty = none).

Schema: `EquipmentProductModel` gains `usb_ids` (array of `{vendor_id, product_id}`, 4 hex digits,
upper case; GIN-indexed). One migration, additive, nullable-equivalent default `[]`.

Matching is unchanged. The bench filter is a **reporting scope**, not authorization: the backend
still accepts and matches whatever a signed agent reports, and still enforces its limits.

### 3.2 License observations (new route)

`POST /agent/license-observations/actions/report`, signed like device observations, UUID
`Idempotency-Key`, 256 KiB limit, same complete-snapshot semantics per `collector_key`
(a complete snapshot marks omitted licenses of that collector as absent).

```json
{
  "generation_key": "…", "collector_key": "vector", "sequence": 1794990911406,
  "collected_at": "2026-11-18T08:35:11Z", "is_complete": true,
  "licenses": [{
    "observation_key": "vector:device:025123:CANoe",
    "vendor": "Vector",
    "product_code": "CANoe",
    "product_name": "CANoe pro",
    "carrier_type": "device",
    "carrier_serial": "025123",
    "valid_until": "2027-03-31",
    "max_version": "19",
    "state": "valid"
  }]
}
```

| Field | Rule |
|---|---|
| `carrier_type` | `device` (a Vector interface), `dongle` (Keyman), `computer` (this computing equipment) |
| `carrier_serial` | Required for `device`/`dongle`; ignored for `computer` (the signing agent's equipment is the carrier) |
| `valid_until` | Date or `null` (perpetual) |
| `state` | `valid`, `expired`, `not_activated` |
| Never sent | activation keys, ticket IDs, license file contents, user names |

### 3.3 Matching and effects

1. Carrier: `computer` → the agent's computing equipment; otherwise the equipment with
   `serial_number = carrier_serial` (same ambiguity rules as devices; ambiguous → no effect).
2. License: among the carrier's **active** `LicenseAssignment`s, the license whose product matches
   `product_code` (new `LicenseProduct.vendor_product_code`, case-insensitive; fallback: product
   name). Exactly one → `matched`; none → `unassigned`; several → `ambiguous`.
3. Projection `LicenseObservation` (monitoring app): observation key, carrier, matched license,
   reported product/version/validity/state, `observed_at`, `received_at`; one row per observation
   key and agent generation, like `DeviceConnection`.
4. Effects on a `matched` license, in the same transaction, recorded in the resource change log
   with the agent as actor (decision D1):
   - `expiry_date` := `valid_until` (end of that day, lab time zone) when different;
   - `max_version` := `max_version` when different and non-blank;
   - `state = expired` → existing license status command records `expired`
     (never revives a `revoked` or `suspended` license).
5. `unassigned` observations are listed for coordinators ("licenses found on lab hardware") so
   they can register or assign them; nothing is created automatically.

### 3.4 Expiry warnings

A daily Celery task lists matched licenses whose observed `valid_until` is within 30 days
(configurable) and notifies coordinators through the existing notification channel. The agent
shows its own tray warning on the computer (agent design, section 6).

## 4. Invariants and guards

| Invariant | Guard |
|---|---|
| One projection per observation key and generation | Unique constraint |
| Sequences ordered per collector | Cursor table like `DeviceObservationCursor` |
| Exact retries do not repeat effects | Batch receipt with content hash (as device observations) |
| License writes never touch `identifier` or seats | Effects limited to `expiry_date`, `max_version`, status command |
| A stale snapshot never overwrites a newer one | Apply only `sequence > cursor` |

## 5. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Apply observed expiry/version to `License` automatically, or only show them for review | Automatic for `matched`, with change-log entry; the vendor license store is the source of truth |
| D2 | Add `LicenseProduct.vendor_product_code` | Yes; names are not stable enough to match on |
| D3 | Add `EquipmentProductModel.usb_ids` for "additional devices" | Yes |
| D4 | Warning window | 30 days |

## 6. Delivery

| Phase | Backend | Agent |
|---|---|---|
| 1 | Policy watch list + `usb_ids` migration | Report only watched / known-model USB devices; Vector device collector (serials from the XL driver) |
| 2 | License observation route, projection, matching (no effects) | Vector license collector (legacy + New Vector License Model) |
| 3 | Effects (D1) + expiry notifications | Tray warnings, licenses in the device dialog |

Each phase: OpenAPI regenerated, focused tests, the quality gates in `docs/ai-team/quality-gates.md`,
security and QA review, owner approval before merge.
