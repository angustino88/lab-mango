# Lab Sessions Feature Architecture

- **Tier:** T2 (new public agent API, cross-feature dependency, agent integration)
- **Status:** Implemented on branch for review; merge requires human approval
- **Date:** 2026-11-11
- **Parent proposal:** [finance and lab analytics](../../../../../docs/proposals/finance-and-lab-analytics.md),
  work packages A1 and A1b, owner decisions O1–O19

## 1. Purpose and scope

`lab_sessions` owns writes to `LabSessionLog`: one record per completed remote session, pushed by the
agent after the user logs out (O1, O13). Before this feature, nothing outside tests and the Django admin
created session logs, so analytics and the leaderboard read a table with no production source.

In scope (A1):

- `record_session_log`, the only write path for session logs.
- `POST /agent/session-logs`, the agent route that calls it.
- Session-log and booking-validation paths published in `GET /agent/info` (O8).

Also delivered with this change (A1b), owned by `bench_bookings`, not by this feature:

- `check_agent_booking_login` and `POST /agent/bookings/actions/validate` (§6).

Out of scope, later work packages: stored session kind and booking, bench and user links (A2); flags,
exclusion and the session list (A6); recompute of links (A10).

## 2. Ownership

| Concept | Owner | Notes |
| --- | --- | --- |
| `LabSessionLog` model | `core/labs/models/session/lab_session.py` | Model package is singular `session`; feature is `lab_sessions` (plural capability name, feature template §5). Transitional naming, recorded here. |
| Session-log writes | `lab_sessions.application` | Only entry point; the agent view calls it through `public.py` |
| Agent authentication and identity | `core.agents` | `AgentSignatureAuthentication`; the computer is `AgentIdentity.equipment` |
| Readers | `analytics`, `leaderboard` | Unchanged by this work package |

Layout: small (`application.py`, `exceptions.py`, `public.py`, `tests/`). There is no `urls.py` or `api/`
package because the only route is an agent route, mounted with the other `/agent/...` routes in
`core/agents/api/urls.py`, following the existing `PATCH /agent/equipment/activity` pattern
(`core/agents/api/views.py`, `AgentActivityAPIView`).

Allowed dependencies: `core.labs.models`; `core.labs.features.lab_sessions.exceptions`. The agent view
imports only `lab_sessions.public`.

## 3. API contract: `POST /agent/session-logs`

Authentication: `X-Agent-*` signed headers. Permission: active enrolled agent. The request never names
equipment.

Request body (O9). Unknown fields are rejected.

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `event_id` | UUID | yes | Agent-generated, unique per session |
| `login_time` | ISO 8601 with offset | yes | |
| `logout_time` | ISO 8601 with offset | yes | After `login_time` |
| `active_duration_seconds` | number ≥ 0 | yes | Not more than logout minus login |
| `remote_user` | string ≤ 255 | yes | Trimmed, non-blank |
| `remote_ip` | IPv4 or IPv6 | no | |
| `remote_host` | string ≤ 255 | no | |
| `booking_code` | string ≤ 64 | no | Null, omitted or blank means temp login (O3, O4) |
| `agent_version` | string ≤ 64 | no | Stored on the record |

Hard limits (O19), checked against the server clock before the transaction:

| Rule | Error field |
| --- | --- |
| `logout_time` ≤ now + 5 minutes | `logout_time` |
| `login_time` ≥ now − 7 days | `login_time` |
| `logout_time` > `login_time` | `logout_time` |
| `active_duration_seconds` ≤ `logout_time` − `login_time` | `active_duration_seconds` |

Responses:

| Status | Code | When |
| --- | --- | --- |
| `201` | — | Stored. Body: `id`, `event_id`, `login_time`, `logout_time`, `booking_code`. |
| `200` | — | Same `event_id` already stored for this agent and computer with the same values. Body is the stored record. |
| `400` | `invalid_request` | Body is not a JSON object |
| `401` | — | Missing, invalid, stale or replayed signature, or agent not active |
| `409` | `session_log_conflict` | Same `event_id` already stored with different values |
| `409` | `equipment_unavailable` | The agent's computer is deleted |
| `422` | `validation_failed` | Unknown field, invalid value or hard limit |
| `429` | — | Per-agent rate limit (`UserRateThrottle`, keyed by agent) |

Not stored: `remote_user_display_name` and `host_name` (O9). `reported_at` is the server receive time.
`computing_equipment` is the agent's enrolled computer.

## 4. Data model, constraints, concurrency

No schema change. Existing constraints used:

| Write path | Race | Guard | Idempotency | Concurrency test |
| --- | --- | --- | --- | --- |
| `record_session_log` | Agent retries the same push, or two retries arrive at once | `unique_session_report_per_agent` (computer, agent id, event id); insert in a savepoint, `IntegrityError` mapped by constraint name only | Natural key (computer, agent id, event id). Replay with equal values returns the stored row; different values raise `SessionLogConflict` | `test_concurrent_identical_pushes_store_one_row` (two threads, PostgreSQL) |

Values compared for replay: `login_time`, `logout_time`, `active_duration_seconds`, `remote_user`,
`remote_ip`, `remote_host`, `booking_code`. Not compared: `agent_version`, `reported_at`.

Other database checks relied on: `labsess_valid_period`, `labsess_active_duration_nonnegative`.

Actor: the agent is not a user, so the record is saved with `actor=None` and has no creator, as in
`sync_computing_activity`. This follows existing agent writes; feature template §4 asks for a scoped
system actor instead (drift, reported in the handoff, not fixed here).

## 5. Read paths

None added. The command performs one equipment read, one insert and, on replay, one read by the unique
key.

## 6. Booking validation (A1b, owned by `bench_bookings`)

`POST /agent/bookings/actions/validate` with body `{"booking_code": "..."}`. Read-only: no check-in, no
status change, no lock.

Eligible when all hold:

1. A bench booking with that code exists.
2. `approval_status` is `approved`.
3. Its bench is the agent computer's active bench (`equipment.public.active_equipment_bench_assignment`).
4. Either `status` is `reserved` and `starts_at` ≤ now < min(`starts_at` + 10 minutes, `ends_at`), or
   `status` is `in_progress` and `starts_at` ≤ now < `ends_at`.

The 10 minutes is `ACTIVATION_WINDOW` (`bench_bookings/application/policies.py`), after which the
reconciliation job expires an unused reservation, so validation and expiry agree. Login before
`starts_at` is not eligible, matching `activate_bench_bookings`.

Responses: `200` with `{"eligible": true, "booking_code", "starts_at", "ends_at", "booked_for"}` where
`booked_for` is the requester's username, or the creator's when no requester is set. `200` with
`{"eligible": false}` and nothing else for every failure. `401`, `422` (blank or overlong code), `429`
as above.

Placement: the pure rule is `policies.is_agent_login_eligible`; the facts are gathered by
`application/check_agent_booking_login.py`, a read-only use case (no transaction, no write), because
queries may not import policies (`tests/architecture/test_labs_boundaries.py`,
`test_queries_do_not_import_application`).

## 7. Authorization and threat notes

- Device-only routes: user and API-key credentials are not accepted.
- The computer comes from the signing identity, so an agent cannot report sessions for, or validate
  bookings on, another computer.
- Validation gives one answer for every failure, so it cannot be used to discover codes or bench
  assignments. The code travels in the signed body, not the URL.
- Session logs contain remote user and remote IP, kept forever (O16, O18).

## 8. Rollout and rollback

Additive: two new routes and two new keys in `GET /agent/info` (`capabilities` values and an `endpoints`
map). No migration. Rollback is a code revert; stored session logs stay valid.

## 9. Test plan

| Criterion | Test |
| --- | --- |
| A session posted twice creates one row | `test_replay_with_same_values_returns_stored_record` |
| Same event id, different values → 409 | `test_same_event_id_with_different_values_conflicts` |
| Computer comes from the agent identity | `test_request_cannot_name_another_computer` |
| Only O9 fields accepted | `test_unknown_fields_are_rejected` |
| Hard limits | `test_hard_limits` (parametrised) |
| Temp login stored without a code | `test_temp_login_has_no_booking_code` |
| Deleted computer → 409 | `test_deleted_computer_is_refused` |
| Concurrent identical pushes | `test_concurrent_identical_pushes_store_one_row` |
| Validation eligibility rules | `bench_bookings/tests/application/test_check_agent_booking_login.py` |
| Validation answers uniformly over HTTP | `core/agents/tests/api/test_agent_booking_validation.py` |
| Published paths | `test_info_publishes_session_and_validation_paths` |

## 10. Decisions and known drift

Owner decisions (2026-11-11), recorded as O20 and O21 in the parent proposal:

1. A user may not log in before the booking's start time (§6, rule 4).
2. Validation does not accept `pending` (or `rejected`) bookings; only `approved` (§6, rule 2).

Known drift, not changed here: `activate_bench_bookings`
(`bench_bookings/application/state_transitions.py:15`) does not filter on approval status, so a pending
booking can still be activated by computing activity. This contradicts O21 and needs its own change.
