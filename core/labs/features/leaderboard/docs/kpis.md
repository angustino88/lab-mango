# Leaderboard KPI catalogue

> Status: verified against code on 2026-11-19 · Owner: Labs Engineering (Leaderboard)
> Code: `queries/selectors.py` (KPI values), `queries/assessment.py` (targets, scoring, wording).

This is the single reference for every KPI the leaderboard computes: what it measures, the exact formula,
which records count, its unit and direction, and how the KPI assessment uses it. The API field name
(what `GET /leaderboard/persona` and `GET /leaderboard/lab` return) and the assessment key (what
`GET .../assessment` returns in `kpis[].kpi.value`) are given for each.

## 1. Common definitions

| Term | Definition |
|---|---|
| **Window** | The requested period: `start_date` 00:00 to `end_date` 23:59:59, server time zone (default: the last 30 days). |
| **Previous window** | The equal-length period immediately before the window; used for trends only. |
| **Weekdays** | Monday to Friday inside the window (at least 1). |
| **Workday capacity** | `weekdays × 480` minutes (8 h per weekday). |
| **Session** | One completed remote session reported by the agent (`LabSessionLog`) with a login and a logout, whose login falls in the window. |
| **Session time** | `logout − login`. |
| **Active time** | The agent-reported active duration (`active_duration_seconds`), capped at the session time; the whole session time for rows stored before the agent reported it. |
| **Session owner** | The app user the session log resolved (`LabSessionLog.user`); for older rows without that link, the user whose username equals the login name (case ignored, `DOMAIN\` dropped). Never a guessed person: an ambiguous name counts for nobody. |
| **Session bench** | The bench the computer stood on at login (`LabSessionLog.bench`), so moving a computer later does not move its history. |
| **Expected booking** | A bench booking that is **approved**, **not cancelled** and has **started inside the window** (`starts_at` in the window and not in the future). Expired bookings are included: they are the no-shows. Pending and rejected bookings are excluded. |
| **Booking owner** | The person the booking is for (`requester`), else its creator. |
| **Linked session** | A session the session log verified against the booking (`LabSessionLog.booking`, access type *booked*). A booking can have **many** linked sessions. |
| **Booking timeline** | All linked sessions of one booking merged into one set of intervals (union): concurrent or overlapping sessions count once. Every booking KPI is computed on this timeline. |
| **Slot** | The booked interval `[starts_at, ends_at)`. `ends_at` always keeps the booked end, also when the booking is completed early. |
| **Completion time** | `completed_at`: when the user (web app or agent) or an equipment return completed the booking; the booked end when the scheduled job completed it at its end. Set exactly when the status is *completed* (database constraint). |
| **Unused tail** | Booked time after the booking timeline's last session ended: `ends_at − max(starts_at, min(last logout, ends_at))`. Counted only when it is at least **15 minutes** (`EARLY_RELEASE_MIN_SECONDS`): finishing a few minutes early is not idle reserved time. |
| **Released tail** | The part of the unused tail freed by completing the booking before its end: `ends_at − max(completed_at, last logout)`, capped at the unused tail; 0 when the booking was not completed before `ends_at`. |

Ratios are returned as fractions `0–1` rounded to 2 decimals (shown as percentages), clamped to `[0, 1]`.
A KPI is **null** ("not applicable", shown as "—") when its denominator is zero; null KPIs are left out of
the score and add nothing to points.

## 2. User (persona) KPIs

### 2.1 Show-up Rate
- **API field:** `booking_compliance` · **Assessment key:** `show_up_rate` · **Direction:** higher is better.
- **Measures:** whether the person used the bookings they made.
- **Formula:** `expected bookings with ≥ 1 linked session ÷ expected bookings`.
- **Null when:** no expected bookings.
- **Companion count:** `no_show_bookings` = expected bookings with no linked session.
- **Example:** 4 expected bookings, one never used → 3 ÷ 4 = **75 %**, 1 no-show. Logging in four times on
  one booking still counts that booking once.
- **Target:** ≥ 90 % (near ≥ 75 %) · **Weight:** 3.

### 2.2 Booking Utilization Rate
- **API field:** `booking_utilization` · **Assessment key:** `booking_utilization_rate` · **Direction:** higher is better.
- **Measures:** how much of the reserved time was actually used, over all sessions of each booking.
- **Formula:** `Σ over expected bookings of (booking timeline ∩ slot) ÷ Σ booked time (ends_at − starts_at)`.
  Session time outside the slot does not count here (see Slot Adherence Rate).
- **Null when:** no expected bookings.
- **Example:** booked 08:00–12:00 (4 h); sessions 08:00–09:00, 08:30–09:30 (concurrent) and 10:00–11:00 →
  timeline 08:00–09:30 + 10:00–11:00 = 2.5 h → 2.5 ÷ 4 = **62.5 %** (reported 0.62). A 4 h booking used
  for 1 h is **25 %** whether or not it was completed early.
- **Target:** ≥ 75 % (near ≥ 50 %) · **Weight:** 2.

### 2.3 Active Time Ratio
- **API field:** `active_rate` · **Assessment key:** `active_time_ratio` · **Direction:** higher is better.
- **Measures:** how much of the session time was active work rather than an idle open session.
- **Formula:** `Σ active time ÷ Σ session time` over the person's sessions in the window.
- **Null when:** no sessions.
- **Example:** 3.5 h of sessions with 3 h active → **86 %**.
- **Target:** ≥ 80 % (near ≥ 60 %) · **Weight:** 2.

### 2.4 Slot Adherence Rate
- **API field:** `slot_adherence` · **Assessment key:** `slot_adherence_rate` · **Direction:** higher is better.
- **Measures:** whether booked work stays inside the reserved slot.
- **Formula:** `Σ (booking timeline ∩ slot) ÷ Σ booking timeline` over expected bookings.
- **Null when:** no expected booking had a linked session.
- **Example:** logged in 07:30, out 11:00 on an 08:00–12:00 booking → 3 h inside of 3.5 h → **86 %**.
- **Target:** ≥ 95 % (near ≥ 80 %) · **Weight:** 1.

### 2.5 Early Release Rate
- **API field:** `early_release_rate` · **Assessment key:** `early_release_rate` · **Direction:** higher is better.
- **Measures:** whether the person completes the booking when the work is finished, so the bench is
  released for others instead of staying reserved.
- **Formula:** `Σ released tail ÷ Σ unused tail` over expected bookings (definitions in section 1).
- **Null when:** no expected booking had an unused tail of at least 15 minutes.
- **Companion value:** `idle_reserved_minutes` = `Σ unused tail − Σ released tail` (booked minutes that
  stayed reserved after the last session).
- **Example:** booked 08:00–12:00, one session 08:00–09:00 (unused tail 3 h).
  Completed at 09:00 → **100 %**, 0 idle reserved minutes. Completed at 10:00 → 2 h ÷ 3 h = **67 %**.
  Not completed (the scheduled job completes it at 12:00) → **0 %**, 180 idle reserved minutes.
  Booking Utilization Rate is 25 % in all three cases, so over-booking stays visible.
- **Target:** ≥ 80 % (near ≥ 50 %) · **Weight:** 1.

### 2.6 Ad-hoc Session Rate
- **API field:** `ad_hoc_rate` · **Assessment key:** `ad_hoc_session_rate` · **Direction:** lower is better.
- **Measures:** how often the lab is used without a verified booking.
- **Formula:** `sessions with no linked booking ÷ sessions` (ad hoc and unverified-booking sessions).
- **Null when:** no sessions.
- **Charts:** shown as its complement **Pre-booked Session Rate** (`1 − value`) where further out is better.
- **Target:** ≤ 20 % (near ≤ 40 %) · **Weight:** 1.

### 2.7 Off-hours Usage Rate
- **API field:** `late_rate` · **Assessment key:** `off_hours_usage_rate` · **Direction:** higher is better (off-hours work is encouraged).
- **Measures:** how much lab time falls outside working hours.
- **Formula:** `session time between 20:00 and 06:00 (server time zone) ÷ session time`, each session split
  exactly at the boundaries.
- **Null when:** never; 0 without sessions.
- **Target:** ≥ 20 % (near ≥ 10 %) · **Weight:** 1.

### 2.8 Workday Utilization Rate
- **API field:** `usage_efficiency` · **Assessment key:** `workday_utilization_rate` · **Direction:** higher is better.
- **Measures:** how much active lab work the person does against an 8-hour working day.
- **Formula:** `Σ active time ÷ workday capacity`.
- **Example:** 20 h active over 5 weekdays → 1 200 ÷ 2 400 = **50 %** (4 h per weekday).
- **Target:** ≥ 50 % (near ≥ 25 %) · **Weight:** 1.

### 2.9 RFO / RFH rate (Remote from Office / Remote from Home)
- **API fields:** `wfo_rate`, `wfh_rate` · **Not in the assessment.**
- **Formula (unchanged detection):** `RFO = min(1, sessions ÷ (weekdays × 2))`; `RFH = 1 − RFO`.
- **Note:** an engagement indicator based on session count against two sessions per weekday; it does not
  inspect the network location.

### 2.10 Volume indicators (reported, not scored)

| API field | Definition |
|---|---|
| `total_sessions` | Sessions in the window (login count). |
| `total_usage_minutes` | Σ session time. |
| `active_usage_minutes` | Σ active time. |
| `avg_session_minutes` | `total_usage_minutes ÷ total_sessions`. |
| `longest_session_minutes` | Longest single session. |
| `labs_accessed` | Distinct computers used. |
| `total_bookings` | Expected bookings. |
| `no_show_bookings` | Expected bookings with no linked session. |
| `idle_reserved_minutes` | See Early Release Rate. |
| `last_remote_at` | Latest login. |
| `top_projects` | Up to three projects with the most expected bookings. |

## 3. Bench (lab) KPIs

Sessions count for their **session bench**; bookings are the bench's expected bookings. The booking KPIs
(Show-up Rate, Booking Utilization Rate, Early Release Rate) use the same formulas as in section 2, over
the bench's bookings whoever made them.

| KPI | API field | Assessment key | Formula | Target (near) | Weight |
|---|---|---|---|---|---|
| **Bench Utilization Rate** | `utilization_rate` | `bench_utilization_rate` | Σ active time on the bench ÷ workday capacity | ≥ 60 % (≥ 30 %) | 3 |
| **Show-up Rate** | `booking_compliance` | `show_up_rate` | attended ÷ expected bookings on the bench | ≥ 90 % (≥ 75 %) | 2 |
| **Booking Utilization Rate** | `booking_utilization` | `booking_utilization_rate` | Σ (timeline ∩ slot) ÷ Σ booked time | ≥ 75 % (≥ 50 %) | 2 |
| **Early Release Rate** | `early_release_rate` | `early_release_rate` | Σ released tail ÷ Σ unused tail | ≥ 80 % (≥ 50 %) | 1 |
| **Booking Occupancy Rate** | `booking_fill` | `booking_occupancy_rate` | Σ booked time ÷ workday capacity | ≥ 50 % (≥ 25 %) | 1 |

Reported, not scored: `total_sessions`, `active_users` (distinct session owners, by user or login name),
`total_usage_minutes` (active minutes), `total_bookings`, `no_show_bookings`, `idle_reserved_minutes`,
`last_remote_at`, `top_projects`. `downtime_minutes` is not computed yet (always 0).

## 4. KPI assessment

`GET /leaderboard/users/<id>/assessment` (lab coordinators and administrators for anyone; a lab member for
themselves) and `GET /benches/<id>/assessment` (coordinators and administrators).

- **Status per KPI:** *On target* when the value reaches the target (at or below it for lower-is-better
  KPIs); *Near target* when it reaches the near threshold; otherwise *Below target*; *Not applicable* when
  null.
- **Attainment per KPI (0–1):** higher is better: `min(1, value ÷ target)`; lower is better: `1` up to the
  target, then `1 − (value − target) ÷ (1 − target)`.
- **Score (0–100):** `round(100 × Σ(attainment × weight) ÷ Σ weight)` over applicable KPIs.
- **Rating:** ≥ 85 *Exceeds expectations*; ≥ 70 *Meets expectations*; ≥ 50 *Partially meets
  expectations*; otherwise *Below expectations*. Fewer than 3 sessions plus expected bookings:
  *Insufficient data* (no score).
- **Strengths:** KPIs on target, with the figure behind them. **Development areas:** KPIs near or below
  target (below first), each with the finding and a recommended action.
- **Trend:** the same computation over the previous window (`previous_value`, `previous_score`).

## 5. Points (ranking)

```text
user  = sessions×10 + active_hours×10 + workday_utilization×100 + show_up×50
      + booking_utilization×50 + slot_adherence×20 + early_release×20 − off_hours×30
bench = sessions×20 + active_hours×10 + active_users×15 + bench_utilization×100 + show_up×50
```
Null KPIs add 0; points are never negative. Login count reflects how much the lab is used; the rates
reflect how well bookings and time are used.

## 6. Data and change notes

- `completed_at` is part of `labs.0001_initial` (migrations reset on a blank database, ADR 005 addendum
  2026-11-19), so every booking records its completion from the start; no historical backfill applies.
- Every write path that completes a booking sets `completed_at`: the agent "complete" action, the web app
  "complete" action (`update_bench_booking`), the scheduled status job (to `ends_at`), and equipment returns.
