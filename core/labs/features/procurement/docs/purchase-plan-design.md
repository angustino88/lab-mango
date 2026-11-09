# Design: Draft Purchase Plan in the Existing Purchase Aggregate

| | |
| --- | --- |
| **Version** | 1.0 (final specification) |
| **Status** | **Approved to start implementation** (owner instruction, 2026-11-07). Merge, deploy, and the breaking cutover (§11) still require human review. |
| **Date** | 2026-11-07 (supersedes the 2026-11-06 documentation-only draft) |
| **Risk tier** | T2: schema, monetary data, public API, write policy |
| **Domain** | Procurement / Finance (Labs) |
| **Authority** | Existing purchase and allocation contracts stay authoritative until each slice is merged. This document is not a second model authority; the Labs model document is updated in the same change (§13, WP7). |
| **Audience** | Backend implementation agent and human reviewers |

---

## 1. Summary

While assembling a purchase draft, users record **why** each item is needed. The owner chose to reuse `Purchase(status="draft")` rather than add a plan entity. This change adds per-line `purpose`, `priority` (a foreign key to an admin-managed reference table), and `unit`; draft detail/edit/delete endpoints with optimistic concurrency; idempotent creates; and an audit trail. It must not corrupt money data, deadlock existing commands, or change the meaning of any existing report.

A draft is an **estimate of intent**. It is not a budget, commitment, expense, allocation, or payment (§3).

## 2. Goals and non-goals

**Goals**

1. Capture purpose, priority, and unit per purchase line.
2. Allow safe edit of a draft header and of its unallocated lines.
3. Preserve existing contracts, report formulas, and history until an approved cutover.
4. Make every new write safe under concurrency, retries, and stale clients.
5. Make every money-affecting change attributable.

**Non-goals**

- Order placement, status transitions, budget reservation or warning, approval workflow, department isolation.
- Invoice-date recognition, partial invoices, frozen FX (not verified as approved repository decisions).
- Fractional quantities, per-line currency, controlled unit catalog, attachments.
- Deleting a purchase or any settled history.
- Any change to report formulas, actual-spend totals, or cash-flow totals.
- An API to create or edit priorities (managed in Django admin in this slice).

## 3. Financial semantics

| Stage | Meaning | Record | Created by this change? |
| --- | --- | --- | --- |
| Plan / estimate | Intent to buy, estimated cost | `Purchase(status="draft")` + `PurchaseItem` | Yes (metadata only) |
| Commitment | Order placed with supplier | `Purchase(status="ordered")` | No |
| Receipt | Goods or services received | `Purchase(status="received")` | No |
| Allocation | Item assigned to a resource | `ResourceAllocation` | No |
| Cash event | Settled payment | `PurchaseTransaction` | No |

| ID | Money rule |
| --- | --- |
| M1 | Draft estimates are excluded from actual-spend and cash-flow totals. |
| M2 | Line value is derived: `quantity * unit_price`. Never stored. |
| M3 | `Purchase.total_amount` is a separately entered stated total. Never recomputed or overwritten by this feature. |
| M4 | Draft detail exposes `total_amount` and `lines_total` as separately named fields. `is_balanced` stays a read-time comparison, not a write invariant. |
| M5 | `unit_price = 0` means "estimate not yet known", not "free". |
| M6 | Draft detail exposes derived `unpriced_line_count` (lines with `unit_price = 0`). |
| M7 | Currency is the purchase currency; no per-line currency. It cannot change once any allocation, transaction, or committed financial activity exists. |
| M8 | New money output uses the same representation as existing routes (decimal, two places). Never floats. |

## 4. Decisions (all closed)

