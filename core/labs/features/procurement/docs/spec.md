# Feature Specification: Procurement Management (`core/labs/features/procurement`)

## 1. Domain Overview & Purpose
The Procurement feature tracks commercial purchasing workflows, supplier relationships, purchase orders, line-item allocations to lab resources, and acquisition cash-flow events.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Purchase`
- **Fields:**
  - `supplier` (CharField(255)).
  - `purchase_order_number` (CharField(100), default="").
  - `purchase_date` (DateField).
  - `currency` (CharField(3), default="EUR").
  - `total_amount` (DecimalField, min 0.00).
  - `status`: Enum (`draft`, `ordered`, `received`, `cancelled`). Default `draft`.
  - `notes` (TextField).

### 2.2 `core.labs.models.PurchaseItem` & `PurchaseItemResource`
- **`PurchaseItem`**: `purchase` (FK `Purchase`, CASCADE), `description`, `quantity` (PositiveIntegerField), `unit_price` (DecimalField), `total_price` (DecimalField).
- **`PurchaseItemResource`**: Polymorphic generic relation linking line items to lab resources:
  - Restricted to: `("labs", "bench")`, `("labs", "equipment")`, `("labs", "license")`, `("labs", "station")`.
  - Allocation `POST` accepts stable `resource_kind` values `bench`, `equipment`, `license`, or `station`; legacy `resource_type_id` remains supported. At least one is required, and both supplied values must agree. Reads return `resource_kind`. There is no kind-discovery endpoint; the enum is published in OpenAPI.

### 2.3 `core.labs.models.PurchaseTransaction`
- Financial ledger entries: `purchase` (FK `Purchase`), `transaction_type` (`payment`, `refund`), `amount`, `transaction_date`.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/procurement/purchases` | `PurchaseListCreateAPIView` | Filtered list of purchase orders. |
| `POST /api/labs/procurement/purchases` | `PurchaseListCreateAPIView` | Create purchase order. |
| `GET /api/labs/procurement/purchases/{id}` | `PurchaseDetailAPIView` | PO detail with line items and transactions. |
| `PATCH /api/labs/procurement/purchases/{id}` | `PurchaseDetailAPIView` | Update purchase order. |
| `POST /api/labs/procurement/purchases/{id}/items` | `PurchaseItemListCreateAPIView` | Add line items and resource allocations. |
| `POST /api/labs/procurement/purchases/{id}/transactions` | `PurchaseTransactionListCreateAPIView` | Record payment/refund. |
