# Design: Stock items (counted equipment)

- Tier: T2 · Status: Draft, owner answers recorded below, not approved for implementation · Date: 2026-11-10
- Domain: Labs (`core/labs/features/stock`, a feature that does not exist yet)
- Related: [equipment management redesign](equipment-management-redesign.md) owns individually tracked
  equipment (lifecycle state, condition, placement). This document does not change it.

Statements marked **Evidence** were read from the repository on the date above. Everything else is **Proposed**.

## Problem and acceptance criteria

Some things the lab keeps are interchangeable and only their number matters (cables, adapters, probes,
connectors). Recording each piece as an `Equipment` record is busywork, and a `quantity` field on
`Equipment` would break everything that is per item (placement, condition, calibration, licences,
bookings, loans, history): with one record for ten cables, nothing can say which two are broken.

| # | Criterion |
|---|---|
| AC1 | A kind of equipment is either tracked per item (`Equipment`) or counted (stock), never both, so nothing is counted twice. |
| AC2 | The quantity of a stock item at a location can never go below zero, including under concurrent requests (PostgreSQL guard). |
| AC3 | Every change to a quantity is an append-only movement with actor, time, reason, and reference. |
| AC4 | A retried request never applies a movement twice. |
| AC5 | Receiving stock against a purchase item reuses its price; stock stores no price of its own. |
| AC6 | Items at or below their reorder level are listed; no notification is sent (owner answer 6). |
| AC7 | A room, station, or bench that still holds stock cannot be deleted. |

## Owner answers recorded (2026-11-10)

| # | Question | Answer | Consequence |
|---|---|---|---|
| A1 | Which items are counted? | Hard to list: categories exist, and only some things in them are countable. | Counting is chosen per **equipment kind**, not per category (see below). |
| A2 | Fractional quantities (metres of cable)? | Not needed. | Whole numbers only (`PositiveIntegerField`); the unit is always pieces. |
| A5 | Stock value / cost? | Price already exists. | **Evidence:** `PurchaseItem` has `quantity` and `unit_price` (`core/labs/models/procurement/purchase.py`). A receipt references its purchase item; stock adds no price field. |
| A6 | Low-stock notification? | Show in a list first; notifications decided later. | Filter `below_reorder=true`; no task, no notification. |

Not answered yet; the defaults below apply until the owner decides:

| # | Question | Default in this design |
|---|---|---|
| Q3 | Are issued items used up, or lent and returned? | Both movements exist: `issue` (leaves stock) and `return` (comes back). No per-person outstanding balance. |
| Q4 | Stock per department or lab-wide? | `StockItem.department` is optional, like `Equipment.department`; writes use the global coordinator role until department scope (redesign OD9) exists. |

## Current state (from repository evidence)

- The equipment catalog has category, kind, type, manufacturer, and product model
  (`core/labs/models/resource/equipment/reference_data.py`). Nothing marks a kind as countable.
- `Equipment` is one record per physical item. Its placement, condition, and history are per item.
- `PurchaseItem` stores `quantity`, `unit_price`, and a free-text `unit`. `PurchaseItemResource` allocates a
  purchase item to an individually tracked resource with an `acquisition_price`.
- Locations: `Room` > `Station` (in a room slot) > `Bench` (in a station slot). Room and station deletes
  already refuse while equipment is placed there.

## Proposed behavior and invariants

### Choosing what is counted

`EquipmentKind` gains `tracking` = `individual` (default) or `quantity`, writable by administrators only
(redesign OD12). Example, category *Accessory*: kind *HDMI cable* is `quantity`, kind *Docking station* is
`individual`.

- Creating an `Equipment` record with a `quantity` kind is refused; creating a `StockItem` with an
  `individual` kind is refused (AC1).
- Changing a kind's tracking is refused while records of the other kind exist for it.

### Model

| Model | Fields | Rules |
|---|---|---|
| `StockItem` | `kind` (FK, `tracking = quantity`), optional `type`, `manufacturer`, `product_model`, `name`, `part_number`, `reorder_level` (int, default 0), optional `department`, `active` | catalog row; administrators and coordinators per the role decision below |
| `StockBalance` | `stock_item`, exactly one of `room` / `station` / `bench`, `bin` (text, optional, e.g. "Shelf B"), `quantity` (int) | written only by the movement command; `stock_balance_non_negative` CHECK `quantity >= 0`; `stock_balance_one_per_place` UNIQUE (`stock_item`, `room`, `station`, `bench`, `bin`) with `NULLS NOT DISTINCT` (PostgreSQL 15+) |
| `StockMovement` | `stock_item`, `kind`, `quantity` (> 0), `from_balance`, `to_balance`, `reason`, optional `purchase_item`, optional `project`, `actor`, `occurred_at`, `idempotency_key` | append-only; CHECK per kind on which side is set (below); UNIQUE (`actor`, `idempotency_key`) |

| Movement kind | From | To | Notes |
|---|---|---|---|
| `receive` | none | balance | `purchase_item` optional; total received for a purchase item cannot exceed its `quantity` |
| `issue` | balance | none | handed out or used up; `project` optional |
| `return` | none | balance | something issued comes back |
| `transfer` | balance | balance | different places |
| `adjust` | balance or none | none or balance | stocktake correction; `reason` required |
| `write_off` | balance | none | broken or lost; `reason` required |