| ID | Decision | Origin |
| --- | --- | --- |
| D1 | Use `Purchase(status="draft")`; no separate plan entity. | Owner |
| D2 | Supplier, purchase date, and purchase total stay required for a draft. | Owner |
| D3 | A draft is editable. Lines can be added, edited, removed. Lines with resource allocations cannot be edited or removed. | Owner |
| D4 | After the approved cutover, every new line requires a purpose, including lines added through existing creation routes. | Owner |
| D5 | During the compatibility phase, old clients may create lines without the new metadata. The exception is measured and retired at cutover. | Owner |
| D6 | Legacy lines keep unknown purpose (`null`). Purpose is never derived from `notes`. | Owner |
| D7 | API audience is unchanged: authenticated and API-key readers; coordinator/admin and API-key writers. This is not department isolation and not an endorsement of exposing financial reports. | Owner |
| D8 | Budget/access-control redesign (department scope, finance role, tightening global finance APIs) is a separate breaking rollout. | Owner |
| D9 | The per-item remark reuses the existing `notes` column and public `notes` field (UI label "Remark"). No second column. | Owner (final) |
| D10 | **`priority` is a foreign key to a reference table `PurchasePriority`, shown as a select.** Not a hard-coded enum or DB check. | Owner |
| D11 | `PurchasePriority` rows are managed by admins (Django admin in this slice) and seeded by a data migration with `low`, `normal`, `high`, `urgent`. Rows in use cannot be deleted (`PROTECT`); they are deactivated instead. | Owner / Review |
| D12 | `unit` is free text for now (trimmed, ≤ 32 chars). A controlled unit catalog is deferred. | Final |
| D13 | `purpose` and `notes` ≤ 2,000 chars. | Final |
| D14 | `quantity` ≤ 1,000,000; ≤ 500 lines per purchase. Exceeding returns 422. | Final |
| D15 | Line creation does not require the parent `If-Match`; it still bumps the parent version. | Final |
| D16 | An append-only audit event is written in the same transaction as every draft/line mutation (§9.5). | Final |
| D17 | Required-field validation is behind a setting flag, default **off**. Turning it on is the breaking cutover and needs separate human approval. | Final |
| D18 | Machine (API-key) writes to the new operations are blocked until a scoped, auditable machine identity exists. API-key reads are allowed (D7). | Final |

## 5. Baseline (verify first, see WP0)

- `Purchase` requires `supplier`, `purchase_date`, `total_amount`. Statuses: `draft`, `ordered`, `received`, `cancelled`.
- `PurchaseItem` has `description`, `quantity`, `unit_price`, `notes`; no `purpose`, `priority`, `unit`, or stored line total.
- Existing endpoints list/create purchases, items, allocations, transactions. No draft detail, PATCH, DELETE, or placement action exists.
- The HTTP serializer exposes `status` read-only, but the creation **command** can accept a status. Do not widen this.
- The existing allocation command locks `PurchaseItem` **before** `Purchase`.
- Existing transaction and allocation creation have no draft-specific restriction. Leave them unchanged.

References: [purchase model](../../../models/procurement/purchase.py), [routes](../api/urls.py), [commands](../application/commands.py).

## 6. Data model

All changes are additive. Do not edit applied migrations.

### 6.1 New model: `PurchasePriority` (reference data)

```python
class PurchasePriority(models.Model):
    code = models.SlugField(max_length=32, unique=True)      # stable key, never reused
    name = models.CharField(max_length=64)                    # display label
    rank = models.PositiveSmallIntegerField()                 # higher = more urgent; display order only
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("name"), name="purchasepriority_name_ci_uniq"),
        ]
        ordering = ["-rank", "id"]
```

Seed (data migration, idempotent by `code`): `low`=10, `normal`=20, `high`=30, `urgent`=40, all active. Admins may rename, re-rank, deactivate, or add rows. Seed rows are not recreated if an admin deactivates them; deletion of a used row is blocked by `PROTECT`.

`rank` is informational. It must **not** reorder invoices, reserve funds, or drive any workflow.

### 6.2 Changes to `PurchaseItem`

| Field | Definition | Rule for new rows | Legacy |
| --- | --- | --- | --- |
| `purpose` | `TextField(null=True, blank=True)` | Required after cutover; trimmed, non-blank, ≤ 2,000, control chars rejected | `null` = unknown |
| `priority` | `ForeignKey(PurchasePriority, null=True, blank=True, on_delete=PROTECT, related_name="purchase_items")` | Required after cutover; must reference an **active** priority; no default | `null` = unknown, never `normal` |
| `unit` | `CharField(max_length=32, null=True, blank=True)` | Required after cutover; trimmed, non-blank | `null` = unknown |
| `notes` | existing | Optional remark, ≤ 2,000 | unchanged |
| `quantity` | existing | Explicit positive integer after cutover; ≤ 1,000,000 | existing default `1` kept only during compatibility |
| `unit_price` | existing | non-negative `Decimal(14,2)` | unchanged |
| `version` | `PositiveIntegerField(default=1)` | incremented on each line edit | n/a |

### 6.3 Changes to `Purchase`

`version = PositiveIntegerField(default=1)`. Incremented by every header edit and every line create/edit/delete. Backs the strong ETag.

