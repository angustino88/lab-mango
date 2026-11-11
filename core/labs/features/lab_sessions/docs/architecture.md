# Lab Sessions Feature Architecture

- **Tier:** T2 (new public agent API, cross-feature dependency, agent integration)
- **Status:** Implemented on branch for review; merge requires human approval
- **Date:** 2026-11-11
- **Parent proposal:** [finance and lab analytics](../../../../../docs/proposals/finance-and-lab-analytics.md),
  work packages A1, A1b and A2, owner decisions O1–O23

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

A2 (§11) adds the stored access type and the booking, bench and user links.

Out of scope, later work packages: flags, exclusion and the session list (A6); recompute of links after
master-data corrections (A10).

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

### 6.1 Check-in (O24)

`POST /agent/bookings/actions/check-in` takes the same body and applies the same eligibility rule as
validation, then writes:

| Booking status | Result |
| --- | --- |
| `reserved`, inside its window | Moves to `in_progress`; `checked_in: true` |
| `in_progress`, before its end | No change; `checked_in: true` (the user logged in again) |
| anything else | No change; `{"checked_in": false}` and nothing else |

| Write path | Race | Guard | Idempotency | Concurrency test |
| --- | --- | --- | --- | --- |
| `check_in_agent_booking` | Two check-ins with one code (two computers on the bench, or a retry); a booking edit or cancel at the same moment | Lock order identity → equipment → bench → booking, as `update_agent_booking_end_time`; the booking row lock makes the transition happen once | Target state: an `in_progress` booking is returned unchanged | `test_concurrent_check_ins_start_the_booking_once` |

No notification is recorded, matching `activate_bench_bookings`. Validation remains for an agent that
wants to check a code without starting the booking.

### 6.2 Ending a booking (O25, O26)

`POST /agent/bookings/actions/complete` (`bench_bookings.complete_agent_booking`) is called only when the
user chooses to end the booking, never at logout, so a user who logs out and back in keeps the booking.

| Booking status | Result |
| --- | --- |
| `in_progress`, approved, on this computer's bench | Moves to `completed`; `ends_at` is kept; an `updated` notification is recorded, as for the web app's complete action |
| `completed` | No change; `completed: true` (a retry) |
| anything else | No change; `{"completed": false}` and nothing else |

Race guard: the same lock sequence as check-in (`lock_agent_booking`). Bookings nobody ends are completed
at their end time by the bench-booking feature's scheduled job, `labs.bench_bookings.reconcile_statuses`
(O26). A completed booking cannot be checked in again.

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

Resolved 2026-11-11: `activate_bench_bookings` (`bench_bookings/application/state_transitions.py`) now
activates only approved bookings, so activation and agent validation apply the same O21 rule.

Resolved 2026-11-11 (O24): the agent now checks in through `POST /agent/bookings/actions/check-in`
(`bench_bookings.check_in_agent_booking`), which moves a reserved booking to `in_progress`. The older
`activate_bench_bookings` and `activate_bench_booking_for_computing_activity` still have no production
caller; they are left in place for the activity-driven path.

## 11. A2: access type and session links

### 11.1 Owner decisions

| ID | Decision |
| --- | --- |
| O22 | The session kind is stored as `access_type` with values `booked` ("Booked"), `ad_hoc` ("Ad hoc (no booking)") and `unverified_booking` ("Booking not verified"). |
| O23 | A session links to an app user when its remote login name, ignoring case and any `DOMAIN\` prefix, equals exactly one active username. Otherwise the user link stays empty. |

### 11.2 Fields on `LabSessionLog`

| Field | Type | Delete rule | Meaning |
| --- | --- | --- | --- |
| `access_type` | `CharField(32)`, choices `SessionAccessType`, nullable | — | How the user got access. Null only on rows stored before A2 and not yet backfilled. |
| `booking` | FK `BenchBooking`, nullable | `SET_NULL` | The verified booking; set only when `access_type` is `booked`. |
| `bench` | FK `Bench`, nullable | `SET_NULL` | The bench the computer was placed on at login time. |
| `user` | FK user, nullable | `SET_NULL` | The app user resolved from `remote_user` (O23). |

`SET_NULL` because the session stays valid history without the target (model conventions §5), and
bench and booking deletion paths must keep working (AGENTS.md rule 1). Raw values (`booking_code`,
`remote_user`, computer) are kept, so a link can be recomputed.

### 11.3 Resolution at ingestion

Resolved once, inside `record_session_log`, from facts read before the insert:

1. **Bench:** the computer's bench placement covering `login_time`
   (`assigned_at` ≤ login < `unassigned_at`, or still active), through `equipment.public`.
2. **Access type and booking:**
   - no booking code → `ad_hoc`;
   - code matches a bench booking that is approved, not cancelled, on the resolved bench, with
     `starts_at` ≤ `login_time` < `ends_at` → `booked`, with the booking linked;
   - any other code → `unverified_booking`, no booking linked.

   `expired` and `completed` bookings still verify: because activation has no production caller, a
   used booking can end as `expired`. The pure rule is `classify_access` in `lab_sessions.application`;
   the booking facts come from `bench_bookings.public`.
3. **User:** `users.public.resolve_user_id_for_login_name` (O23).

Classification is a snapshot at ingestion. A later booking change does not reclassify a stored
session; that is the recompute job (A10). Replay comparison (§4) uses only the pushed values, so a
retry never fails because master data changed in between.

### 11.4 Constraints

| Name | Rule | Why |
| --- | --- | --- |
| `labsess_access_type_matches_code` | `access_type` is null, or `ad_hoc` with no code, or `booked`/`unverified_booking` with a code | A kind cannot contradict the pushed code |
| `labsess_booking_only_when_booked` | `booking` is null, or `access_type` is `booked` | Only verified sessions point at a booking |

`booked` with a null booking stays legal so that deleting a booking (`SET_NULL`) is never blocked.
Indexes: `(bench, login_time)`, `(user, login_time)`, `(access_type, login_time)` for the reports A4
and A5 will run; the booking FK has Django's default index.

### 11.5 Migration and backfill

- **Expand:** one migration adds the four nullable columns, two constraints and three indexes. The
  table has no production writer before A1, so it is expected to be small; existing rows satisfy the
  constraints because `access_type` starts null.
- **Migrate:** `resolve_session_links(*, batch_size, max_batches)` fills rows whose `access_type` is
  null, in primary-key order, one transaction per batch, with `select_for_update(skip_locked=True)`.
  Idempotent and resumable: a filled row is never selected again. Entry point:
  `manage.py backfill_session_links`. Rows without a login time get the access type from the code and
  no bench or booking.
- **Contract:** making `access_type` non-null is a later change, after the backfill reports zero rows.
- **Rollback:** reverse the migration (drops the columns). No pushed value is lost, because links are
  derived.

### 11.6 API

`POST /agent/session-logs` responses add `access_type`. Additive, non-breaking (VER-2).

### 11.7 Tests

| Criterion | Test |
| --- | --- |
| Each access type and its booking link | `test_application.py::test_access_type_*` |
| Bench at login time, not current bench | `test_bench_is_the_placement_at_login_time` |
| User match: case, domain prefix, inactive, ambiguous | `test_user_link_*`, `core/users` resolver tests |
| Constraints | `test_access_type_constraints` |
| Backfill idempotent and batched | `test_backfill_*` |
| Response includes access type | agent HTTP tests |
