# Feature Specification: Monitoring & Telemetry Events (`core/labs/features/monitoring`)

## 1. Domain Overview & Purpose
The Monitoring feature ingests real-time hardware telemetry, peripheral attach/detach signals, device heartbeat pulses, and inventory snapshots from daemon runner agents deployed on lab computing stations.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.MonitoringEvent`
- **Inheritance:** `AgentReportedModel`, `TimeStampedModel`.
- **Fields:**
  - `computer` (FK `ComputingEquipment`, PROTECT).
  - `occurred_at` (DateTimeField).
  - `action`: Enum (`heartbeat`, `device_inserted`, `device_removed`, `device_changed`, `device_status_changed`, `inventory_snapshot`, `metric_reported`, `alert_raised`, `alert_resolved`, `custom`).
  - `action_name` (CharField(128), required if action is `custom`).
  - `subject_type`, `subject_id`, `subject_name` (CharField).
  - `payload` (JSONField, default=dict).
- **Invariants:**
  - `clean()` enforces: `custom` actions require a non-blank `action_name`; `payload` must be a JSON object.
  - Ingestion requires a valid agent API key (`HasAPIKey`).

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/monitoring-events` | `MonitoringEventListCreateAPIView` | Query events with computer, action, and date filters. |
| `POST /api/labs/monitoring-events` | `MonitoringEventListCreateAPIView` | Ingest agent telemetry event. |
| `GET /api/labs/monitoring-events/{id}` | `MonitoringEventDetailAPIView` | Single telemetry event details. |
| `GET /api/labs/monitoring-events/export` | `MonitoringEventExportAPIView` | Stream export of monitoring events. |
| `GET/POST /api/labs/lab-monitoring` | `ListCreateLabMonitoringAPIView` | Deprecated alias returning Sunset headers. |
| `GET /api/labs/lab-monitoring/export` | `ExportLabMonitoringAPIView` | Deprecated alias returning Sunset headers. |
