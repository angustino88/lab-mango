# Design: Finance, Procurement, Expense and Lab Analytics — Review and Implementation Plan

- **Tier:** T2 · **Status:** Draft; session-log decisions and finance direction recorded; A1 and A1b implemented on branch `claude/loving-hopper-n5grpk`, pending review and approval · **Date:** 2026-11-10, updated 2026-11-11
- **Note:** main was redesigned after this review (single equipment table; `EquipmentAssignment` now holds every placement, with `EquipmentAssignment.objects` returning bench placements only). Model names in §3–§4 refer to the code as reviewed on 2026-11-10.
- **Domain:** Labs (`procurement`, `expense`, `analytics`, session log, agent session ingestion)
- **Scope of this change:** documentation only. No code, schema, API or permission was changed.
- **Verification:** findings come from reading the code. No test or endpoint was run. Items marked
  *not verified* could not be confirmed from this repository.

---

## 1. Summary

The write-safety work in procurement is solid, but two things stop these features from being product
grade:

1. **The finance model is a ledger of free-text records**, not a procure-to-pay or cost model. Recurring
   expenses are reported wrongly, the purchase lifecycle cannot be reached through the API, and money
   records cannot be corrected.
2. **Lab analytics has no reliable input.** Every utilisation report reads `LabSessionLog`, but the
   backend has no endpoint that receives session logs, sessions are not linked to a bench or a user, and
   operating hours are hard-coded.

The plan is ordered so that the data source is fixed before any report is polished: session ingestion →
session links → operating calendar → analytics rebuild, with the finance fixes as a parallel track.

## 2. Decisions already made by the owner

| ID | Decision |
| --- | --- |
| O1 | A session is recorded only at logout. The agent pushes one session log after the user logs out. |
| O2 | If the network is lost, the agent does not send the session. This loss is accepted. No offline queue and no heartbeat-based session closing are required. |
| O3 | "Temp login" (remote login without a booking) is enforced by the agent on the computer. The backend applies no rule to it. |
| O4 | The backend recognises a temp login as a session without a booking code. Miscounting a booked session as temp login when the code is missing is accepted. |
| O5 | `booking_code` stays the reference between a session and a booking. One booking can have many sessions. |
| O6 | Holidays are entered manually. No holiday library is added. |
| O7 | The operating calendar is staged: timezone and weekly hours first, closed dates second. |
| O8 | The backend provides the URL the agent pushes session logs to. There is no existing receiver to migrate; A1 is a new endpoint. |
| O9 | The agent sends exactly: login time, logout time, active time, remote user, remote IP, remote host, booking code. It does not send a display name or host name. |
| O10 | One computer allows one remote user with one booking code at a time, so sessions on one computer do not overlap. Used time is the sum of session active times. |
| O11 | The session log list and per-user usage reports are visible to lab coordinators and lab admins only. |
| O12 | Before accepting a booking code, the agent checks that the booking's start and end time cover the login and that the booking belongs to this computer. A code the agent sends is therefore valid at login. |
| O13 | Each session is pushed once, after logout, and is final. There is no update or correction endpoint. |
| O14 | The finance direction in §8 is accepted (2026-11-10). Each work package still needs its own design note and approval before merge (T2). |
| O15 | New agent APIs are designed for session-log push and booking validation (§5.5). The planned but unbuilt `GET /agent/bookings/code/{booking_code}` is not relied on. |
| O16 | Session logs are kept forever. |
| O17 | Only lab admins may exclude or restore a session log (existing `IsLabAdmin`). |
| O18 | There is no data policy restricting session-log personal data. Remote user and remote IP are kept forever with no removal path. |
| O19 | Session-log limits confirmed: logout at most 5 minutes after server time, login at most 7 days before server time, sessions over 24 hours flagged (§5.6). |

## 3. Current state: lab analytics

### 3.1 Session data has no source

- Mounted agent routes are `agent/info`, `agent/enrollments` and `agent/heartbeat`
  (`core/agents/api/urls.py:26-28`). None accepts a session log.
- `POST /api/labs/monitoring-events` stores monitoring events only. Its action types have no login or
  logout value (`core/labs/models/monitoring/monitoring.py:8-18`) and its command does not create a
  session log.
- Nothing outside tests and the Django admin creates `LabSessionLog` rows.
- `docs/agent-platform/backend-api.md:47` records raw-session ingestion as deferred until mapping,
  minimisation, retention and corrections are approved.
