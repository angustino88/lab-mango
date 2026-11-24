# Feature Specification: Expense & Facility Finance (`core/labs/features/expense`)

## 1. Domain Overview & Purpose
The Expense feature manages ongoing operational costs (facility rent, utilities, maintenance, calibration, repair, service contracts, software license fees, insurance) associated with lab resources (`room`, `station`, `bench`, `equipment`, or `license`).

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Expense`
- **Fields:**
  - `resource_type` (FK `ContentType`, restricted to `EXPENSE_RESOURCE_MODELS`: `labs.room`, `labs.station`, `labs.bench`, `labs.equipment`, `labs.license`), `resource_id` (PositiveBigIntegerField).
  - `name` (CharField(255)).
  - `expense_type`: Enum (`rent`, `utilities`, `maintenance`, `calibration`, `repair`, `service_contract`, `license_fee`, `insurance`, `service`, `other`).
  - `amount` (DecimalField, min 0.01), `currency` (default "EUR").
  - `billing_period`: Enum (`one_time`, `monthly`, `quarterly`, `annual`).
  - `valid_from` (DateField), `valid_until` (DateField, nullable).
- **Constraints:**
  - `expense_valid_dates`: `CheckConstraint(valid_until IS NULL OR valid_until >= valid_from)`.

### 2.2 `core.labs.models.ExpensePayment`
- Disbursed payments: `expense` (FK `Expense`, PROTECT), `transaction_type` (`payment`, `refund`), `amount`, `paid_at`, `reference`.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/expenses` | `ExpenseListCreateAPIView` | List expenses across all resources; filters `resource_kind`, `resource_id`, `expense_type`, `billing_period`. |
| `POST /api/labs/expenses` | `ExpenseListCreateAPIView` | Create an expense linked to a `room`, `station`, `bench`, `equipment`, or `license` via `resource_kind` + `resource_id`. |
| `GET /api/labs/rooms/{room_id}/expenses` | `RoomExpenseListCreateAPIView` | List room-scoped expenses. |
| `POST /api/labs/rooms/{room_id}/expenses` | `RoomExpenseListCreateAPIView` | Create expense for a room. |
| `GET /api/labs/rooms/{room_id}/expenses/report` | `RoomFinancialReportAPIView` | Room expenditure metrics report. |
| `GET/POST /api/labs/expenses/{expense_id}/payments` | `ExpensePaymentListCreateAPIView` | List or record payments/refunds against an expense. |
| `GET /api/labs/expenses/report` | `FinancialReportAPIView` | Canonical financial report; supports `room_id`, `resource_kind`, `resource_id`, `expense_type`, `billing_period`, `status`, `from_date`, `to_date`, `currency`. |
