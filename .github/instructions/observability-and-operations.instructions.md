---
applyTo: '**/Dockerfile*,**/docker-compose*.yml,.github/workflows/**,**/settings*/**,**/logging*.py'
---
# Observability & Operations Standards

## Logging
Structured (JSON) logs with timestamp, level, service, environment, request/trace ID,
user/tenant identifier where permitted. No secrets, tokens, or personal data. Log
decisions and failures, not every step.

## Metrics & tracing
Request rate, error rate, latency by route (RED), database query time and connection
usage, task queue depth and age, outbox lag. Distributed traces (OpenTelemetry-style)
with the same correlation ID as logs.

## Health & shutdown
Separate liveness (process is alive) and readiness (can serve: database reachable,
migrations compatible). Graceful shutdown drains requests and finishes or safely requeues tasks.

## SLOs & alerts
Define SLIs/SLOs for the key journeys (e.g. booking creation, resource search).
Alert on user-visible symptoms; every alert has a runbook and an owner.

## Deployment
- Migrations are an explicit release step, backward-compatible with the previous app
  version (expand/contract). No implicit migrate-on-start across many instances.
- Risky behavior ships behind a flag with a documented rollback.
- Rollback plan is stated for every T2 change, including data implications.
- Config is environment-driven, validated at start-up; secrets via the secret mechanism.

## Backups & recovery
Documented RPO/RTO. Point-in-time recovery where available. Restore tested in a safe
environment on a schedule; untested backups are not claimed as recoverable.

## Containers & supply chain
Multi-stage builds, non-root, pinned base images, locked and hashed dependencies where
supported, image and dependency scanning in CI, SBOM when required.

## Safety
Production actions follow AGENTS.md rule 9. Restarting a production service or rotating a credential counts
as a production action.