- The agent pushes to a URL the backend provides (O8). Because no receiver exists, no session log
  reaches this backend today.

Reports affected: bench efficiency, user usage, user booking efficiency, usage by timeslot,
booked-versus-used, and the leaderboard.

### 3.2 Sessions are not linked to a bench, a booking or a user

`LabSessionLog` links only to a computer. The booking is a text code and the user is a remote login name
(`core/labs/models/session/lab_session.py:15-33`).

| Effect | Evidence |
| --- | --- |
| Bench efficiency reports every row under a hard-coded "Default Lab" | `core/labs/features/analytics/queries/utilization.py:102` |
| Booked-versus-used gives one lab-wide used total, not per bench | `core/labs/features/analytics/queries/insights.py` (`get_booked_vs_used` docstring) |
| User booking efficiency matches the booking creator's app username against the remote login name, which are different identities | `core/labs/features/analytics/queries/utilization.py:207-244` |

### 3.3 Operating hours are hard-coded

- Monday to Friday, 09:00 to 17:00, no holidays, no per-lab hours
  (`core/labs/features/analytics/queries/calculations.py:42`).
- The boundary is taken in the timezone of the request, not of the lab.
- Sessions outside those hours still count in the numerator, and ratios are capped at 100%, which hides
  over-use and bad data.
- `Room` already links to `Country`, `City` and `Building`
  (`core/labs/models/resource/location/room.py`). No timezone or opening-hours field exists.

### 3.4 Snapshot model

- `ResourceUtilizationObservation`, `BookingOutcomeObservation` and `LaboratoryAvailabilityObservation`
  are never written or read. `ProjectUsageObservation` is read but has no writer.
- "Active laboratories" is the count of non-deleted benches; "active users" is the count of enabled
  accounts (`core/labs/features/analytics/application/tasks.py:51-82`). Neither measures activity.
- Each task snapshots the current day at the moment it runs, overwrites on re-run and has no backfill.
  The model describes observations as immutable.
- Schedules live in the django-celery-beat database, not in code. *Not verified* that the tasks run.

### 3.5 Aggregation errors

| Error | Evidence |
| --- | --- |
| Project usage adds stored observations and live bookings for the same window, and includes cancelled and expired bookings | `core/labs/features/analytics/queries/utilization.py:137-154` |
| Month, quarter and year buckets sum daily counts of active users and distinct visitors | `core/labs/features/analytics/queries/calculations.py:149` |
| Booking volume counts by creation date, not by use date | `core/labs/features/analytics/application/tasks.py:41` |
| Fallback rows invent data ("Default Group", trend fixed at 0) | `core/labs/features/analytics/queries/utilization.py:44-55`, `observations.py` |

### 3.6 Other findings

- **Equipment availability** counts all 24 hours and treats planned maintenance the same as breakdown.
- **Storage alerts:** model validation rejects used above quota, but the write command skips validation
  (`application/commands.py:50`) and the alert searches for exactly that case over every historical
  measurement (`application/tasks.py:110`), so an old overage emails forever.
- **Access:** every analytics endpoint uses `HasAPIKey | IsAuthenticated`. Any logged-in user can post
  storage measurements and visit events, and can read per-user usage rankings.
- **Scale:** most reports loop in Python over all sessions, bookings or status records in the window.
- **Coverage:** only bench bookings are analysed. Equipment booking is still a proposal
  (`docs/proposals/equipment-booking.md`).

## 4. Current state: procurement, expense and finance analytics

### 4.1 Must fix

