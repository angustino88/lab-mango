---
applyTo: '**/application/**,**/application.py,**/tasks*.py,**/handlers*.py,**/management/commands/**'
---
# Write safety: transactions, race conditions, idempotency

Owns how a write stays correct when it runs concurrently or more than once. Constraint design:
`database.instructions.md`. Task retries: `async-and-integrations.instructions.md`. HTTP replay and
precondition semantics: response standard RW-5, RW-6, ACT-3. Tests: `testing.instructions.md`.

## 1. Transactions
- One `transaction.atomic()` per command, opened in the command. Never in views, serializers, or queries.
- Checks that need no database (period, duration, input shape) run before the transaction opens.
  Example: `create_bench_booking` calls `policies.ensure_valid_period` before `atomic()`.
- No network call, email, or `task.delay()` inside the transaction or while a row lock is held. Inside: write an
  outbox row. After commit: dispatch. Best-effort only (cache refresh, UI ping): `transaction.on_commit`.
  `on_commit` alone is not durable (`docs/architecture/feature-template.md` section 4, Events).
- An expected `IntegrityError` is caught around a nested `transaction.atomic()` savepoint that wraps only the
  single write, so the outer transaction stays usable (pattern: `bench_bookings/application/create_booking.py`).

## 2. Race conditions: every write path names its guard
| Race | Guard | Repo example |
|---|---|---|
| Two writers create the same "one active X per Y" | conditional `UniqueConstraint` + map the `IntegrityError` by constraint name | `one_active_bench_per_equipment`, `equipment/application/assign_equipment.py` |
| Overlapping time windows on one resource | every writer locks the resource row, then checks overlap | `bench_bookings/application/locks.py` (`lock_benches`) |
| Check dependents, then delete or retire | the delete locks the parent row that every dependent writer also locks | `delete_bench` and `lock_benches` both lock `Bench` |
| Read-modify-write of a number or field | `.update(field=F("field") + 1)`, or `select_for_update()` before the read | |
| Two users edit the same record (lost update) | version column + conditional update; 0 rows → conflict | `support_desk/.../assign_ticket.py` |
| Several workers take jobs from one table | `select_for_update(skip_locked=True)` + lease expiry | `bench_bookings/application/notification_delivery.py` (`claim_one`) |

Rules:
- Check-then-act with no guard from the table is a defect.
  Bad: `if X.objects.filter(key=k).exists(): ... X.objects.create(key=k)` outside a lock or unique constraint.
- Lock several rows in one ordered query: `.select_for_update().filter(pk__in=ids).order_by("pk")`. Never lock
  rows one by one in input order (deadlock).
- Lock order across tables is fixed per feature and written in the lock helper's docstring
  (e.g. stations before bench in `benches/application/services.py::_lock_bench`).
- Map `IntegrityError` by `getattr(exc.__cause__, "diag", None).constraint_name` to a feature exception and
  re-raise everything else. Bad: catching every `IntegrityError` and raising one conflict (hides real bugs);
  matching a substring of `str(error)`.
- `select_for_update()` on a query with `select_related` over a nullable FK needs `of=("self",)`; PostgreSQL rejects
  `FOR UPDATE` on the nullable side of an outer join.

## 3. Idempotency: running it twice leaves the same state and returns the same result
| Operation | How it is idempotent | Repo example |
|---|---|---|
| Set to a target state (assign to the same bench, add favorite) | already in the target state → return the existing row, no new write | `assign_equipment` returns `current`; `add_favorite` uses `get_or_create` |
| State transition | same target → no-op; terminal or disallowed → conflict (ACT-3) | `ensure_booking_status_transition` |
| Client-initiated create or non-idempotent action | `Idempotency-Key` (RW-6), stored with a unique constraint covering the scope (actor + operation) and the key, plus a hash of the request body | target; no compliant implementation yet |
| Task or handler | write keyed on a natural key (`update_or_create`) or a deterministic event id | analytics `update_or_create`; `record_notification` uses `uuid5` |
| Outbox insert | unique (event id, recipient, channel) + `get_or_create` | `support_desk/models/outbox.py` |

Rules:
- The idempotency key is looked up and inserted in the same transaction. If two requests with the same key race,
  the loser catches the `IntegrityError` and returns the stored result instead of failing with 500.
  Same key with a different body hash → `idempotency_key_reuse` (RW-6).
- Dedupe keys come from the input (ids, natural keys, `uuid5` of them), never from `uuid4()` or `now()`.
- `get_or_create` / `update_or_create` are race-safe only when the lookup fields have a unique constraint.

## 4. State transitions
- One transition function per state machine with an explicit allowed map (pattern: `BOOKING_STATUS_TRANSITIONS`
  and `ensure_booking_status_transition` in `core/labs/models/booking/base.py`).
- Lock the row (`select_for_update`) before reading its current status, then transition.
- A bulk `.update(status=...)` filters on the allowed source states in the same query; otherwise call the
  transition function per row.
- Resource lifecycle, booking, assignment, and live activity statuses each have their own transition function
  (AGENTS.md rule 2).
