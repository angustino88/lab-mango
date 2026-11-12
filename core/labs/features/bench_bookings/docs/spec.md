# Feature Specification: Bench Bookings (`core/labs/features/bench_bookings`)

## 1. Domain Overview & Purpose
The Bench Bookings feature provides reservation scheduling, scheduling conflict resolution, approval workflow orchestration, and automated lifecycle state machines for lab benches.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Booking` & `BenchBooking`
- **Fields:**
  - `booking_code` (CharField(64), unique, indexed).
  - `bench` (FK `Bench`, PROTECT, related_name="bookings").
  - `starts_at`, `ends_at` (DateTimeField, indexed).
  - `status`: `BookingStatus` (`reserved`, `in_progress`, `completed`, `cancelled`, `expired`).
  - `approval_status`: `BookingApprovalStatus` (`pending`, `approved`, `rejected`).

## Approval threshold

Bookings longer than four hours require approval; bookings of exactly four hours or less are approved by default. If a schedule update extends an approved booking beyond four hours, its approval status returns to `pending` and current approver attribution is cleared so the changed schedule receives a fresh decision. This rule applies to both user updates and agent end-time updates. An edit that results in a duration of four hours or less preserves the current approval status and attribution; shortening a pending booking does not automatically approve it.

Coordinators and administrators can decide pending bookings through explicit approve and reject actions. Nobody, superusers included, may approve or reject a booking they created or that is for them (`requester`); the action returns `403 self_approval_forbidden` and another coordinator or administrator must decide (separation of duties, owner decision 2026-11-12). A decision is allowed only while the booking lifecycle status is `reserved` and the approval status is `pending`; other states return a conflict. Repeating or reversing a completed decision also returns a conflict. Approval sets `approval_status` to `approved`; rejection sets it to `rejected` and requires a trimmed, nonblank reason of at most 500 characters. Both decisions record the coordinator or administrator and decision time in the existing `approved_by` and `approved_at` fields. These fields mean decision actor and time for either outcome; API responses do not expose decision metadata or rejection reason. Approval decisions do not change the booking lifecycle status and do not send notifications.

Both decision actions require an RFC 9562 UUID `Idempotency-Key`, scoped to the authenticated actor, method, canonical action path, and key. Completed successful outcomes are retained for 24 hours. An identical retry replays the original status and body with `Idempotency-Replayed: true`; reusing a key with different input or another action path returns `422 idempotency_key_reuse`. A new key after a decision still conflicts. Validation, authorization, and state-conflict outcomes are not stored. Requests sharing an active scope serialize on a PostgreSQL transaction advisory lock; a waiter replays the committed result rather than returning `409 request_in_progress`.
  - `approved_by` (FK `AUTH_USER_MODEL`, SET_NULL, optional).
  - `project` (FK `LabProject`, SET_NULL, optional).
  - `reason`, `cancellation_reason` (TextField).
- **Invariants:**
  - `ends_after_starts`: `CheckConstraint(ends_at > starts_at)`.
  - Non-Overlapping Bookings: Queries and application validation enforce that no two active bookings for the same bench overlap in time:
    ```sql
    starts_at < target_ends_at AND ends_at > target_starts_at AND status NOT IN ('cancelled', 'expired')
    ```
  - State Machine Immutability: Terminal states (`completed`, `cancelled`, `expired`) cannot transition to any other status.

### 2.2 `core.labs.models.BookingNotification`
- **Fields:** `booking` (FK `BenchBooking`), `notification_type` (`24h_reminder`, `1h_reminder`, `cancelled`, `status_change`), `scheduled_at`, `sent_at`, `error`.

---

## 3. Options Standard Compliance (ADR 002)
`GET /api/labs/bench-bookings/options` provides selector options `{id, sku, name}`.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/bench-bookings` | `BenchBookingCreateAPIView` | Paginated list (`page`, `page_size`, maximum 100); normal users see only bookings they created; lab coordinators and admins see all. `view_side=my_booking` restricts any user to bookings they created. `starts_at_after` and `starts_at_before` filter bookings overlapping a calendar window; the lower bound is inclusive and upper bound exclusive. Bounds accept `YYYY-MM-DD` (midnight in Django `TIME_ZONE`) or offset-aware RFC3339 datetimes. For Nov 2 through Nov 8, use `starts_at_after=2026-11-02&starts_at_before=2026-11-09`. API-key-only callers receive an empty list. Unknown or invalid parameters return `400`. `view_side=booking_calendar` does not bypass role scope. |
| `POST /api/labs/bench-bookings` | `BenchBookingCreateAPIView` | Create booking with overlap validation. |
| `GET /api/labs/bench-bookings/{id}` | `BenchBookingDetailAPIView` | Booking details, with the same object scope as the list: the creator, lab coordinators and admins. Anyone else, including API-key-only callers, receives `404` (no existence oracle). The same applies to `GET /api/labs/bench-bookings/code/{booking_code}`. |
| `PATCH /api/labs/bench-bookings/{id}` | `BenchBookingDetailAPIView` | Reschedule booking times. |
| `POST /api/labs/bench-bookings/{id}/actions/approve` | `BenchBookingApproveActionAPIView` | Approve a pending, reserved booking; coordinator/admin only. Empty body or `{}`. Requires `Idempotency-Key` (UUID). Identical retries replay the original response; new-key repeated decisions return `409`. |
| `POST /api/labs/bench-bookings/{id}/actions/reject` | `BenchBookingRejectActionAPIView` | Reject a pending, reserved booking; coordinator/admin only. Requires `{"reason": "..."}` (trimmed, nonblank, maximum 500 characters) and `Idempotency-Key` (UUID). Identical retries replay the original response; new-key repeated decisions return `409`. |
| `DELETE /api/labs/bench-bookings/{id}` | `BenchBookingDetailAPIView` | Soft delete/cancel booking. |
| `POST /api/labs/bench-bookings/{id}/actions/cancel` | `BenchBookingCancelAPIView` | Cancel reservation with cancellation reason. |
| `POST /api/labs/bench-bookings/{id}/actions/checkin` | `BenchBookingCheckinAPIView` | Check-in command (`reserved` $\to$ `in_progress`). |
| `POST /api/labs/bench-bookings/{id}/actions/checkout` | `BenchBookingCheckoutAPIView` | Check-out command (`in_progress` $\to$ `completed`). |
| `GET /api/labs/bench-bookings/summary` | `BenchBookingSummaryAPIView` | Active, upcoming, and total reservation counts. |
| `GET /api/labs/bench-bookings/options` | `BenchBookingOptionsAPIView` | Selector `{id, sku, name}`. |
