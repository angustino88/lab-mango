# Design: Finance, Procurement, Expense and Lab Analytics — Review and Implementation Plan

- **Tier:** T2 · **Status:** Draft, not approved · **Date:** 2026-11-10
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

No decision has been made yet on the finance items (§4, §8).

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
- *Not verified:* where the agent sends session logs today, if anywhere.

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
- Payload: login time, logout time, active duration, booking code (empty for temp login), remote user
  fields as approved, and the agent's event id.
- The computer is taken from the authenticated agent identity, not from a host name in the payload.
- Retry-safe: the existing rule `unique_session_report_per_agent` (computer, agent, event id) is the
  race guard. A repeated push returns the original result.
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
| `unmatched` | Booking code present but matches no booking |

The backend holds no temp-login time rule (O3).

### 5.3 Used time for a booking

- Used time is the sum of the booking's sessions, using the agent's active duration.
- **Open decision:** when sessions of one booking overlap (several computers on a bench, or a reconnect),
  report machine-hours (add) or bench-occupied time (merge overlaps). Booked-versus-used should use the
  merged figure.

### 5.4 Session log list (for a frontend table)

No list endpoint exists today. Proposed:

- Default order: newest login first, row id as the final tie-breaker.
- Views: flat (one row per session) and grouped by booking (session count, first login, last logout,
  total used time). Temp logins group by user and computer.
- Filters: date range (required), computer, bench, user, booking code, session kind.
- Access: restricted role, because the table shows who used which machine and when.

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
| A0 | Decisions: fields the agent may send, retention period, correction path, overlap rule (§5.3), roles for the session list and per-user reports | none | Recorded in this document |
| A1 | Agent session-log ingestion endpoint (§5.1) | A0 | A completed session posted twice creates one row; computer comes from agent identity |
| A2 | Session links and session kind (§5.2), resolved at ingestion; backfill for existing rows | A1 | Each session has a kind; bench resolves from assignment at login time; unmatched codes are countable |
| A3 | Operating calendar stage 1: timezone and weekly hours, inherited (§6) | none | Available hours for a room and day come from the calendar, in the lab's timezone |
| A4 | Fact tables and backfillable job (§7) | A2, A3 | Re-running a day is idempotent; a missed day can be backfilled |
| A5 | Rebuilt reports and new endpoints; legacy endpoints deprecated with a sunset date | A4 | Three-way booked/used split and calendar-based utilisation match hand-checked samples |
| A6 | Session log list endpoint (§5.4) | A2 | Stable ordering across pages; date range required; role enforced |
| A7 | Operating calendar stage 2: manual closed dates (§6) | A3 | A closed date removes that day's available hours; unconfigured countries are flagged |
| A8 | Analytics write and read access; storage alert fix | none | Plain users cannot post measurements; an overage alerts once |
| A9 | Remove unused observation models and retired endpoints | A5 | No reader or writer remains; OpenAPI regenerated |

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

1. Where does the agent send session logs today (URL or system)? This decides whether A1 is a new
   endpoint or a migration.
2. Which personal fields may the agent send (remote user, display name, IP address), and for how long are
   session logs kept?
3. Overlapping sessions for one booking: machine-hours or bench-occupied time (§5.3)?
4. Who may see the session log list and the per-user usage reports?
5. Does the agent always send the booking code when a booking was used? (O4 accepts the miscount, but the
   size of it should be known.)
6. Finance: approve, change or defer each row of §8, starting with the read role (B1) and the expense
   split (B2).
7. Is a correction path needed for a wrong session log, or is the record final once pushed?

## 12. Facts, assumptions and residual risks

**Facts** are the statements in §3 and §4 with a `path:line` reference.

**Assumptions**

- The agent can include a stable event id and the booking code in the logout push.
- A computer's bench can be resolved from its equipment assignment history at login time.
- Manual holiday entry will be kept current each year by an admin.

**Residual risks**

- Used time is understated by sessions lost to network failure or crash (accepted, O2).
- Booked sessions without a code are counted as temp logins (accepted, O4).
- Until A7, utilisation is understated in holiday periods.
- Until A1 ships, all session-based reports have no production data source.
