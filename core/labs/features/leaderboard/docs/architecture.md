# Leaderboard Feature Architecture

> Status: Verified against code on 2026-10-18 · Owner: Labs Engineering (Leaderboard)

## 1. Purpose and scope

The leaderboard feature provides gamified user engagement scoring, laboratory and bench utilization rankings, weekly heatmaps, user/bench profiles, and operational dashboard summaries.

- **In Scope:**
  - Persona leaderboard: user points, work-from-office (WFO) vs work-from-home (WFH) ratios, late-night session rates, booking compliance, and session duration metrics.
  - Laboratory leaderboard: bench utilization ranking based on active session volume and distinct user engagement.
  - Profile summaries: detailed activity and booking statistics for individual benches and users.
  - Weekly utilization heatmaps (7 days x 24 hours).
  - High-level asset status dashboard summaries.
  - Export capabilities for persona and lab rankings.
- **Out of Scope:**
  - Ingestion of raw session logs (owned by session telemetry).
  - Bench reservation scheduling or resource lifecycle status changes.

---

## 2. Responsibilities and ownership

| Concept / Rule | Owned Here? | Notes |
|---|---|---|
| User persona points algorithm | Yes | Multi-factor engagement scoring |
| Bench ranking algorithm | Yes | Activity-weighted bench scoring |
| Weekly usage heatmaps | Yes | 7x24 session hour distribution |
| Dashboard summary projection | Yes | Aggregate equipment lifecycle status counts |
| `Bench` | No (Dependency) | Owned by `core.labs.features.benches` |
| `BenchBooking` | No (Dependency) | Owned by `core.labs.features.bench_bookings` |
| `LabSessionLog` | No (Dependency) | Owned by `core.labs.models.session` |
| `User` | No (Dependency) | Owned by `core.users.models` |

---

## 3. Public interface and contracts

The feature boundary is exposed through `public.py`:

- **Query Selectors:**
  - `compute_leaderboard_persona(start_date: datetime, end_date: datetime) -> list[dict]`
  - `compute_leaderboard_lab(start_date: datetime, end_date: datetime) -> list[dict]`
  - `get_lab_profile(pk: int, start_date: datetime, end_date: datetime) -> dict`
  - `get_lab_weekly_usage(pk: int) -> list[dict]`
  - `get_user_profile(pk: int, start_date: datetime, end_date: datetime) -> dict`
  - `get_user_weekly_usage(pk: int) -> list[dict]`
  - `get_dashboard_labs() -> list[dict]`
  - `get_dashboard_summary() -> dict`
- **Domain Exceptions:**
  - `LeaderboardError`
  - `LeaderboardValidationError`
  - `ResourceNotFoundError`
- **HTTP Endpoints (mounted under `/api/labs/`):**
  - `GET /leaderboard/persona`: ranked list of users with points and operational metrics
  - `GET /leaderboard/lab`: ranked list of benches by usage
  - `GET /leaderboard/export`: export ranking data
  - `GET /benches/<id>/profile`: bench profile statistics (404 if bench missing)
  - `GET /benches/<id>/weekly-usage`: bench weekly heatmap
  - `GET /leaderboard/users/<id>/profile`: user profile statistics (404 if user missing)
  - `GET /leaderboard/users/<id>/weekly-usage`: user weekly heatmap
  - `GET /lab-dashboard`: polymorphic unpaginated/paginated dashboard bench list

---

## 4. Dependencies and layer separation

```mermaid
flowchart LR
  api[api/views.py] --> public[public.py facade]
  public --> queries[queries/selectors.py & helpers.py]
  queries --> dep_models[core.labs.models (Bench, BenchBooking, LabSessionLog, User)]
```

- API views never import Django models directly (`test_public_boundary.py` enforced).
- All calculations are pure, side-effect free database reads.
- Missing entities cleanly raise `ResourceNotFoundError` which maps to HTTP 404 Problem Details.

---

## 5. Scoring algorithms and metrics

### KPI definitions

