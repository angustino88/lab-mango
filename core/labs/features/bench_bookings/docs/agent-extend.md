# Design: Agent Booking Extension

- **Tier:** T2 (booking state, concurrency, public agent API)
- **Status:** Proposed; rules E1–E8 need owner confirmation before implementation
- **Date:** 2026-11-11
- **Parent:** [finance and lab analytics proposal](../../../../../docs/proposals/finance-and-lab-analytics.md),
  decisions O20–O26; [lab sessions design](../../lab_sessions/docs/architecture.md) §6

## 1. Problem

A user working at a bench wants more time without leaving the computer. The agent should let them
extend the running booking. Today the command `update_agent_booking_end_time` exists
(`application/update_agent_booking_end_time.py`) but no route exposes it, and it was written before
the agent check-in flow: it takes a booking id, accepts reserved bookings, allows shortening, and sends
a booking longer than 4 hours back to `pending`.

That last rule breaks the agent flow: a pending booking can no longer be checked in (O21), so a user
who extends past 4 hours and then logs out and back in would be locked out of their own session.

## 2. Proposed behavior

`POST /agent/bookings/actions/extend`

```json
{ "booking_code": "BK-7F3K9Q", "ends_at": "2026-11-11T13:00:00+07:00" }
```

| ID | Rule | Reason |
| --- | --- | --- |
| E1 | Only an approved `in_progress` booking on the agent's own bench can be extended. | The user must be checked in at this computer. A reserved booking is changed in the web app. |
| E2 | The new end must be later than the current end. Shortening is not extension: the user ends the booking instead (O25). | One meaning per action. |
| E3 | The current end must not have passed. | After the end time the scheduled job completes the booking (O26). |
| E4 | The new end must not overlap another reserved or in-progress booking on the bench. | Existing overlap guard (`conflicting_bench_bookings`), under the bench lock. |
| E5 | The total booking (start to new end) may not exceed the approval threshold, 4 hours (`LONG_BOOKING_APPROVAL_THRESHOLD`). Longer bookings are requested in the web app and approved by a coordinator. | Keeps the booking approved, so re-login keeps working (O21), and keeps the approval rule meaningful. |
| E6 | The new end is rounded to whole minutes and must be at least 10 minutes after the current end. | Matches `MIN_BOOKING_DURATION`; avoids many tiny extensions. |
| E7 | Repeating the call with the same end time succeeds without a write. | Safe retry. |
| E8 | A successful extension records an `updated` notification. | Same as every other end-time change. |

### 2.1 Responses

The agent needs to tell the user *why* an extension failed, unlike check-in, where every failure
looks the same. Failures are split in two:

| Status | Body | When |
| --- | --- | --- |
| `200` | `extended: true`, `booking_code`, `starts_at`, `ends_at` | Extended (or E7 repeat) |
| `200` | `{"extended": false}` only | The code is unknown, on another bench, not approved, or not in progress (E1). Same answer for all, as for check-in. |
| `409` `bench_not_free` | `details`: `available_until` (the next booking's start) | E4: the agent can offer the user the longest possible extension |
| `422` `extension_not_allowed` | `details`: field `ends_at` and a reason: `not_later`, `already_ended`, `too_short`, `needs_approval` (with `max_ends_at`) | E2, E3, E6, E5 |
| `401`, `429` | | As for the other agent routes |

Revealing `available_until` and `max_ends_at` is safe: they are only returned after the booking is
proven to be in progress on the agent's own bench.

## 3. Implementation outline

- New command `extend_agent_booking(ExtendAgentBookingInput(agent_uid, booking_code, ends_at), actor=...)`
  in `bench_bookings/application/extend_agent_booking.py`, using `lock_agent_booking` (identity →
  equipment → bench → booking), so check-in, end and extend share one lock order.
- Pure rules `policies.ensure_agent_extension(...)` for E2, E3, E5 and E6; the conflict check (E4) runs
  under the bench lock.
- `update_agent_booking_end_time` has no caller. Once extend ships, remove it in a separate change
  (public export; check for external callers first).
- `GET /agent/info` adds `booking_extend`.

| Write path | Race | Guard | Idempotency | Concurrency test |
| --- | --- | --- | --- | --- |
| `extend_agent_booking` | Extension against a new booking created on the same bench; two extensions at once | Bench lock taken by every booking writer, then overlap check; booking row lock | Same `ends_at` returns unchanged (E7) | Extension and a conflicting create in two threads: exactly one succeeds |

## 4. Tests (planned)

E1–E8 each as command tests; HTTP tests for the four response shapes; the concurrency test above;
re-login after extension still checks in (O21 not broken).

## 5. Decisions needed from the owner

1. E1: extend only in-progress bookings (recommended), or also reserved ones?
2. E5: cap at the 4-hour approval threshold (recommended), or allow longer and keep the booking
   approved, bypassing coordinator approval for agent extensions?
3. E6: minimum step of 10 minutes; any maximum per extension?
4. May the user extend more than once (recommended: yes, within E5)?