| # | Finding | Evidence |
| --- | --- | --- |
| F1 | `Expense.amount` is per billing period, but the report compares total payments to that single amount. A monthly expense paid once shows "paid" forever. | `core/labs/features/expense/queries/selectors.py:94` |
| F2 | `total_budgeted` adds monthly and annual amounts together and is an obligation, not a budget. | `selectors.py:126` |
| F3 | "Overdue" is derived from `valid_until` (contract end), and the date filter uses `valid_from` only. | `selectors.py:63`, `:98` |
| F4 | `status` is read-only in the purchase serializer and no transition endpoint exists, so API-created purchases stay `draft`. Payments and allocations are accepted on any status. | `core/labs/features/procurement/api/serializers.py:193`, `application/commands.py:532-587` |
| F5 | Transactions, payments, allocations and expenses are create-only with no reversal. Only draft edits are audited. Payments are not bounded by the total; the report clamps negative net paid to zero. | `application/commands.py:568-587`, `selectors.py:91` |
| F6 | `PurchaseIdempotencyRecord` exists but nothing uses it. A repeated payment post creates a second payment. | `core/labs/models/procurement/purchase.py:249` |
| F7 | Purchases, expenses, the financial report and finance analytics are readable by any authenticated user. | `procurement/api/views.py:45-47`, `expense/api/views.py:24-26` |
| F8 | License cost lives in two places. `LicenseAgreement` and `LicensePayment` are marked deprecated but still served; finance analytics ignores them; the referenced `docs/MIGRATION_PLAN.md` does not exist. The expense API accepts rooms only. | `core/labs/models/resource/license/agreement.py:14-18`, `expense/application/commands.py:42-43` |

### 4.2 Model gaps

- **Supplier** is free text on `Purchase` and `Expense`.
- **No requester, approver, cost centre, project or budget line.** No budget-versus-actual or commitment
  view is possible.
- **No invoice.** `PurchaseTransaction.reference` carries the invoice number.
- **Receipt is a header status only.** No per-line received quantity or date.
- **`total_amount` is entered separately from the lines** and never reconciled. No tax, shipping or
  discount field.
- **A resource can belong to one purchase line only** (`purchase_resource_unique`,
  `core/labs/models/procurement/purchase.py:209`). Upgrades and later additions cannot be recorded. No
  useful life, depreciation or warranty date.
- **Consumables do not fit:** whole-number quantity, one resource per unit.
- **Currency:** two decimals hard-coded, no exchange rate, and the commands default to "EUR" while the
  model reads a setting.
- **Dates:** purchase payments use a timestamp, expense payments a date.

### 4.3 Finance analytics

Cash basis only: payments and refunds per month by source and expense type
(`core/labs/features/analytics/queries/finance.py`). Missing: committed versus paid versus budget, cost
of ownership per resource, cost per booked and per used hour, spend by supplier and project, upcoming
renewals.

### 4.4 Smaller findings

- `GET /api/labs/purchase-priorities` references an undefined `error` variable
  (`procurement/api/views.py:64`). *Not verified by running.*
- The mandatory-field flag D17 from `procurement/docs/purchase-plan-design.md` is not implemented.
- `procurement/docs/spec.md` and `expense/docs/spec.md` disagree with the code on routes, field names,
  cascade behaviour and expense types.

## 5. Proposed design: session log

### 5.1 Ingestion (agent → backend)

- One request per completed session, sent after logout (O1). No request is sent at login.
- The backend publishes the push URL to the agent (O8). *Proposed:* return it from `agent/info` so the
  agent does not hard-code it.
- Payload (O9), mapped to existing `LabSessionLog` fields:

  | Sent by agent | Field |
  | --- | --- |
  | Login time | `login_time` |
  | Logout time | `logout_time` |
  | Active time | `active_duration_seconds` |
  | Remote user | `remote_user` |
  | Remote IP | `remote_ip` |
  | Remote host | `remote_host` |
  | Booking code | `booking_code` (empty for temp login) |
  | Event id (envelope) | `event_id`, with `agent_id`, `agent_version`, `reported_at` |

- `remote_user_display_name` and `host_name` are not sent and stay empty. Reports that show a display
  name fall back to `remote_user`.
- Login and logout are both required, and logout must be after login (existing check
  `labsess_valid_period`). Active time must not exceed logout minus login.
- The computer is taken from the authenticated agent identity, not from the payload.
- Create-only and final (O13). The existing rule `unique_session_report_per_agent` (computer, agent,
  event id) is the race guard. A repeated push with the same event id returns the original result; the
  same event id with a different body is rejected.
- Sessions lost through network failure are not recovered (O2). Reports carry a note that used time is a
  lower bound.
- A session still in progress is not visible. "In use now" continues to come from heartbeat activity,
  not from session logs.

### 5.2 Links and classification

| Link | Rule |
| --- | --- |
| Booking | Optional. Resolved at ingestion from `booking_code` (O5). The raw code is kept as sent. |
| Bench | Resolved from the computer's equipment assignment at login time, not from the booking. |
| User | Resolved from the remote user where a mapping exists; otherwise left empty and reported as unmapped. |

Session kind, stored on the row:

