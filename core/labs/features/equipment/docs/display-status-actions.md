# Changing equipment status from the frontend

Frontend guide for the equipment "Change status" menu. Users see and choose **display status** names only
(Available, In use, Borrowed, Maintenance, Broken, Lost, Transferred, Retired). The frontend turns each
choice into the backend call that changes the underlying fact. Users never see `lifecycle_state` or
`condition`; the frontend reads them only to decide which menu items to offer.

Behavior and rules are owned by `spec.md` and the code; this guide explains how to drive them. All routes
are under `/api/labs/` and need a lab coordinator or administrator (`api/common.py`, `EQUIPMENT_PERMISSIONS`).

## 1. Why there is no single "change status" call

`display_status` is computed by the backend from separate facts and is never written
(`EquipmentDisplayStatus`, `core/labs/models/resource/equipment/equipment.py`). The old
`POST .../actions/change-status` with per-status `details` was removed.

| Fact (equipment response field) | Changed by |
|---|---|
| `lifecycle_state` (`planned`, `in_service`, `transferred_out`, `retired`, `lost`) | `POST equipment/{id}/actions/change-lifecycle` |
| `condition` (`operational`, `in_maintenance`, `out_of_service`) | `POST equipment/{id}/actions/change-condition` |
| `placement` (bench, station, room, or a note; `null` = unknown) | `PUT` / `DELETE equipment/{id}/placement` |
| `loan` (open loan or `null`) | `POST equipment/{id}/actions/hand-over`, `.../return`, `.../extend-loan` |
| `calibration_overdue` | calibration dates; not changed from this menu |

When several facts hold, the label is the first match in this order:

| Priority | Fact | `display_status` |
|---|---|---|
| 1 | `lifecycle_state` is not `in_service` | `on_order` (planned), `transferred`, `retired`, `lost` |
| 2 | `condition = out_of_service` | `broken` |
| 3 | `condition = in_maintenance` | `maintenance` |
| 4 | open `loan` | `borrowed` |
| 5 | `placement.target_type = "bench"` | `in_use` |
| 6 | calibration required and overdue | `calibration_overdue` |
| 7 | otherwise | `available` |

A unit in a room, at a station or at a noted place is `available`; show where it is from `placement`.

## 2. Reading the status

From `GET /api/labs/equipment/{id}` (or any equipment list):

- Badge: `display_status.label` (value in `display_status.value`).
- Badge detail line: `placement` (where it is), `loan.borrower_name`, `loan.due_at`, `loan.overdue`.
- Menu rules: `lifecycle_state.value`, `condition.value`, `placement`, `loan`, `calibration_overdue`.
- Category abilities: `capabilities` of the unit's category from `GET /api/labs/equipment-categories`
  (`assignable` = can go on a bench, `bookable` = can be lent).

Show combined facts; do not hide them behind the label. A broken unit that is out on loan shows
**Broken** with "On loan to … until …" under it.

## 3. Menu: when to offer each item

Build the menu from the facts, not from the current label. Variables below: `life = lifecycle_state.value`,
`cond = condition.value`, `onBench = placement?.target_type === "bench"`, `onLoan = loan !== null`.

| Menu item | Offer when | Otherwise |
|---|---|---|
| **Maintenance** | `life === "in_service"` and `cond !== "in_maintenance"` | hide |
| **Broken** | `life === "in_service"` and `cond !== "out_of_service"` | hide |
| **In use** (put on a bench) | `life === "in_service"`, category `assignable` | hide |
| **Borrowed** (lend) | category `bookable`, `life === "in_service"`, `cond === "operational"`, not `onBench`, not `onLoan`, not `calibration_overdue` | disable, tooltip with the first failing reason |
| **Lost** | `life === "in_service"` | hide |
| **Transferred** | `life === "in_service"` | hide |
| **Retired** | `life` is `planned`, `in_service` or `lost` | hide |
| **Available** | the label is not already Available, and `life !== "retired"` | hide |
| On order, Calibration overdue | never | they are not chosen by hand |

Lost, Transferred and Retired also need the unit off its bench, and Transferred and Retired need it
returned from loan. Offer them anyway and run the preparation steps in section 5 first (with a
confirmation), or disable them with the tooltip "Remove it from the bench first" / "Take it back first".

## 4. What each item sends

Every write is `POST`/`PUT` with a JSON body; responses use `{"data": ...}`.