### 6.4 `PurchaseIdempotencyRecord`

| Column | Notes |
| --- | --- |
| `credential_ref` | User ID or API-key identifier (never the secret) |
| `key` | Client `Idempotency-Key` |
| `method`, `path` | Original request |
| `body_hash` | SHA-256 of the canonicalized body |
| `state` | `in_progress` / `completed` |
| `status_code`, `response_body` | Stored result once completed |
| `created_at`, `expires_at` | Retention ≥ 24 h (confirm against longest client retry window) |

`UniqueConstraint(credential_ref, key)`. Same key with a different body hash, method, or path → 422.

### 6.5 `PurchaseAuditEvent` (append-only)

`purchase` (FK, PROTECT), `item_id` (nullable, no FK so it survives line deletion), `action` (`create`/`update`/`delete`), `actor`, `credential_ref`, `request_id`, `before` (JSON), `after` (JSON), `occurred_at`. `before`/`after` always include `quantity`, `unit_price`, `currency`, `total_amount` when they changed, and priority as `{id, code}`. No update or delete path. Retention follows the finance retention policy (owner to confirm; default keep indefinitely).

### 6.6 Database vs. application enforcement

| Invariant | Enforced by |
| --- | --- |
| Item → purchase protected FK; item → priority `PROTECT` | Database |
| `quantity > 0`, `unit_price >= 0` | Database |
| Priority is a valid row | Database (FK) |
| Priority is **active** | Command (at write time; not locked, a concurrent deactivation is acceptable) |
| `purpose` / `unit` / `priority` present on **new** rows | Application (a row check cannot tell legacy from new) |
| Draft-only, not allocated, version match, header-total balance | Commands + consistent locking |

If direct or admin SQL must obey the application-only rules, design triggers or a snapshot first. Do not claim a database guarantee otherwise.

## 7. API contract (slashless paths)

### 7.1 Endpoints

| Method and path | Purpose | Preconditions |
| --- | --- | --- |
| `GET /api/labs/purchase-priorities` | Select options for the UI. Active only by default; `include_inactive=true` returns all. Ordered `-rank, id`. | Same audience as purchase reads (D7). |
| `POST /api/labs/purchases` | Existing creation, extended with nested items. | Header fields stay required. Each item needs purpose, `priority_id`, unit, quantity, unit price once D17 is on. Zero items allowed. 201 + `Location`. |
| `GET /api/labs/purchases/{purchase_id}` | Detail: parent fields, `version`, `ETag`, `lines_total`, `unpriced_line_count`, line count, links. No unbounded inline collections. | D7 audience. |
| `PATCH /api/labs/purchases/{purchase_id}` | Edit supplier, purchase date, order number, currency, total, notes. | Draft only. `If-Match` required. `status` not writable. |
| `GET/POST /api/labs/purchases/{purchase_id}/items` | Existing list/create. | GET unchanged plus new fields. POST requires new fields only when D17 is on. |
| `GET/PATCH/DELETE /api/labs/purchases/{purchase_id}/items/{item_id}` | Line detail/edit/remove. | Line belongs to parent. Draft only, unallocated only. `If-Match` on PATCH/DELETE. DELETE → 204. |

### 7.2 Field contract

Input uses `priority_id` (integer). Output uses a nested object. Both are on item create, item PATCH, and nested items in `POST /purchases`.

```json
POST /api/labs/purchases/118/items
Idempotency-Key: 6f1c2a9e-0d4b-4c1e-9a77-2b5e8c1d3f40

{
  "description": "Oscilloscope probe, 500 MHz",
  "quantity": 4,
  "unit": "piece",
  "unit_price": "320.00",
  "priority_id": 3,
  "purpose": "Replace damaged probes on bench B-12 before the radar validation campaign.",
  "notes": "Supplier quote valid until month end."
}
```

```json
201 Created
Location: /api/labs/purchases/118/items/907
ETag: "item-907-v1"

{
  "id": 907,
  "description": "Oscilloscope probe, 500 MHz",
  "quantity": 4,
  "unit": "piece",
  "unit_price": "320.00",
  "line_value": "1280.00",
  "priority": { "id": 3, "code": "high", "name": "High" },
  "purpose": "Replace damaged probes on bench B-12 before the radar validation campaign.",
  "notes": "Supplier quote valid until month end."
}
```

Legacy lines return `"priority": null`, `"purpose": null`, `"unit": null`.

### 7.3 Validation

