# Feature Specification: Leaderboard & Heatmaps (`core/labs/features/leaderboard`)

## 1. Domain Overview & Purpose
The Leaderboard feature computes engagement metrics, classifies users into behavioral persona archetypes, tracks bench productivity rankings, and generates 168-hour utilization heatmap matrices.

---

## 2. Core Projections & Scoring Algorithms

### 2.1 Persona Archetype Classification
- Categorizes engineers over a rolling window based on session logs (`LabSessionLog`) and bookings (`BenchBooking`):
  - *Power User*: High session duration and frequent multi-bench usage.
  - *Steady Tester*: Consistent scheduled test runs.
  - *Occasional Explorer*: Intermittent ad-hoc sessions.

### 2.2 168-Hour Heatmap Matrices
- Synthesizes session telemetry and booking hours across a 7-day grid (24 hours $\times$ 7 days = 168 slots) normalized to UTC.
- Evaluates bench-level and user-level load distribution.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/leaderboard/persona` | `LeaderboardPersonaAPIView` | User rankings binned by persona archetype. |
| `GET /api/labs/leaderboard/lab` | `LeaderboardLabAPIView` | Laboratory utilization leaderboard. |
| `GET /api/labs/leaderboard/export` | `LeaderboardExportAPIView` | Leaderboard dataset export. |
| `GET /api/labs/benches/{id}/profile` | `LabProfileAPIView` | Canonical bench performance profile. |
| `GET /api/labs/benches/{id}/weekly-usage` | `LabWeeklyUsageHeatmapAPIView` | Canonical bench 7-day hourly heatmap. |
| `GET /api/labs/leaderboard/users/{id}/profile` | `UserProfileAPIView` | Canonical user ranking profile. |
| `GET /api/labs/leaderboard/users/{id}/weekly-usage` | `UserWeeklyUsageHeatmapAPIView` | Canonical user 7-day hourly heatmap. |
| `GET /api/labs/lab-dashboard` | `LabDashboardAPIView` | Polymorphic dashboard overview list. |
| `GET /api/labs/lab-dashboard/summary` | `DeprecatedLeaderboardDashboardSummaryAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/profile/{id}` | `DeprecatedLabProfileAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/weekly-usage/{id}` | `DeprecatedLabWeeklyUsageHeatmapAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/users/profile/{id}` | `DeprecatedUserProfileAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/users/weekly-usage/{id}` | `DeprecatedUserWeeklyUsageHeatmapAPIView` | Deprecated alias returning Sunset headers. |
