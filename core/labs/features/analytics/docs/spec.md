# Feature Specification: Laboratory Analytics (`core/labs/features/analytics`)

## 1. Domain Overview & Purpose
The Analytics feature calculates longitudinal operational trends, booking efficiency ratios, equipment availability statistics, financial projections, and storage quota measurements across laboratory facilities.

---

## 2. Data Models & Observations

### 2.1 Analytics Base Observation Contract
- Stored under `core/labs/models/analytics/`:
  - `ActiveLaboratoryObservation`, `ActiveUserObservation`, `BookingOutcomeObservation`, `BookingVolumeObservation`, `LaboratoryAvailabilityObservation`, `LaboratoryVisitEvent`, `ResourceUtilizationObservation`, `StorageQuotaMeasurement`.
- **Dimensions:**
  - `granularity`: Enum (`daily`, `weekly`, `monthly`, `ad_hoc`).
  - `source`: Enum (`application`, `collector`, `import`, `manual`).
  - `period_start`, `period_end` (DateTimeField, indexed).

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/analytics/finance/summary` | `FinanceSummaryAPIView` | Financial rollup metrics. |
| `GET /api/labs/analytics/finance/monthly-trends` | `FinanceMonthlyTrendsAPIView` | Longitudinal monthly spend trajectory. |
| `GET /api/labs/analytics/finance/expense-type-breakdown` | `FinanceBreakdownAPIView` | Expense distribution by type. |
| `GET /api/labs/analytics/bench-group` | `BenchGroupSummaryAPIView` | Canonical bench count per resource group. |
| `GET /api/labs/analytics/lab-group` | `DeprecatedLabGroupSummaryAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/analytics/lab-equipment-status` | `EquipmentStatusSummaryAPIView` | Status distribution time-series. |
| `GET /api/labs/analytics/lab-efficiency` | `LabEfficiencyAPIView` | Utilization efficiency ratios. |
| `GET /api/labs/analytics/project-usage` | `ProjectUsageAPIView` | Hours utilized per project. |
| `GET /api/labs/analytics/user-lab-usage` | `UserLabUsageAPIView` | Lab bench hours per user. |
| `GET /api/labs/analytics/user-booking-efficiency` | `UserBookingEfficiencyAPIView` | Reserved vs actual hours utilized. |
| `GET /api/labs/analytics/lab-usage-by-timeframe` | `LabUsageTimeframeAPIView` | Time-binned utilization curves. |
| `GET /api/labs/analytics/storage-quota` | `StorageQuotaAPIView` | Storage consumption metrics. |
| `GET /api/labs/analytics/lab-visits` | `LabVisitsAPIView` | Physical visitor counts. |
| `GET /api/labs/analytics/booking` | `BookingCountAPIView` | Reservation volume metrics. |
| `GET /api/labs/analytics/lab-count` | `LabCountAPIView` | Active laboratory counts. |
| `GET /api/labs/analytics/user-count` | `UserCountAPIView` | Active user statistics. |
| `GET /api/labs/analytics/booked-vs-used` | `BookedVsUsedAPIView` | Scheduled vs confirmed run hours. |
| `GET /api/labs/analytics/equipment-availability` | `EquipmentAvailabilityAPIView` | Uptime and readiness statistics. |
| `GET /api/labs/analytics/dashboard-summary` | `DashboardSummaryAPIView` | Deprecated alias for dashboard summary. |