| Kind | Condition |
| --- | --- |
| `booked` | Booking code present and matches a booking |
| `temp_login` | No booking code (O3, O4) |
| `unmatched` | Booking code present but matches no booking for this computer |

The backend holds no temp-login time rule (O3).

The agent already validates the booking before login (O12). The backend still resolves the code itself
rather than trusting the client, but `unmatched` is not an expected case: it means the booking was
cancelled or moved after login, or the agent check failed. It is reported as a data-quality alert.

### 5.3 Used time, including benches with several computers

One computer runs one remote user at a time (O10), but one bench can hold several computers: a
computer has at most one active bench (`one_active_bench_per_equipment`,
`core/labs/models/resource/equipment/assignment.py`), while a bench has no limit on computers. So the
same bench booking can be in use on two computers at once.

Solution: keep two figures and use each for its own question.

| Figure | Definition | Used for |
| --- | --- | --- |
| Computer active time | Sum of `active_duration_seconds` of the sessions on that computer | Computer utilisation, per-user usage, machine-hours |
| Bench occupied time | Length of the union of the `[login_time, logout_time]` intervals of all sessions on all computers of the bench | Bench utilisation, booked-versus-used |

Rules:

- The bench of each session is resolved from the computer's assignment at login time (§5.2), so a
  computer moved between benches counts toward the right bench on each date.
- For booked-versus-used, the union is clipped to the booking window. Time outside the window is
  reported separately as overrun, so booked-versus-used never exceeds 100%.
- Temp-login sessions on the bench join the union too: the bench was occupied, whoever used it.
- The union uses login and logout times, because active time is a single number with no interval.
- The agent is not asked to block a second computer. Agents do not coordinate with each other, and
  concurrent use of one booking on several computers is legitimate.

Example: bench B has PC1 and PC2. Booking 09:00–12:00.

| Session | Login–logout | Active time |
| --- | --- | --- |
| PC1 | 09:00–11:00 | 1.5 h |
| PC2 | 10:00–12:30 | 2.0 h |

- Computer active time: PC1 1.5 h, PC2 2.0 h, machine-hours 3.5 h.
- Bench occupied time: union 09:00–12:30 = 3.5 h; within the booking 3.0 h, overrun 0.5 h.
- Booked-versus-used: 3.0 h of 3.0 h = 100%, with 0.5 h overrun reported beside it.

### 5.4 Session log list (for a frontend table)

No list endpoint exists today. Proposed:

- Default order: newest login first, row id as the final tie-breaker.
- Views: flat (one row per session) and grouped by booking (session count, first login, last logout,
  total used time). Temp logins group by user and computer.
- Filters: date range (required), computer, bench, user, booking code, session kind.
- Access: lab coordinators and lab admins only (O11), for reads as well as writes. The existing
  `IsLabCoordinator` allows any authenticated user to read, so this endpoint needs `read_roles` set.

### 5.5 New agent APIs (O15)

Both endpoints sit beside the existing `agent/heartbeat` and reuse its authentication:
`AgentSignatureAuthentication` with `IsAuthenticatedAgent` (`core/agents/api/views.py:326-330`). The
computer is always `AgentIdentity.equipment`, never a value in the request body.

`GET /agent/info` adds the paths of both endpoints to its response, so the agent reads the push URL from
the backend (O8). This is an additive field.

#### 5.5.1 `POST /agent/bookings/actions/validate`

Called by the agent when a user enters a booking code at login (O12). Read-only: it does not check in,
start a session or change the booking. The code goes in the body, not the URL, so it does not appear in
access logs.

Request:

```json
{ "booking_code": "BK-7F3K9Q" }
```

Eligible when all hold: the booking exists; it is approved; its status is reserved or in progress; its
bench is the computer's active bench; and now is within the booking window, including the existing
10-minute start grace (`bench_bookings/application/policies.py:10`).

`200` when eligible:

```json
{
  "data": {
    "eligible": true,
    "booking_code": "BK-7F3K9Q",
    "starts_at": "2026-11-11T09:00:00+07:00",
    "ends_at": "2026-11-11T12:00:00+07:00",
    "booked_by": "nguyen.an"
  }
}
```

`200` with `"eligible": false` and no booking details for every other case: unknown code, wrong bench,
not approved, cancelled, outside the window. One answer for all failures stops a caller from learning
which codes exist. `401` for a bad signature, `429` above the rate limit.

