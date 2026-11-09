# Feature Specification: Operational Dashboard (`core/labs/features/dashboard`)

## 1. Domain Overview & Purpose
The Dashboard feature is the primary mission-control deck for lab coordinators and test engineers, synthesizing bench hardware state, live booking occupancy, active telemetry sessions, and aggregate facility KPIs.

---

## 2. Aggregations & Query Projections

### 2.1 Bench Operational State Card
- Consolidates for each bench:
  - Base metadata: `id`, `sku`, `name`, `lifecycle_status`, `criticality`.
  - Docking location: `setup_location` (Station), `station_slot`.
  - Active reservation: Current active `BenchBooking` and booking user.
  - Hardware status: Attached `ComputingEquipment` and recent heartbeat status.

### 2.2 Canonical Headline Metrics (`/summary`)
- Serves as the single source of truth for dashboard KPI cards:
  - Total benches, active benches, available benches, maintenance benches.
  - Total active bookings and occupancy rate.
  - Online vs offline computing units.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/dashboard` | `DashboardOverviewAPIView` | Paginated live bench cards with telemetry. |
| `GET /api/labs/dashboard/summary` | `DashboardSummaryAPIView` | Canonical KPI summary metrics across the lab. |
| `GET /api/labs/dashboard/benches/{bench_id}` | `DashboardBenchDetailAPIView` | Deep operational status of a single bench. |
