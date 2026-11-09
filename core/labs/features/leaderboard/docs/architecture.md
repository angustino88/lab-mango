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
  - `GET /profile/<id>`: bench profile statistics (404 if bench missing)
  - `GET /weekly-usage/<id>`: bench weekly heatmap
  - `GET /users/profile/<id>`: user profile statistics (404 if user missing)
  - `GET /users/weekly-usage/<id>`: user weekly heatmap
  - `GET /lab-dashboard`: polymorphic unpaginated/paginated dashboard bench list
  - `GET /lab-dashboard/summary`: total equipment count and status breakdown

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

### Persona Ranking Formula
```text
points = max(0, int(
    (total_sessions * 10)
  + (total_duration_minutes * 0.1)
  + (usage_efficiency * 100)
  + (booking_compliance * 50)
  - (late_rate * 30)
))
```
- **WFO Rate:** Ratio of sessions to expected weekday capacity (clamped to `[0.0, 1.0]`).
- **WFH Rate:** `1.0 - wfo_rate`.
- **Late Rate:** Proportion of session duration occurring between 20:00 and 06:00 local time.
- **Usage Efficiency:** Ratio of active computing minutes to standard 8-hour working days.
- **Booking Compliance:** Ratio of actual session count to booked slots.

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