| Menu item | Request | Form fields to show |
|---|---|---|
| **Maintenance** | `POST equipment/{id}/actions/change-condition` `{"condition": "in_maintenance", "reason": "..."}` | Reason (optional, max 500) |
| **Broken** | `POST equipment/{id}/actions/change-condition` `{"condition": "out_of_service", "reason": "..."}` | Reason (optional, max 500) |
| **In use** | `PUT equipment/{id}/placement` `{"bench_id": 12, "role": "default", "position": 0}` | Bench picker |
| **Borrowed** | `POST equipment/{id}/actions/hand-over` `{"borrower_id": 7 \| null, "borrower_name": "", "borrower_contact": "", "purpose": "", "due_at": "<ISO, future>", "condition_out": ""}` | Borrower (user or name), contact, purpose, due date |
| **Lost** | `POST equipment/{id}/actions/change-lifecycle` `{"lifecycle_state": "lost", "reason": "..."}` | Reason |
| **Transferred** | `POST equipment/{id}/actions/change-lifecycle` `{"lifecycle_state": "transferred_out", "receiving_organisation": "...", "transfer_date": "YYYY-MM-DD", "reason": "..."}` | Receiving organisation (**required**), transfer date (default today), reason |
| **Retired** | `POST equipment/{id}/actions/change-lifecycle` `{"lifecycle_state": "retired", "reason": "..."}` | Reason; warn that this is final |

**Available** depends on what is in the way. Send the first matching row:

| Current fact | Request | Form |
|---|---|---|
| `life` is `planned` or `transferred_out` | `POST .../actions/change-lifecycle` `{"lifecycle_state": "in_service"}` | Reason |
| `life` is `lost` (found) | `POST .../actions/change-lifecycle` `{"lifecycle_state": "in_service"}`; the unit comes back as **Maintenance**, not Available | Reason (where it was found); label the item "Found" |
| `cond` is not `operational` | `POST .../actions/change-condition` `{"condition": "operational"}` | Reason |
| `onLoan` | `POST .../actions/return` `{"condition_in": "", "condition": null, "room_id": 3}` (or `station_id`, `bench_id`, `location_note`) | Return condition, where it goes now |
| `onBench` | `PUT .../placement` `{"room_id": 3}` (or `station_id`, or only `location_note`) | Where it goes now |
| only `calibration_overdue` | not possible from this menu | Tell the user to record a calibration |

After the call, re-read the unit (section 6). If it is still not Available (for example it was in
maintenance and is also on a bench, so it now shows **In use**), the menu shows the next step.

Placement body rules: give **one** of `bench_id`, `station_id`, `room_id`; with none of them,
`location_note` is required. `role` and `position` are for benches only. Any move, including bench to
room or bench to bench, is one `PUT`. `DELETE equipment/{id}/placement` makes the location unknown
(prefer a room or a note so the unit can be found).

## 5. Side effects to tell the user about

Show these in the confirmation dialog before sending:

| Action | Also happens on the server |
|---|---|
| Lost | An open loan is closed as lost; non-bench placement is closed; reserved bookings are cancelled; condition resets to operational |
| Transferred, Retired | Refused while on loan or on a bench (return / move first); non-bench placement is closed; reserved bookings are cancelled; condition resets to operational |
| Borrowed (hand-over) | The unit leaves its resting place |
| Back to service from Transferred / On order | Condition is operational |
| Found (back to service from Lost) | Condition is set to in maintenance; the unit shows **Maintenance** until it is set back to operational. It has no placement: record where it is |

Preparation sequence for Lost, Transferred or Retired on a unit that is on a bench or on loan:
1. on loan and target is Transferred or Retired → `POST .../actions/return`;
2. on a bench → `PUT .../placement` to a room or note (or `DELETE`);
3. `POST .../actions/change-lifecycle`.

Each step is its own request; if one fails, stop and show the error. Re-read the unit before continuing.

## 6. After every successful call

- `change-condition` and `change-lifecycle` return the full equipment detail: use it directly.
- `placement` `PUT` returns the placement, `DELETE` returns `204`, and `hand-over` / `return` return the
  loan. Re-fetch `GET /api/labs/equipment/{id}` to get the new `display_status`.
- Never set the badge to the label the user picked. Always show the `display_status` the server returns.
- Invalidate cached equipment lists, status summary (`equipment/status-summary`) and facets.

Choosing the state the unit already has is accepted and changes nothing (same response as success).

## 7. Errors

Errors use `{"error": {"code", "message", "details", "request_id"}}` (`docs/api/response-standard.md`).
Show `message`; branch on `code`.

