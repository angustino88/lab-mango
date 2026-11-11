# Design: Agent Booking Extension

- **Tier:** T2 (booking state, concurrency, public agent API)
- **Status:** Implemented on branch `claude/loving-hopper-n5grpk` (PR #6), rules confirmed by the owner (decision O28); merge requires human approval
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
| E6 | Seconds are dropped from the new end, which must be at least 10 minutes after the current end. No maximum per extension; the user may extend repeatedly within E5. | Matches `MIN_BOOKING_DURATION`; avoids many tiny extensions. |
| E7 | Repeating the call with the same end time succeeds without a write. | Safe retry. |
| E8 | A successful extension records an `updated` notification. | Same as every other end-time change. |

### 2.1 Responses

The agent needs to tell the user *why* an extension failed, unlike check-in, where every failure
looks the same. Failures are split in two:

| Status | Body | When |
| --- | --- | --- |
| `200` | `extended: true`, `booking_code`, `starts_at`, `ends_at` | Extended (or E7 repeat) |
| `200` | `{"extended": false}` only | The code is unknown, on another bench, not approved, or not in progress (E1). Same answer for all, as for check-in. |
| `409` `bench_not_free` | `details[0]`: `field` `ends_at`, `code` `bench_not_free`, `limit` = the next booking's start | E4: the agent can offer the user the longest possible extension |
| `422` `extension_not_allowed` | `details[0]`: `field` `ends_at`, `code` = `already_ended`, `not_later`, `too_short` (`limit` = earliest accepted end), `needs_approval` (`limit` = latest accepted end) or `bench_not_in_service` | E3, E2, E6, E5; bench out of service |
| `422` `validation_failed` | Field errors | Unknown field, missing or invalid value |

Each error detail is `{field, code, message, limit}` (`AgentBookingExtendErrorSerializer`): `code` is
machine-stable (ERR-2) and `limit` is null when no time applies.
| `401`, `429` | | As for the other agent routes |

Revealing these limits is safe: they are only returned after the booking is
proven to be in progress on the agent's own bench.

## 3. Implementation outline

- New command `extend_agent_booking(ExtendAgentBookingInput(agent_uid, booking_code, ends_at), actor=...)`
  in `bench_bookings/application/extend_agent_booking.py`, using `lock_agent_booking` (identity →
  equipment → bench → booking), so check-in, end and extend share one lock order.
- Pure rules `policies.ensure_agent_extension(...)` for E2, E3, E5 and E6; the conflict check (E4) runs
  under the bench lock. A bench that is not in service refuses with `bench_not_in_service`.
- `update_agent_booking_end_time` has no caller. Once extend ships, remove it in a separate change
  (public export; check for external callers first).
- `GET /agent/info` adds `booking_extend`.

| Write path | Race | Guard | Idempotency | Concurrency test |
| --- | --- | --- | --- | --- |
| `extend_agent_booking` | Extension against a new booking created on the same bench; two extensions at once | Bench lock taken by every booking writer, then overlap check; booking row lock | Same `ends_at` returns unchanged (E7) | Extension and a conflicting create in two threads: exactly one succeeds |

## 4. Tests (planned)

E1–E8 each as command tests; HTTP tests for the four response shapes; the concurrency test above;
re-login after extension still checks in (O21 not broken).

## 5. Owner decisions (2026-11-11, O28)

1. E1: only in-progress bookings can be extended.
2. E5: the total booking is capped at the 4-hour approval threshold; longer bookings go through the web
   app and coordinator approval.
3. E6: at least 10 minutes per extension, no maximum.
4. A user may extend more than once, within E5.

## 6. Implementation

- Command: `application/extend_agent_booking.py`; rule: `policies.ensure_agent_extension`; errors:
  `AgentExtensionNotAllowed`, `AgentExtensionBenchNotFree` (`exceptions.py`).
- Route: `POST /agent/bookings/actions/extend` (`core/agents/api/views.py`, `AgentBookingExtendAPIView`).
- Tests: `tests/application/test_extend_agent_booking.py` (E1–E8, the race with a new booking, re-login
  after extension) and `core/agents/tests/api/test_agent_booking_validation.py` (HTTP shapes).