Sessions count for the app user the session log resolved (`LabSessionLog.user`); older rows without
that link fall back to the login name (case ignored, `DOMAIN\` dropped, never a guessed person).
Bookings count for the person they are for (`requester`, else `creator`). A booking is *expected*
when it is approved, not cancelled and has started inside the window; expired bookings are no-shows.
"Active" time is the agent-reported `active_duration_seconds`, else the whole session.

| KPI | Definition | Null when |
|---|---|---|
| `wfo_rate` / `wfh_rate` (shown as RFO / RFH) | `sessions ÷ (weekdays × 2)`, clamped; RFH is `1 − RFO`. Detection unchanged. | — |
| `late_rate` | Share of session time between 20:00 and 06:00 local time | — |
| `usage_efficiency` | Active minutes ÷ (weekdays × 480) | — |
| `active_rate` | Active minutes ÷ session minutes | no sessions |
| `ad_hoc_rate` | Sessions without a verified booking ÷ sessions | no sessions |
| `booking_compliance` | Expected bookings with at least one session ÷ expected bookings | no bookings |
| `booking_utilization` | Session time inside each slot (capped at the slot) ÷ booked time | no bookings |
| `slot_adherence` | Session time inside the slot ÷ all time of booked sessions | no attended booking |
| `no_show_bookings` | Expected bookings with no session | — |

Benches use the bench the computer stood on at login (`LabSessionLog.bench`): `utilization_rate`
(active minutes ÷ weekdays × 480), `booking_fill` (booked minutes ÷ weekdays × 480), and the booking
KPIs above over the bench's bookings. `downtime_minutes` is not computed yet (always 0).

### Points

```text
persona = sessions×10 + active_hours×10 + usage_efficiency×100 + booking_compliance×50
        + booking_utilization×50 + slot_adherence×20 − late_rate×30        (null KPIs add 0)
bench   = sessions×20 + active_hours×10 + active_users×15 + utilization_rate×100 + booking_compliance×50
```
Login count reflects how much the lab is used; active hours and the booking KPIs reflect how well.

### KPI assessment (`queries/assessment.py`)

`GET /leaderboard/users/<id>/assessment` and `GET /benches/<id>/assessment`, **lab coordinators and
administrators only** (`LABS_STAFF_ACCESS`); the rankings stay readable by every lab member.

- Scorecard: each KPI with its value, previous-period value, target and status (on / near / below
  target, or not applicable). Targets (persona): attendance ≥ 90 %, booked time used ≥ 75 %, active
  rate ≥ 80 %, slot adherence ≥ 95 %, sessions without booking ≤ 20 %, after-hours ≤ 10 %, lab
  presence ≥ 50 % (4 h/weekday). Bench: utilisation ≥ 60 %, attendance ≥ 90 %, booked time used
  ≥ 75 %, booking fill ≥ 50 %.
- Score: weighted mean of each KPI's attainment towards its target (0–100). Rating: ≥ 85 exceeds,
  ≥ 70 meets, ≥ 50 partially meets, else below expectations; fewer than 3 sessions plus bookings is
  "insufficient data".
- Strengths (KPIs on target) and development areas (near or below target, each with a recommended
  action), with the figures behind them, and a one-paragraph summary including the trend against the
  equal-length previous period.

---

## 6. Security and authorization

- All endpoints enforce `HasAPIKey | IsAuthenticated` via `FeatureAPIView`.
- Date range query inputs (`start_date`, `end_date`) are validated to ensure ranges do not exceed the 730-day window limit.

---

## 7. Observability and OpenAPI integration

- Documented in `openapi/labs-leaderboard.yml` via `drf-spectacular`.
- Polymorphic response contract on `/api/labs/lab-dashboard` supporting both single envelope (`{"data": [...]}`) and paginated envelope (`{"data": [...], "meta": {...}}`).

---

## 8. Tests and boundary enforcement

- `core/labs/features/leaderboard/tests/test_public_boundary.py`: Enforces zero model imports in API views and public facade exports.
- `tests/integration/test_leaderboard_api.py`: 10 integration tests verifying auth, date range filtering, empty display name resilience, and 404 handling.
- `tests/unit/test_leaderboard_helpers.py`: 30 unit tests covering late rate math, downtime calculations, weekday counters, and cache timeouts.
