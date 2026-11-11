# Bench Booking Architecture

**Status:** Proposed. This document is located at the feature-local documentation path specified as `CONFIRM` in `docs/ai-team/documentation-map.md`; owner confirmation is required.

## Scope

`core.labs.features.bench_bookings` owns creation, updates, conflict detection, and lifecycle transitions for the existing `labs.BenchBooking` model. It does not own computing-activity ingestion, equipment assignment, or project lifecycle.

It also owns approval decisions for pending bench bookings. Dedicated approve and reject commands authorize only lab coordinators and administrators, lock the bench before the booking (the same order used by schedule writers), then recheck the state while locked. A decision is valid only for a `reserved` booking whose approval status is `pending`. Approval and rejection are an independent state machine from booking lifecycle. Both outcomes record the acting coordinator/admin and decision timestamp using the existing `approved_by` and `approved_at` fields; rejection additionally stores a required nonblank reason (maximum 500 characters). Repeated or reverse decisions conflict. The commands do not change lifecycle status or emit notification intents. The database overlap exclusion constraint remains the final guard; pending bookings already reserve their bench interval, so approval does not newly claim a reservation.

Approve/reject API actions require a UUID `Idempotency-Key` and retain completed success receipts for 24 hours. The receipt is scoped to actor, method, canonical action path, and key, and stores the request fingerprint and original success status/body. A transaction-scoped PostgreSQL advisory lock serializes same-key attempts before receipt lookup; the decision, response projection, and receipt are committed atomically. A matching retry replays the stored response; a different request under the same key is rejected. A concurrent waiter replays the committed result instead of returning `409 request_in_progress`. A distinct key against an already-decided booking continues to conflict. Failed validation or state transitions do not create receipts. Expired records are removed when the same key scope is reused.

All public booking codes are opaque SHA-256-derived identifiers. The generator includes a cryptographically random nonce; the `Booking.booking_code` database unique constraint remains the durable system-wide uniqueness guard. Creation retries a booking-code uniqueness collision at most three times.

Booking creation and updates require a minimum duration of 10 minutes. A start time may be up to 10 minutes in the past.

## Verified Model Ownership

- `labs.BenchBooking` is the concrete booking record and inherits shared fields and statuses from `labs.Booking`.
- `labs.ComputingActivity` owns the current state and booking code reported by a computing resource.
- `labs.EquipmentAssignment` owns the active relationship from equipment to a bench.
- `labs.Bench` owns the booked resource.

The activity-to-booking association is resolved through the existing chain:

```mermaid
flowchart LR
    Activity["ComputingActivity"] --> Computing["Equipment (with ComputingProfile)"]
    Computing --> Assignment["EquipmentAssignment"]
    Assignment --> Bench["Bench"]
    Activity --> Code["booking_code"]
    Code --> Booking["BenchBooking"]
    Bench --> Booking
```

An activity can activate a booking only when all of these are true:

1. The computing activity status is `active`.
2. The activity carries a non-empty booking code.
3. The computing equipment has an active assignment to the booking's bench.
4. The booking code identifies a `reserved` booking for that bench.
5. The current time falls in the booking interval: `$starts_at \le now < ends_at$`.

## State Machine

```mermaid
stateDiagram-v2
    [*] --> reserved: create
    reserved --> in_progress: active computing activity with matching assignment and booking code
    reserved --> cancelled: cancel command
    reserved --> expired: no activation by start + 10 minutes
    in_progress --> completed: end time reached
    in_progress --> cancelled: cancel command
    expired --> [*]
    completed --> [*]
```

The lifecycle command is idempotent: every transition targets its source status. A subsequent invocation updates zero rows after a prior successful transition.

The shared transition policy is deny-by-default: terminal `completed`, `cancelled`, and `expired` bookings cannot transition to `reserved` or any other status. `in_progress` bookings can move only to `completed` or `cancelled`.