#### 5.5.2 `POST /agent/session-logs`

Called once after logout (O1, O13). Body:

```json
{
  "event_id": "5b0f6c1e-2a7d-4c9e-9a3b-0d6e4f1a2c77",
  "login_time": "2026-11-11T09:02:11+07:00",
  "logout_time": "2026-11-11T11:47:40+07:00",
  "active_duration_seconds": 8912,
  "remote_user": "nguyen.an",
  "remote_ip": "10.20.4.17",
  "remote_host": "LT-NGUYENAN",
  "booking_code": "BK-7F3K9Q",
  "agent_version": "2.4.1"
}
```

`booking_code` is null or omitted for a temp login. Unknown fields are rejected.

| Response | When |
| --- | --- |
| `201` | Stored. Body returns the session id, event id, login and logout time, and booking code. The session kind is added with A2, where it is also stored. |
| `200` | Same `event_id` and same body already stored. Returns the original record. |
| `409` | Same `event_id` with a different body. |
| `422` | Validation failed (§5.6 hard limits). |
| `401` / `429` | Bad signature / rate limit. |

The race guard is the existing unique rule `unique_session_report_per_agent` (computer, agent, event id).
The insert and the booking and bench resolution happen in one transaction. An `unmatched` code is
stored, not rejected, because the session really happened.

### 5.6 Wrong records

A record is final once pushed (O13) and kept forever (O16), but some records will still be wrong. These
are the cases expected in practice:

| # | Example | What goes wrong | Handling |
| --- | --- | --- | --- |
| W1 | The computer clock is wrong, so the session shows a login in 2019 or a logout tomorrow | Usage lands on the wrong day | Rejected at ingestion (hard limit) |
| W2 | The agent hangs, and the logout is recorded two days later | One session counts as 48 hours | Accepted and flagged as suspect for review |
| W3 | A disk image with the agent's identity is copied to a second PC | Both PCs report as one computer | Admin excludes the affected rows; IT re-enrols the agent |
| W4 | IT staff log in to install software before the bench opens | Setup work counts as lab use | Admin excludes the rows with reason "maintenance" |
| W5 | A PC is moved to another bench, but the assignment is updated a week late | That week's use counts for the old bench | Fix the assignment history and recompute the bench link; the raw row is untouched |
| W6 | The booking is cancelled after the user has logged in | The session becomes `unmatched` | Kept as recorded; shown in the data-quality list |
| W7 | An agent bug sends one session twice with different event ids | Usage doubles | Flagged as probable duplicate (same computer, same login and logout); admin excludes one |

Mechanisms:

- **Hard limits at ingestion (reject with `422`):** logout after login; logout not more than 5 minutes
  in the future; login not more than 7 days in the past; active time not more than logout minus login.
  The times come from the PC's clock, the check uses the server's clock:

  | Limit | Why | Example |
  | --- | --- | --- |
  | Logout ≤ server time + 5 min | The session ended before the push, so a logout in the future means the PC clock is ahead. 5 minutes tolerates normal clock drift. | Server time 11:50, logout 11:52: accepted. Logout 14:00: rejected, PC clock about 2 hours ahead. |
  | Login ≥ server time − 7 days | A push is sent right after logout, so a login weeks ago means the PC clock is behind or the date is wrong. 7 days still allows a long session. | Login 2019-03-01: rejected. |
  | Active time ≤ logout − login | The user cannot be active longer than they were logged in. | Logged in 2 h, active 3 h: rejected. |
  | Session > 24 h | Not a rejection: stored and flagged for review (W2). | Login Monday 09:00, logout Wednesday 10:00: stored, flagged `long_session`. |
- **Automatic flags (accept and mark for review):** a session longer than 24 hours; a probable
  duplicate. Flagged rows still count until a person decides.
- **Exclusion instead of deletion:** a lab admin marks a row as excluded, with a reason (maintenance,
  duplicate, wrong computer, clock error, other) and an optional note. The raw values never change. Who
  excluded it and when is recorded. Reports skip excluded rows. Exclusion can be undone.
- **Derived links are recomputable:** bench, booking and user links come from master data, so fixing
  that data (W5) and recomputing corrects the reports without touching the pushed record.

### 5.7 Which feature and endpoint handles each case