| Field | Rule | Error |
| --- | --- | --- |
| `priority_id` | Exists and `is_active`. For nested creates, resolve all IDs in one query. On PATCH, unchanged inactive priority is allowed. | 422, field `priority_id` |
| `purpose` | Trim, non-blank, ≤ 2,000, no control chars | 422 |
| `unit` | Trim, non-blank, ≤ 32 | 422 |
| `quantity` | Integer, 1..1,000,000 | 422 |
| `unit_price` | Decimal ≥ 0, two places, within `Decimal(14,2)` | 422 |
| Line count | ≤ 500 per purchase | 422 |
| Unknown or read-only keys | Rejected | 422 |

### 7.4 Rules

1. Separate input and output serializers for every new operation. Allowlist fields.
2. Old routes keep current monetary response shapes. New fields are additive.
3. Lists use the standard bounded paginator, order by unique `id`, and use `select_related("priority")` (no per-line queries).
4. Wrong parent, missing ID, and not-visible ID return the **same** 404.
5. Normal API error envelope, with these codes:

| Code | Condition |
| --- | --- |
| 201 / 204 | Created (with `Location`) / line deleted |
| 404 | Missing, wrong parent, or not visible |
| 409 | Not in draft, line allocated, idempotent request in progress |
| 412 | Stale `If-Match` |
| 422 | Validation, bound exceeded, idempotency key reused with different body or path |
| 428 | `If-Match` missing |

6. Items added while editing do not place an order. Do not repurpose `POST /purchases` for placement and do not make `status` writable.

## 8. Business rules by purchase status

| Operation | `draft` | `ordered` / `received` / `cancelled` |
| --- | --- | --- |
| PATCH header | Allowed | 409 |
| Create line (existing route) | Allowed | Existing behavior kept; metadata required when D17 is on |
| Edit / delete line | Allowed if unallocated | 409 |
| Change currency | Only with no allocation, transaction, or committed financial activity | 409 |
| Change `total_amount` | Allowed; no automatic balancing or recompute (M3) | 409 |
| Create allocation / transaction (existing) | Unchanged | Unchanged |

## 9. Write safety

### 9.1 Locking
1. Lock order for every draft edit: `Purchase` → `PurchaseItem` rows by primary key → allocation checks. `PurchasePriority` is reference data and is not locked.
2. Refactor the existing allocation command to the same order **before** adding parent-first locks.
3. Set a bounded `lock_timeout` on these commands. Map a timeout to a retryable error, not a hang.
4. No lockless check-then-write.

### 9.2 Transactions and versions
1. Each create/update/delete is one command-owned atomic transaction with an explicit actor.
2. Strong ETag from `version` (e.g. `"purchase-118-v4"`, `"item-907-v2"`). Compare-and-update or lock-then-check; a stale edit fails with 412 and overwrites nothing.
3. Line mutations bump the parent version.
4. A replayed conditional PATCH/DELETE returns the stored original or the documented 412/404. It never duplicates a line.

### 9.3 Idempotency
- Required on new creates (`POST /purchases`, `POST .../items`). Scope: credential + key, with method, path, and body hash compared (§6.4).
- Repeat of key + body → original status and body. In progress → 409. Different body, method, or path → 422. Follow WRT-8.
- A key-only request has `actor=None`. **Never treat that as unrestricted authority** (D18).

### 9.4 Atomicity of audit
The audit event and the mutation commit together or not at all.

## 10. Security and access

- Audience per D7. Existing list, item, and transaction access is global for authenticated readers and API keys; do not claim department isolation.
- Explicit permission classes on every new route. Build the role × action × purchase relationship × API-key/anonymous test matrix.
- Prove existing routes' permissions are unchanged (equivalence tests).
- Priority reference data is readable by the same audience; writes are admin-only (Django admin).
- Never log request bodies containing money or free text at INFO; log IDs and request IDs.

## 11. Compatibility and rollout

**VER-2 classification.** Non-breaking: additive response fields, detail/edit routes, priority list route. **Breaking:** requiring purpose / `priority_id` / unit / explicit quantity on either existing create path; requiring concurrency headers on old write routes. Non-production does not mean clients cannot break.