| HTTP | `code` | Meaning | Frontend reaction |
|---|---|---|---|
| 409 | `invalid_state_transition` | Not allowed from the current state (e.g. condition change when not in service, anything after Retired, bench for a unit not in service or a category that is not assignable) | Re-fetch the unit, rebuild the menu |
| 409 | `equipment_already_placed` | Lost / Transferred / Retired while on a bench | Offer "Move off the bench first" |
| 409 | `equipment_on_loan` | Transferred / Retired while on loan; hand-over of a unit already lent | Offer "Take it back first" |
| 409 | `equipment_not_available` | Hand-over refused; reasons are in `details` | List the reasons |
| 409 | `equipment_not_on_loan` | Return of a unit nobody holds | Re-fetch |
| 409 | `equipment_already_assigned` | Bench placement conflict | Re-fetch |
| 422 | validation codes | Missing or invalid field (e.g. `receiving_organisation`, `due_at` in the past, two placement targets) | Show per-field errors from `details[].field` |
| 404 | `not_found` | Unit deleted or not visible | Close the dialog, refresh the list |

Not verified: the exact structure of the hand-over refusal reasons inside `details`; check one live
response before parsing it.

## 8. Reference implementation (TypeScript sketch)

```ts
type Equipment = {
  id: number;
  display_status: { value: string; label: string };
  lifecycle_state: { value: "planned" | "in_service" | "transferred_out" | "retired" | "lost" };
  condition: { value: "operational" | "in_maintenance" | "out_of_service" };
  placement: { target_type: "bench" | "station" | "room" | "note" } | null;
  loan: { due_at: string; overdue: boolean; borrower_name: string } | null;
  calibration_overdue: boolean;
};

type Step = { method: "POST" | "PUT"; path: string; body: Record<string, unknown>; form: string };

export function stepFor(target: string, e: Equipment, caps: string[]): Step | null {
  const life = e.lifecycle_state.value;
  const cond = e.condition.value;
  const base = `/api/labs/equipment/${e.id}`;
  const inService = life === "in_service";
  const condition = (c: string): Step => ({
    method: "POST", path: `${base}/actions/change-condition`, body: { condition: c }, form: "reason",
  });
  const lifecycle = (s: string, form = "reason"): Step => ({
    method: "POST", path: `${base}/actions/change-lifecycle`, body: { lifecycle_state: s }, form,
  });

  switch (target) {
    case "maintenance": return inService && cond !== "in_maintenance" ? condition("in_maintenance") : null;
    case "broken":      return inService && cond !== "out_of_service" ? condition("out_of_service") : null;
    case "in_use":      return inService && caps.includes("assignable")
      ? { method: "PUT", path: `${base}/placement`, body: {}, form: "bench" } : null;
    case "borrowed":    return caps.includes("bookable")
      ? { method: "POST", path: `${base}/actions/hand-over`, body: {}, form: "borrower" } : null;
    case "lost":        return inService ? lifecycle("lost") : null;
    case "transferred": return inService ? lifecycle("transferred_out", "transfer") : null;
    case "retired":     return ["planned", "in_service", "lost"].includes(life) ? lifecycle("retired", "retire") : null;
    case "available":
      if (life === "retired") return null;
      if (life !== "in_service") return lifecycle("in_service");
      if (cond !== "operational") return condition("operational");
      if (e.loan) return { method: "POST", path: `${base}/actions/return`, body: {}, form: "return" };
      if (e.placement?.target_type === "bench")
        return { method: "PUT", path: `${base}/placement`, body: {}, form: "location" };
      return null; // only calibration overdue, or already available
    default: return null; // on_order and calibration_overdue are never chosen by hand
  }
}
```

The `form` value names the dialog that fills `body` before sending. Keep the server as the authority: a
409 means the local rules are stale, so re-fetch and rebuild the menu.

## 9. Known gaps

- There is no endpoint that lists a unit's status history. `EquipmentEvent` rows are recorded but not
  exposed in the API, so the old status-history view has nothing to call yet.
- Removed old detail fields without a replacement: `responsible_person`, `notes`, `stored_date`,
  `expected_end_date`, `issue_description`, `failure_cause`, `last_known_location`, `supplier`,
  `expected_delivery_date`. Only `reason` remains for condition and lifecycle changes.
- The menu rules in section 3 copy the backend transition table (`LIFECYCLE_TRANSITIONS`). A server-provided
  list of allowed actions per unit would remove that copy; it is not built (API contract change, T2).
- Not verified: whether a unit on loan can be placed on a bench.