All seven examples are about one record type, `LabSessionLog`. No feature owns it today: analytics and
the leaderboard only read it. *Proposed:* a new feature `core/labs/features/lab_sessions` owns its
writes, queries, flags and exclusions. The `/agent/...` routes are mounted with the other agent routes
but call `lab_sessions` through its `public.py`, the same way the agent booking end-time command lives in
`bench_bookings`.

Endpoints involved:

| Endpoint | Feature | Status | Who calls it |
| --- | --- | --- | --- |
| `POST /agent/session-logs` | `lab_sessions` | New (§5.5.2) | Agent, after logout |
| `GET /api/labs/session-logs` | `lab_sessions` | New (§5.4) | Lab coordinator, lab admin |
| `POST /api/labs/session-logs/{id}/actions/exclude` | `lab_sessions` | New | Lab admin (O17) |
| `POST /api/labs/session-logs/{id}/actions/restore` | `lab_sessions` | New | Lab admin |
| `POST /api/labs/session-logs/actions/recompute-links` | `lab_sessions` | New | Lab admin, after master data is fixed |
| `POST /api/labs/equipment/{id}/assignment` | `equipment` | Exists; always records the current time | Lab coordinator |
| Correction of a past assignment date | `equipment` | Missing | Lab admin |
| `POST /api/agents/{id}/actions/revoke` and re-enrolment | `core.agents` | Exists | Lab coordinator |
| `GET /api/labs/analytics/...` and leaderboard | `analytics`, `leaderboard` | Exist; must skip excluded rows | Readers of reports |

Where each example is caught and fixed:

| # | Example | Caught by | Fixed with |
| --- | --- | --- | --- |
| W1 | Wrong PC clock | `POST /agent/session-logs` returns `422`; nothing is stored | Fix the PC clock; that session is lost (accepted, like O2) |
| W2 | Logout two days late | `POST /agent/session-logs` stores it with flag `long_session` | Admin finds it in `GET /api/labs/session-logs?flag=long_session` and calls `.../exclude` if it is wrong |
| W3 | Copied disk image | Not detectable automatically; noticed when one computer shows two users at once | `POST /api/agents/{id}/actions/revoke`, re-enrol each PC; admin excludes the mixed rows with reason `wrong_computer` |
| W4 | IT staff setup sessions | Not detectable automatically | Admin filters the list by computer and date, then excludes with reason `maintenance` |
| W5 | PC moved, assignment updated late | Not detectable automatically | Correct the past assignment date in `equipment` (missing today), then `.../actions/recompute-links` for that computer and period |
| W6 | Booking cancelled after login | `POST /agent/session-logs` stores it as kind `unmatched` | No fix needed; listed by `GET /api/labs/session-logs?kind=unmatched` |
| W7 | Same session sent twice with different ids | `POST /agent/session-logs` stores it with flag `probable_duplicate` | Admin excludes one copy with reason `duplicate` |

After any exclusion, restore or recompute, every report (`analytics`, `leaderboard`) reflects it on its
next read or next fact-table run (A4); no report reads excluded rows.

## 6. Proposed design: operating calendar

- A calendar is inherited country → building → room; the most specific level wins.
- **Stage 1 (O7):** timezone and weekly opening hours, including which days form the working week.
- **Stage 2 (O6):** closed dates entered manually per country and year (about 10 to 15 rows), plus
  site-level closures at building level. Where a country has no list, every working-week day counts and
  the report states "holidays not configured".
- Each day's available hours are stored when the day is computed, so a later calendar edit changes
  history only through a deliberate recompute.
- Booking rules and analytics read the same calendar. Use outside opening hours is reported as
  out-of-hours use, not capped at 100%.

Expected error without stage 2: about 4 to 6% understatement over a year, and up to a quarter in a month
that contains a long holiday week.

## 7. Proposed design: analytics rebuild

- Replace the generic observation tables with per-day facts keyed to real resources: bench-day and
  equipment-day (available hours, booked hours, used hours, out-of-hours use, temp-login hours).
- One backfillable job writes each fact table. Re-running a day replaces that day and nothing else.
- Remove the unused observation models and rename "laboratory" counts to what they measure.
- Reports:
  - booked and used; booked and not used (no-show); used and not booked (temp login);
  - utilisation against calendar hours;
  - equipment availability against operating hours, with planned maintenance separate from breakdown.
- Retire the legacy endpoints that return either a count or a list, duplicate field names and floats.
- Analytics writes (storage, visits) accept collector or agent identity only. Storage alerts read the
  latest measurement per account and do not repeat for the same overage.