| Phase | Content | Gate |
| --- | --- | --- |
| 1. Expand | New Labs migrations: `PurchasePriority` + seed; nullable item fields; version counters; idempotency and audit tables. | Rehearsal on PostgreSQL with existing rows. |
| 2. Accept | New fields accepted; detail/edit/delete; audit writes. D17 flag **off**. | Full tests green; OpenAPI diff reviewed. |
| 3. Measure | Counter of item creates missing metadata, by client/credential. | Owner-defined period with zero legacy-style creates (suggested 14 days) and all known clients migrated. |
| 4. Cutover | Turn D17 flag **on**. | **Separate human approval.** |
| 5. Later | Backfill and non-null constraints for legacy rows. | Own decision. |

**Rollback.** Additive schema is reversible only while no new data exists; afterwards keep columns and roll back code first. Cutover rollback = turn the flag off.

## 12. Observability

- Metrics: create/update/delete by outcome (2xx/409/412/422/428); idempotent replays; lock timeouts; legacy-style item creates; p95 for detail and list.
- Alerts: sustained lock timeouts, post-release rise in 412, any 5xx on new routes.
- Request ID is stored on every audit event.

## 13. Backend agent implementation plan

### 13.1 Operating rules
1. Work in the work packages below, in order. One PR per package; each PR runs the applicable [quality gates](../../../../../docs/ai-team/quality-gates.md).
2. Follow the existing feature-layer convention (commands, queries, `public.py`, `contracts.py`, `exceptions.py`). Keep input and output serializers separate.
3. Never edit an applied migration. Never change report formulas or existing permission classes.
4. Keep the D17 flag **off** in every PR. Never flip it.
5. Treat this document as the spec. If the code contradicts a statement in §5, follow §13.3 (stop and ask).

### 13.2 Work packages

| WP | Deliverable | Depends on | Done when |
| --- | --- | --- | --- |
| WP0 | **Preflight.** Read the model, routes, commands, permission classes, and existing tests. Verify §5 and the relative links. Confirm the meaning of the rule IDs (§16) from the API standard. Write a short findings note in the PR. | none | Every §5 statement confirmed or a discrepancy raised. Baseline tests pass. |
| WP1 | `PurchasePriority` model, migration, idempotent seed, admin, query selector, `GET /api/labs/purchase-priorities` (separate serializer, paginator). | WP0 | Seed idempotent; rows in use cannot be deleted; list ordered `-rank, id`; inactive hidden by default. |
| WP2 | Expand migration: `purpose`, `priority` FK, `unit`, `version` fields on item/purchase, `PurchaseIdempotencyRecord`, `PurchaseAuditEvent`. Nullable only. | WP1 | Migration rehearsed on PostgreSQL with legacy rows; legacy rows load with nulls. |
| WP3 | Refactor allocation command lock order to Purchase → items (pk order) → allocations; add concurrency test. | WP0 | Existing allocation behavior unchanged; two-session test shows no deadlock. |
| WP4 | Commands and selectors: purchase detail, PATCH, item create (nested and standalone), item PATCH, item DELETE. Validation per §7.3; locking per §9.1; versions per §9.2; audit per §6.5; flag-aware required-field check. | WP2, WP3 | Rules in §8 enforced; money rules M1–M8 hold. |
| WP5 | API layer: serializers, views, URLs, permission classes, ETag / `If-Match`, `Idempotency-Key`, error envelope, `Location`, machine-write block (D18). | WP4 | Contract in §7 matches generated OpenAPI. |
| WP6 | Compatibility flag (D17, default off) and Phase 3 metrics counter. | WP5 | Flag off: old clients behave as before; flag on (tests only): omission returns 422 on both create paths. |
| WP7 | Docs: update [labs-model-architecture](../../../models/docs/labs-model-architecture.md) (new model, fields, inheritance/relations); update `openapi/openapi.yml` and golden examples in `docs/api/`; Spectral lint passes; mark this document's status. | WP5 | Docs and spec match the code. |
| WP8 | Verification package: full test results, query-budget evidence, OpenAPI diff, permission matrix, migration rehearsal notes; request independent security/QA/code review. | WP1-WP7 | Package attached to the final PR. |

### 13.3 Stop and ask a human
- Baseline tests fail before any change.
- The allocation refactor would change existing behavior.
- An applied migration, existing permission class, or report formula would need to change.
- API-key identity cannot be audited or scoped (keep machine writes blocked; do not invent an identity).
- Any change would make a draft estimate count toward actual spend or cash flow.
- A need arises for a new column or endpoint not in this document.
- Turning on the D17 flag.

### 13.4 Definition of done
All WPs merged; quality gates green; test plan (§14) complete; acceptance criteria (§15) satisfied; D17 still off; independent review done; owner approval recorded before deploy.