Why a ledger and a balance: the ledger alone cannot guard "never below zero" in the database and makes
every read a sum; a balance alone has no history and loses concurrent updates. Together they give an
audit trail, fast reads, and a PostgreSQL guarantee.

### Write path

| Write path | Race | Guard (constraint name / lock order) | Idempotency | Concurrency test |
|---|---|---|---|---|
| `record_stock_movement` | two issues of the last piece; balance row created twice | get-or-create balance rows inside a savepoint (`stock_balance_one_per_place`), then lock them ordered by pk; `UPDATE ... quantity = quantity ± n`; `stock_balance_non_negative` maps to `insufficient_stock` (409) | `Idempotency-Key` header required (request standard RW-6); same key and body returns the stored movement, different body returns `idempotency_key_reuse` | two concurrent issues of the last piece: one 201, one 409 |
| receive against a purchase item | over-receiving | lock the `PurchaseItem` row, then balances; sum of receipts ≤ `PurchaseItem.quantity` | as above | two concurrent receipts beyond the ordered quantity: one refused |
| change `EquipmentKind.tracking` | records created while switching | lock the kind row; refuse if records of the other kind exist; equipment and stock creation lock the kind row too | same value is a no-op | switch racing a create |
| delete room / station / bench | stock arriving during delete | delete locks the location row; movements lock the same row before creating a balance there | already deleted is a no-op | delete racing a receipt |

Lock order: `PurchaseItem`, then location rows, then `StockBalance` rows by pk.

## API contract (endpoints, errors, breaking?)

New routes only; nothing existing changes except `EquipmentKind` gaining a `tracking` field.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/labs/stock-items` · `GET .../{id}` | authenticated | catalog with total quantity |
| `POST /api/labs/stock-items` · `PATCH .../{id}` | administrator (catalog) | create, rename, set reorder level |
| `GET /api/labs/stock-balances` | authenticated | filters: `stock_item`, `room`, `station`, `bench`, `below_reorder=true` |
| `POST /api/labs/stock-movements` | coordinator | receive, issue, return, transfer, adjust, write off; `Idempotency-Key` required |
| `GET /api/labs/stock-movements` | authenticated | history; filters: `stock_item`, `kind`, location, `purchase_item`, date range |

Errors: `insufficient_stock` (409), `over_received` (409), `invalid_tracking` (422), validation (422),
not found (404), permission denied (403), `idempotency_key_reuse` (422).

## Read paths and query budget

| Endpoint | Query | Budget | Page cap |
|---|---|---|---|
| stock items | annotate total quantity (`Sum` over balances) | page + count = 2 | 100 |
| balances | join item and location | 2 | 100 |
| below reorder | balances grouped by item, `HAVING SUM(quantity) <= reorder_level` | 2 | 100 |
| movements | join item, balances, actor | 2 | 100 |

Stock value (when needed): quantity received × `PurchaseItem.unit_price`, reported per receipt; no
valuation method (average, FIFO) in the first version.

## Authorization and threat notes

- Movements: coordinator role (global until department scope exists). Catalog and `EquipmentKind.tracking`:
  administrators (redesign OD12). Reads: authenticated users.
- `reason`, `bin`, and names are length-capped and rendered as text, never HTML.

## Migration, rollout, rollback

- One migration: `EquipmentKind.tracking` (default `individual`, so nothing changes until an
  administrator marks a kind) and the three new tables. Development database: no data to convert.
- Rollback: remove the routes; the tables are additive.

## Phasing

1. `tracking` on kinds; catalog, balances, receive / issue / return / transfer / adjust / write off; below-reorder list.
2. Purchase-item receipts with the over-receiving guard; stocktake sessions (count a whole location, post the differences as adjustments).
3. Low-stock notifications (owner decides later) and stock value reporting, if finance asks.

## Test plan (criterion → test)

| Criterion | Test |
|---|---|
| AC1 | equipment create refused for a `quantity` kind and stock item refused for an `individual` kind; tracking change refused while records exist |
| AC2 | issue more than on hand returns 409; two concurrent issues of the last piece: one wins (PostgreSQL) |
| AC3 | every command writes one movement; balances equal the sum of movements |
| AC4 | same `Idempotency-Key` twice applies once; same key, different body returns 422 |
| AC5 | receipt references a purchase item; receipts beyond its quantity refused |
| AC6 | `below_reorder=true` lists exactly the items at or below their level |
| AC7 | deleting a room, station, or bench with stock returns 409 |

## Alternatives considered

| Alternative | Why not |
|---|---|
| `quantity` field on `Equipment` | per-item facts (placement, condition, loans, licences, history) cannot be told apart |
| Counted or individual per category | owner answer A1: one category mixes both |
| Counted or individual per product model | many counted things have no product model; kind is the level administrators already manage |
| Balance table only | no history; concurrent edits overwrite each other |
| Ledger only, sum on read | cannot guard "never below zero" with a constraint; slower reads |
| Separate price on stock items | owner answer A5: price already lives on the purchase item |

## Open questions / decisions needed from the owner

1. Q3: are issued items used up, lent and returned, or both? (Default: both movements, no per-person balance.)
2. Q4: is stock held per department, or lab-wide? (Default: optional department on the item.)
3. Who creates stock items: administrators only (like the equipment catalog), or coordinators too?
4. Approve the per-kind `tracking` switch as the way to choose what is counted.