## 8. Proposed design: finance

| Area | Change |
| --- | --- |
| Expense | Split the contract (amount per period, validity) from per-period charges (amount, due date). Payments attach to charges. Rename `total_budgeted`. |
| Purchase lifecycle | State machine: draft → submitted → approved → ordered → partially received → received → closed, plus cancelled. State which statuses allow allocation and payment. |
| Corrections | Reversal entry pointing to the original record; audit events for every money write; idempotent payment posts; bounds on payments and refunds. |
| Access | Finance read role for purchases, expenses, reports and finance analytics. |
| License cost | Finish the move to `Expense`; open the expense API to all allowed resource types; remove the deprecated models. |
| Reference data | Supplier as an entity; cost centre and project on purchases, expenses and bookings; budget line. |
| Procure-to-pay | Invoice record; per-line receipt; tax, shipping and discount on the purchase. |
| Assets | Allow more than one purchase line per resource; useful life and warranty dates. |
| Analytics | Commitment and budget views; cost of ownership per resource; cost per booked and per used hour (depends on §5–§7). |

## 9. Breaking changes

| Area | Change | Surface |
| --- | --- | --- |
| Session log | New links and session kind; new agent ingestion endpoint | Schema, agent contract |
| Operating calendar | New models; every utilisation ratio changes value | Schema, report values |
| Observation tables | Unused models dropped; fact tables added | Schema, API |
| Analytics API | Legacy endpoints retired | API contract |
| Analytics writes and per-user reports | Restricted identities and roles | Access control |
| Expense | Contract and charge split; report fields renamed | Schema, API |
| Purchase | Status machine, supplier entity, invoice, receipt, reversal | Schema, API |
| Asset allocation | `purchase_resource_unique` relaxed | Constraint |
| License cost | Deprecated models removed | Schema, API |

Every row is T2. Each needs its own design note, security and QA review, and owner approval before merge.

## 10. Implementation plan

Track A (lab analytics) is strictly ordered. Track B (finance) can run in parallel.

### Track A: lab analytics

| WP | Deliverable | Depends on | Done when |
| --- | --- | --- | --- |
| A0 | Decisions: fields the agent may send, retention period, correction path, overlap rule (§5.3), roles for the session list and per-user reports | none | Done (O8–O19) |
| A1 | `POST /agent/session-logs` and its path in `agent/info` (§5.1, §5.5.2), with the hard limits of §5.6 | A0 | A completed session posted twice creates one row; same event id with a different body returns 409; computer comes from agent identity; only the O9 fields are accepted. **Implemented on branch**; design in `core/labs/features/lab_sessions/docs/architecture.md` |
| A1b | `POST /agent/bookings/actions/validate` (§5.5.1) | none | Eligible only for an approved, active booking on the computer's bench inside its window; every failure returns the same answer. **Implemented on branch** |
| A2 | Session links and session kind (§5.2), resolved at ingestion and returned by the push; backfill for existing rows | A1 | Each session has a kind; bench resolves from assignment at login time; unmatched codes are countable |
| A3 | Operating calendar stage 1: timezone and weekly hours, inherited (§6) | none | Available hours for a room and day come from the calendar, in the lab's timezone |
| A4 | Fact tables and backfillable job (§7), with computer active time and bench occupied time (§5.3) | A2, A3 | Re-running a day is idempotent; a missed day can be backfilled; the §5.3 example gives 3.0 h used and 0.5 h overrun |
| A5 | Rebuilt reports and new endpoints; legacy endpoints deprecated with a sunset date | A4 | Three-way booked/used split and calendar-based utilisation match hand-checked samples |
| A6 | `lab_sessions` feature: session log list (§5.4), exclude and restore endpoints, review filters for flags and kinds (§5.6, §5.7) | A2 | Stable ordering across pages; date range required; role enforced; excluded rows leave every report and can be restored |
| A7 | Operating calendar stage 2: manual closed dates (§6) | A3 | A closed date removes that day's available hours; unconfigured countries are flagged |
| A8 | Analytics write and read access; per-user reports limited to lab coordinators and admins (O11); storage alert fix | none | Plain users cannot post measurements or read per-user reports; an overage alerts once |
| A9 | Remove unused observation models and retired endpoints | A5 | No reader or writer remains; OpenAPI regenerated |
| A10 | Correction of a past equipment assignment date in `equipment`, audited, plus `.../actions/recompute-links` in `lab_sessions` (§5.7, W5) | A2 | A corrected assignment moves that period's sessions to the right bench after recompute; the pushed rows are unchanged |