## Application Interface

### Agent end-time update

The agent end-time command resolves `agent_uid` through `agents.public.require_active_agent_identity`;
it never accepts a caller-supplied equipment identifier. This identifies the credential subject only;
it is not API authentication and does not replace transport authentication. It derives the identity's
equipment and locks that equipment through `equipment.public.lock_active_equipment_bench_assignment`,
which returns an immutable projection of its active equipment-to-live-bench binding. The booking must
belong to that bound bench. These are reviewed internal boundaries, not HTTP endpoints.

The transaction's explicit lock order is **agent identity → equipment → bench → booking**. Identity
validation holds its row lock through the outer command transaction, preventing revocation from
racing past the subject lookup. Equipment assignment and unassignment writers lock the equipment
row before modifying assignment rows, so holding that same owner-row lock keeps the authorized
binding stable until this command commits. The existing assignment write paths lock equipment before
bench. This command does not lock an assignment row first and therefore avoids reversing that order.
Booking conflict checks remain protected by the bench lock and database overlap guard.

An unchanged end time is a no-op for persistence and notification intent creation. This does not make distinct
changed requests idempotent, and `request_id` is not persisted as an audit record here. No durable
audit or notification-delivery guarantee is claimed.

### Agent booking login check

`check_agent_booking_login(CheckAgentBookingLoginInput(equipment_id, booking_code), now=None)` answers
`POST /agent/bookings/actions/validate`. It is a read-only use case: no transaction, lock, check-in or
status change. `equipment_id` is the signing agent's computer, set by the agent view, never the body.

It returns an `AgentBookingLogin` (`booking_code`, `starts_at`, `ends_at`, `booked_for`) when the pure rule
`policies.is_agent_login_eligible` holds, otherwise `None` for every failure:

- the booking is approved and on the computer's active bench
  (`equipment.public.active_equipment_bench_assignment`);
- a `reserved` booking is inside `scheduled_start_is_due` (start to start + 10 minutes, the moment
  reconciliation would expire it); an `in_progress` booking is before its end.

