# Feature Specification: Expense & Facility Finance (`core/labs/features/expense`)

## 1. Domain Overview & Purpose
The Expense feature manages ongoing operational overhead costs (facility rent, building maintenance, power/cooling utilities, service contracts) associated with physical rooms.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Expense`
- **Fields:**
  - `resource_type` (FK `ContentType`, restricted to `labs.room`), `resource_id` (PositiveBigIntegerField).
  - `name` (CharField(255)).
  - `expense_type`: Enum (`rent`, `utilities`, `maintenance`, `service`, `other`).
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
| `GET /api/labs/rooms/{room_id}/expenses` | `RoomExpenseListCreateAPIView` | List room-scoped expenses. |
| `POST /api/labs/rooms/{room_id}/expenses` | `RoomExpenseListCreateAPIView` | Create expense for a room. |
| `GET /api/labs/rooms/{room_id}/expenses/report` | `RoomFinancialReportAPIView` | Room expenditure metrics report. |
| `POST /api/labs/expenses/{expense_id}/payments` | `ExpensePaymentListCreateAPIView` | Record payment against expense. |
| `GET /api/labs/expenses/report` | `FinancialReportAPIView` | Canonical facilities financial report. |
| `GET /api/labs/financial-report` | `DeprecatedFinancialReportAPIView` | Deprecated alias returning Sunset headers. |
