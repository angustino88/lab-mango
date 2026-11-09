# Monitoring Feature Architecture

> Status: Verified against code on 2026-10-19 · Owner: Labs / Monitoring

**Verified** statements describe inspected code. **Proposed** statements are not implemented guarantees.

## 1. Purpose and scope

**Verified.** The monitoring feature owns the ingestion, recording, querying, and reporting of immutable agent-reported monitoring telemetry events (`MonitoringEvent`).

- **In Scope:**
  - Ingestion and recording of agent-reported events (`MonitoringEvent`).
  - Enforcement of idempotency and natural uniqueness (`computer`, `agent_id`, `event_id`).
  - Query selectors and filtering for monitoring events (`list_monitoring_events`, `get_monitoring_event`).
  - HTTP endpoints for event ingestion, paginated browsing, event details, and reporting exports.

- **Out of Scope / Does not own:**
  - Live computer remote-session and activity state (owned by `activity.ComputingActivity`).
  - Session logins, logouts, and work-time aggregation (owned by `session.LabSessionLog`).
  - Computer resource and hardware/software specifications (owned by `equipment.ComputingEquipment`).
  - Reservation bookings and schedule conflicts (owned by `bench_bookings.BenchBooking`).

## 2. Model ownership and invariants

**Verified.**
- `MonitoringEvent` (`core.labs.models.monitoring`): An immutable audit log of agent-reported facts and metrics. Extends `AgentReportedModel` and `TimeStampedModel`. Protects its `ComputingEquipment` relation with `PROTECT`. Enforces natural uniqueness per agent (`computer`, `agent_id`, `event_id`).

## 3. Public boundary and interface contracts

**Verified.** All external callers interact with `core.labs.features.monitoring.public`:
- **Commands:**
  - `create_monitoring_event(command: CreateMonitoringEventInput, *, actor=None) -> MonitoringEvent`
- **Query Selectors:**
  - `list_monitoring_events(*, computer_id=None, computer_sku=None, action=None, subject_type=None, bench_id=None, from_date=None, to_date=None) -> QuerySet[MonitoringEvent]`
  - `get_monitoring_event(*, event_id: int) -> MonitoringEvent`
- **Exceptions:**
  - `ComputerNotFound` (inherits `ObjectDoesNotExist`, `ValueError`)
  - `MonitoringEventNotFound` (inherits `ObjectDoesNotExist`, `ValueError`)
  - `MonitoringEventConflict` (inherits `ValueError`, maps to HTTP 409)

## 4. HTTP Transport endpoints

- `GET /api/labs/monitoring-events` (and alias `/api/labs/lab-monitoring`): Paginated listing of monitoring events.
- `POST /api/labs/monitoring-events` (and alias `/api/labs/lab-monitoring`): Ingests a new monitoring event.
- `GET /api/labs/monitoring-events/<id>`: Retrieves a single monitoring event.
- `GET /api/labs/monitoring-events/export` (and alias `/api/labs/lab-monitoring/export`): Non-paginated export of monitoring events.