### Track B: finance

| WP | Deliverable | Depends on | Done when |
| --- | --- | --- | --- |
| B0 | Fix the priority options view (§4.4); correct the two `spec.md` files | none | Endpoint returns options; docs match code |
| B1 | Finance read role (F7) | owner decision | Reads denied without the role; permission matrix tested |
| B2 | Expense contract and charge split (F1–F3) | owner decision | A monthly expense shows one charge per period, each with its own paid state and due date |
| B3 | Purchase state machine (F4) | owner decision | Transitions enforced in commands; allocation and payment rejected in disallowed statuses |
| B4 | Reversal, audit and idempotency for money writes (F5, F6) | B3 | A wrong payment can be reversed without a refund; a repeated post creates one record |
| B5 | License cost migration and expense API for all resource types (F8) | B2 | License fees appear in finance analytics; deprecated models unused |
| B6 | Supplier, cost centre, project and budget line | B3 | Spend can be grouped by each |
| B7 | Invoice, per-line receipt, tax and shipping | B3, B6 | Order, receipt and invoice are separate records that can be matched |
| B8 | Asset allocation changes and asset dates | B7 | A resource can receive a later purchase line |
| B9 | Finance analytics: commitment, budget, cost of ownership, cost per hour | B2–B8, A5 | Figures reconcile to source records |

### Quality gates

Each work package reports the gates in `docs/ai-team/quality-gates.md` for the paths it touches as
passed, failed or not run, with the exact command.

## 11. Open questions for the owner

### Resolved (2026-11-10)

| # | Question | Answer |
| --- | --- | --- |
| 1 | Where does the agent send session logs? | To a URL the backend provides (O8) |
| 2 | Which fields may the agent send? | Login, logout, active time, remote user, remote IP, remote host, booking code (O9) |
| 3 | How are overlapping sessions counted? | They do not overlap on one computer; sum active time (O10) |
| 4 | Who sees the session list and per-user reports? | Lab coordinators and lab admins (O11) |
| 5 | Is the booking code always correct? | The agent validates time window and computer before login (O12) |
| 6 | Finance design | Direction accepted; per-package approval still required (O14) |
| 7 | Correction path for session logs | None; each record is pushed once and is final (O13) |

### Resolved (2026-11-11)

| # | Question | Answer |
| --- | --- | --- |
| 8 | Rely on the planned booking-code route? | No; new agent APIs designed (O15, §5.5) |
| 9 | Retention | Forever (O16) |
| 10 | Benches with several computers | Two figures: computer active time and bench occupied time (§5.3) |
| 11 | Wrong records | Hard limits, automatic flags and audited exclusion; no deletion (§5.6) |

| 12 | Who may exclude a session log | Lab admins only (O17) |
| 13 | Data policy for remote user and IP | None applies; kept forever (O18) |

| 14 | Session-log limits | 5 minutes, 7 days, 24 hours confirmed (O19) |

### Still open

None for the session log (Track A). Track B work packages each need their own design note and
approval before merge (O14).

## 12. Facts, assumptions and residual risks

**Facts** are the statements in §3 and §4 with a `path:line` reference.

**Assumptions**

- The agent can include a stable event id in the logout push, so a retry is recognised as the same
  session.
- The agent's booking check (O12) calls `POST /agent/bookings/actions/validate` (§5.5.1), so the agent
  and the backend judge a booking with the same data.
- Each agent identity is linked to its computer (`AgentIdentity.equipment`), as the existing agent
  booking command already relies on.
- A computer's bench can be resolved from its equipment assignment history at login time.
- Manual holiday entry will be kept current each year by an admin.

**Residual risks**

- Used time is understated by sessions lost to network failure or crash (accepted, O2).
- Booked sessions without a code are counted as temp logins (accepted, O4).
- A wrong session log cannot be corrected through the API (O13); it can only be excluded (§5.6).
- Remote user and remote IP are kept forever (O16, O18). If a policy is introduced later that requires removal, there is
  no path for it in this design.
- Until A7, utilisation is understated in holiday periods.
- Until A1 ships, all session-based reports have no production data source.
