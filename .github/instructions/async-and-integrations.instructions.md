---
applyTo: '**/tasks*.py,**/tasks/**,**/handlers*.py,**/integrations/**,**/jira_integration/**,**/outbox*/**,**/events.py,**/notification_delivery*.py'
---
# Async work and integration rules

- Celery is the task runner. Task names are a deployed contract (AGENTS.md rule 1); renaming one is T2.
- **Thin entry points.** A task or handler loads by ID and calls one application command; no business rules.
- **Idempotent.** Running a task twice leaves the same state. Pass IDs or DTOs, never model instances or requests.
  How: `write-safety.instructions.md` section 3.
- **Competing workers.** Claim work with `select_for_update(skip_locked=True)` and a lease that expires
  (pattern: `claim_one` in `bench_bookings/application/notification_delivery.py`). Never "read pending rows,
  then mark them" in two steps without a lock.
- **Bounded batches.** `query-performance.instructions.md` section 4.
- **Durable vs best effort.** Use `transaction.on_commit` only for best-effort work. Work that must happen uses the
  transactional outbox written in the command's transaction (`docs/architecture/feature-template.md` section 4, Events).
  Reference implementation: `core/labs/features/bench_bookings/` (outbox and notification delivery).
- **Retries.** Bounded, exponential backoff with jitter, only for retryable errors.
  Permanent failures go to a visible dead-letter/failed state with an alert.
- **Timeouts.** Every outbound call and every task has an explicit timeout.
- **Scheduling.** Scheduled jobs are safe with multiple scheduler/worker instances.
- **Webhooks (inbound).** Verify signature and timestamp; reject replays; respond fast and
  process asynchronously.
- **External systems.** Wrap in an adapter; map their errors to domain errors; contract-test
  with recorded fixtures; consider a circuit breaker for flaky dependencies.
- **High-volume ingestion** (monitoring, live activity): batch writes, bound payload size,
  set retention, consider partitioning, keep separate from lifecycle and booking state.
- **Correlation.** The request's `request_id` is passed into the task and logged (OBS-1).
- **Privacy.** No secrets or personal data in task arguments or logs.
- **Tests.** Cover duplicate delivery, retry after partial failure, and timeout for every new task or adapter.