## 14. Test plan

1. **Migration:** rehearsal on PostgreSQL with existing rows; seed idempotent; legacy rows keep nulls.
2. **Priority reference:** list order and `include_inactive`; PROTECT blocks deleting a used row; inactive priority rejected on create and on changed PATCH; unchanged inactive priority allowed on PATCH; unknown ID → 422 on `priority_id`; nested create resolves priorities in one query.
3. **Commands:** valid and invalid payloads; rollback on failure; bounds (quantity, line count, text length).
4. **Concurrency:** stale update → 412, no lost edit; concurrent edit vs allocation in both orders; `lock_timeout` mapping.
5. **Idempotency:** replay, different body, different path, in-progress.
6. **Protection:** allocated line and non-draft purchase return 409.
7. **Money:** derived line value; `total_amount` never rewritten; currency lock; `unpriced_line_count`; drafts excluded from existing spend/cash-flow outputs.
8. **Audit:** one event per mutation, written atomically, includes priority `{id, code}` and money fields.
9. **Security:** full permission matrix; equivalence of existing-route permissions; machine writes to new routes blocked.
10. **Performance:** bounded-query tests on ≥ 3 rows for list and detail (`select_related("priority")`).
11. **Contract:** generated OpenAPI compared with prior contracts; Spectral lint.
12. **Flag:** off = legacy behavior; on = 422 on omission on both create paths.

## 15. Acceptance criteria

- A draft round-trips with several lines, each with a distinct purpose and a selected priority.
- The UI can load priority options from `GET /api/labs/purchase-priorities`.
- Only unallocated lines of a draft are editable or deletable.
- A stale update does not lose another user's edit.
- Legacy and null data loads unchanged.
- Old clients keep working until the approved cutover.
- No planned line creates an allocation, invoice, budget reservation, or cash event.
- Report formulas, API security, and generated schema keep their documented meanings.
- Every money-affecting mutation has an audit event.

## 16. Rule compliance matrix

Rule IDs refer to the project API standard (legend to be confirmed in WP0).

| Rule ID | Status | Evidence required |
| --- | --- | --- |
| TRN-4, PTH-5, REL-1 | Pass in design | Slashless paths; stable IDs. |
| RW-1, BDY-6/7, ERR-1/3 | Conditional | Distinct serializers; strict keys; correct envelope and status; verify against OpenAPI. |
| RW-5, WRT-9, STR-9 | Conditional | Version-backed strong ETag / `If-Match` on new edit and delete. |
| RW-6, WRT-8 | Conditional | Scoped idempotency records on new creates; existing POST policy needs separate compatibility sign-off. |
| SEC-2, SEC-15/16 | Known existing risk | Global access for authenticated readers and API keys; no department isolation claimed. |
| COL-2/9, PRF-2 | Conditional | Pagination, deterministic ordering, query-budget tests on ≥ 3 rows. |
| VER-2 | Breaking in part | Mandatory fields on existing create routes need client rollout and human approval (D17). |

## 17. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Allocation and draft edits lock in opposite order | Deadlock | WP3 refactor first; concurrency tests. |
| `unit_price = 0` read as free | Understated estimate | M5/M6. |
| Cutover breaks unknown clients | Failed writes | Phase 3 gate; flag default off. |
| API-key writes with `actor=None` | Unattributable money changes | D18 block. |
| Global read access to finance data | Over-exposure | D7/D8 stated; not claimed fixed. |
| Admin deactivates or renames a priority | Existing lines show a changed label | Deactivate, never delete; stable `id` and `code` stored in audit events. |
| Free-text `unit` drifts | Poor reporting later | Trim on input; controlled catalog deferred. |
| Hard delete of lines | Lost history | Audit events (§6.5). |

## 18. Deferred

Need-by date and delivery window, cost center or department scope, budget category, supplier SKU, tax/VAT, attachments, approval workflow, order placement and budget warning, invoice-date recognition, FX, controlled unit catalog, API for managing priorities, backfill of historical purpose/priority/unit.

## 19. Revision history

| Date | Version | Change |
| --- | --- | --- |
| 2026-11-06 | draft | Initial documentation-only design. |
| 2026-11-07 | 0.2 | Restructured; money rules, status matrix, audit, rollout gates. |
| 2026-11-07 | 1.0 | Final. `priority` changed from enum to FK reference table (`PurchasePriority`). Open decisions closed. Added backend agent work packages, stop conditions, definition of done, test plan, flag-based cutover. |