Two queries: the booking with `requester` and `creator`, and the computer's active bench. `booked_for`
is the requester's username, or the creator's when no requester is set. Design and tests:
[lab sessions architecture](../../lab_sessions/docs/architecture.md#6-booking-validation-a1b-owned-by-bench_bookings).

### Agent check-in

`check_in_agent_booking(CheckInAgentBookingInput(agent_uid, booking_code), actor=..., now=None)` answers
`POST /agent/bookings/actions/check-in`. It applies `policies.is_agent_login_eligible`, then moves a
`reserved` booking to `in_progress` through `ensure_booking_status_transition`; an `in_progress` booking is
returned unchanged. Lock order is **agent identity → equipment → bench → booking**, the same as the agent
end-time command. Every failure returns `None`, and no notification is recorded (owner decision O24).

### Agent end booking

`complete_agent_booking(CompleteAgentBookingInput(agent_uid, booking_code), actor=...)` answers
`POST /agent/bookings/actions/complete`, called only when the user chooses to end the booking (owner
decision O25). An approved `in_progress` booking on the agent's bench moves to `completed` and records an
`updated` notification; a `completed` booking is returned unchanged; anything else returns `None`.
`ends_at` is kept. Check-in and end share `application/agent_booking_locks.py::lock_agent_booking`
(identity → equipment → bench → booking). Completion at the end time stays with
`reconcile_bench_booking_statuses`, scheduled as `labs.bench_bookings.reconcile_statuses` (O26).

### Agent extend

`extend_agent_booking(ExtendAgentBookingInput(agent_uid, booking_code, ends_at), actor=..., now=None)` answers
`POST /agent/bookings/actions/extend` (owner decision O28). Rules, responses and tests:
[agent-extend.md](agent-extend.md). It uses the shared `lock_agent_booking`; the bench lock makes it and
`create_bench_booking` serialise on the overlap check. The older `update_agent_booking_end_time` has no
caller and can be removed in a separate change.

`application/state_transitions.py` exposes the supported lifecycle commands:

- `activate_bench_booking_for_computing_activity(computing_id, now)`: resolves the activity-to-bench relationship and activates the matching booking.
- `activate_bench_bookings(bench_id, booking_code, now)`: smaller verified-facts command that performs the `reserved -> in_progress` transition. Only approved bookings are activated; pending and rejected bookings stay `reserved` (owner decision O21, 2026-11-11). Neither activation command has a production caller yet; agent check-in uses `check_in_agent_booking`.
- `reconcile_bench_booking_statuses(now)`: expires overdue reserved bookings and completes elapsed in-progress bookings.

Each command uses an atomic database transaction and locks the booking rows before updating their status.

## API Lookup

The feature supports numeric and public-code detail routes:

- `GET` and `PATCH` `/api/labs/bench-bookings/<booking_id>`
- `GET` and `PATCH` `/api/labs/bench-bookings/code/<booking_code>`

The public-code route resolves the booking internally and delegates updates to the same application command as the numeric route. Missing codes return the standard not-found response.

Numeric booking routes also expose `POST /api/labs/bench-bookings/<booking_id>/actions/approve` and `/actions/reject`. Both are restricted at the API and command layers to coordinators/admins; rejection requires a trimmed, nonblank reason of at most 500 characters. Action requests lock bench then booking and validate `reserved` + `pending` after acquiring the locks. The existing booking response shape remains unchanged and does not reveal decision actor/time or the stored rejection reason.

Creation requires a nonblank `reason` and a valid `project`. PATCH accepts partial schedule, bench, reason, project, and status updates. A status update is allowed only when the shared booking state machine permits that transition.

`in_progress` and `expired` are system-managed and cannot be submitted through PATCH. Only confirmed computing activity may transition a reserved booking to `in_progress`; only scheduled reconciliation may transition a reserved booking to `expired` after its activation grace window passes.

## Scheduled Reconciliation

`tasks.py` defines the Celery task name `labs.bench_bookings.reconcile_statuses`. It must run at least once per minute for timely lifecycle transitions: it expires reservations nobody checked in to (10 minutes after start) and completes bookings whose end time has passed (owner decision O26).

- **Discovery:** `core/labs/tasks.py` imports the task, so worker autodiscovery registers it.
- **Schedule (code-owned, 2026-11-11):** `CELERY_BEAT_SCHEDULE["bench-booking-status-reconciliation"]` in `config/settings/base.py`, every 60 seconds (`BENCH_BOOKING_RECONCILE_INTERVAL_SECONDS`). django-celery-beat's database scheduler copies the entry into its Periodic Tasks each time beat starts, so no manual step is needed per environment. An admin may disable it in Django admin; beat keeps it disabled.
- **Tests:** `tests/unit/test_celery_beat_schedule.py`.

## Guarantees and Constraints

- Time intervals use the half-open convention `$[starts_at, ends_at)$`.
- Status transitions only occur from their valid source state.
- Booking status updates do not call model-level business workflows; lifecycle orchestration remains in the booking application layer.
- The scheduler may run on multiple workers because source-status filters make repeated reconciliation safe.

## Testing and Operations

Required PostgreSQL tests:

- active activity on an assigned computing resource activates the matching reservation;
- inactive, missing-code, wrong-bench, future, and elapsed activity does not activate a booking;
- exact ten-minute expiration boundary and the instant before it;
- exact end-time completion boundary and the instant before it;
- duplicate task invocation is idempotent;
- concurrent activity activation and reconciliation preserve a valid terminal state.

The current focused database tests are blocked before execution by the existing test-database migration issue: `common_apilog.creator_id` references a missing `users_user` table. Static lint, formatting, and byte-compilation must be rerun after lifecycle changes.
