# Bench slot watches — design and operations

Status: implemented on branch `claude/keen-wozniak-7yx3et`; T2 (new tables, public API, background jobs,
integrations). Needs security + QA review and owner approval before merge. No new dependencies.

## What it does

A signed-in user asks to be notified when a bench frees up inside a time range they choose. The watch
never holds or reserves the bench: whoever books first gets the slot (owner decision 2026-11-26).

| Event (`kind`) | When it fires |
|---|---|
| `slot_ending_soon` | A booking that still reserves the bench and overlaps the range ends within the lead time (default 15 min, `BOOKING_SLOT_WATCH_LEAD_MINUTES`), and the time right after it is free inside the range. |
| `slot_freed` | A booking overlapping the range stops reserving the bench **after the watch was created**: cancelled, expired, rejected, or completed before its booked end. Fires only if a free gap remains in the range. |

"Free" means a gap of at least 5 minutes not covered by any other reserving booking (reserved/in progress and
pending/approved, the same set as the `bench_booking_no_overlap` exclusion constraint). A back-to-back booking
suppresses the event. The watcher's own bookings never trigger events. Messages carry the bench name and the free
window only, never the other user's identity, booking code, project or reason.

Channels are decided by the server, never by the user: every alert goes to the web feed (persisted
`websocket.Notification` + per-user websocket push), to email when email notifications are enabled and the user has
an address, and to Teams (private chat via the existing verified-recipient workflow) when Teams is enabled and the
user has a verified Entra identity.

## API (`/api/labs/bench-slot-watches`, `BENCH_BOOKING_ACCESS`, user-scoped)

| Method & path | Behavior |
|---|---|
| `GET /bench-slot-watches?status=` | Paginated list of the caller's own watches. API-key-only callers get an empty list. |
| `POST /bench-slot-watches` | `{bench_id, starts_at, ends_at}`. Idempotent: the same user/bench/range returns the existing active watch. 201. Range must end in the future, span ≤ 7 days, start within 60 days; ≤ 20 active watches per user (`422 slot_watch_invalid` / `slot_watch_limit`). Unknown bench → 404. API-key-only caller → 403. |
| `GET /bench-slot-watches/{id}` | Caller's own watch; anyone else's → 404 (no existence oracle). |
| `POST /bench-slot-watches/{id}/actions/cancel` | Stop the watch; repeating is a no-op. Others' → 404. |

## Data and invariants

* `labs.BenchSlotWatch`: user, bench, `range_start/range_end`, status
  (`active/cancelled/expired`). DB constraints: range valid, status allowlist, partial unique
  `(user, bench, range_start, range_end) WHERE status='active'`.
* `labs.BenchSlotNotification`: feature-owned outbox on `AbstractOutboxLedger` (lease/state constraints),
  plus channel and kind allowlists. FK `booking` (PROTECT) is the booking whose end/release opened the slot.
* Dedupe: one row per (watch, kind, booking, logical key, channel, recipient). Ending-soon keys include the booking
  end, so an extended-then-ending booking can notify again; freed fires once per booking.

Race guards: create locks the user row (serializes the cap) and relies on the partial unique constraint; cancel
locks the watch row. Collection inserts with `get_or_create` on the unique dedupe key, so re-runs and overlapping
runs insert nothing new. Delivery uses the shared `SKIP LOCKED` lease protocol (120 s lease, 5 attempts,
backoff); web delivery creates the feed entry in the same transaction as the fenced completion, so it is created
exactly once (the websocket push after commit is best effort). Email/Teams are at-least-once as for booking
notifications. Each send revalidates: watch still active, recipient active, and a
free gap still exists — otherwise the row expires with `slot_taken` / is skipped.

## Configuration and rollout

* `BOOKING_SLOT_WATCH_ENABLED` (default false) — master switch; alone it enables web delivery.
* Email/Teams additionally require `BOOKING_NOTIFICATIONS_ENABLED` and the matching
  `BOOKING_NOTIFICATIONS_{EMAIL,TEAMS}_ENABLED` (Teams endpoint/tenant validation is reused unchanged).
* `BOOKING_SLOT_WATCH_LEAD_MINUTES` (1–120, default 15).
* Jobs (queue `BOOKING_NOTIFICATIONS_QUEUE`): `labs.bench_bookings.collect_slot_watch_notifications` every 60 s
  (100 watches per page, keyset continuation; also expires finished watches) and
  `labs.bench_bookings.deliver_slot_watch_notifications` every 15 s (≤ 10 rows per run).
  `provision_booking_notification_schedules` now also provisions these two, disabled by default; `--enable`
  enables each group only when its own configuration is on.
* Rollback: turn the flag off and disable the two schedules; the additive tables stay.

Missed windows are not backfilled: a release older than 15 minutes, or a notice older than 30 minutes (or past the
free window), is not sent.

## Verification (2026-11-26, local PostgreSQL 16, `config.settings.test`)

* `uv run pytest core/labs tests/unit tests/architecture core/common core/websocket -q` — passed (2913).
* New tests: `tests/application/test_slot_watches.py` (commands, availability rules, collection, delivery per
  channel, retries, revalidation, provisioning) and `tests/api/test_slot_watch_api.py` (ownership, contract, codes).
* `makemigrations --check --dry-run` — passed. OpenAPI regenerated; contract rules 0 violations; parity check passed.
* `ruff check` / `ruff format --check` on new files — passed. `mypy` — no findings in new modules (pre-existing
  repository findings elsewhere unchanged).
* Not run: deploy check, Spectral, live email/Teams sends, concurrent-worker load test.
