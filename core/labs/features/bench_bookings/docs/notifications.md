# Bench booking notifications — T2 design and operations

Status: implementation authorized on 2026-10-20; not approved for merge or release.
Independent QA, security and code review remain required. No new dependencies.

## Ownership and acceptance criteria

The centralized Labs model package owns `BookingNotification`. Bench bookings owns
orchestration and transports. Equipment exposes bounded resource-only DTOs via its
public interface; there is no reverse dependency or remote identity projection.

| Acceptance criterion | Implementation | Isolated evidence |
|---|---|---|
| Creation intent in existing transaction | create_booking → notification_intents | intent tests; transaction integration pending |
| Material update, not no-op/free-text | update_booking compares bench, start, end, status, approval, project; reason-only edits are ignored | material comparison test; integration pending |
| Creator only, skip ownerless/inactive/missing destination | intent and delivery precheck | recipient tests |
| Start once per booking/start, approved reserved/in_progress | collector; durable channel/recipient dedupe | half-open boundaries and dedupe tests |
| Inactive strictly >60 minutes, heartbeat [now−10m, now] | equipment projection | exact ORM filter assertions; PostgreSQL execution pending |
| Current assignment, same bench and booking code | projection and collector/send revalidation | resource episode tests |
| Inactive episode not before assignment/booking/cutoff | projection and collector/send revalidation | projection assertions and revalidation |
| Independent retries; locks released before I/O | delivery ledger per channel; fenced completion | claim/retry/fencing tests; concurrent PostgreSQL proof pending |
| Private Teams JSON and shared HTML email | booking payload adapter on shared `post_teams_json`; shared `send_email` HTML sender with a factual booking snapshot | shared transport and mocked integration/email contract tests |
| Registered bounded jobs and opt-in beat | explicit Celery imports; provisioning command | registration/provisioning tests |

No HTTP API/schema changes. Existing lifecycle state machines and ownership authorization
are unchanged. Messages use friendly bench and equipment names when available and never
render their internal numeric IDs. No free text, IP, remote identity, departments or
activity-level assessment appears in messages or logs. Destination email is read only when
necessary; it is not persisted in the outbox. Teams targets a provisioned, verified Entra
tenant/object identity; email/UPN is not used to infer the Teams recipient.

## Event and delivery semantics

One row per logical event/channel/creator; SHA-256 unique dedupe key and shared event UUID.
Creation and each material update have stable event keys derived from the material snapshot;
repeated hook execution for the same state deduplicates. Start keys use booking/start;
inactivity keys use **booking/equipment/inactive_at**, once per episode and channel.
Changing the schedule to a different start yields a new start event. Reason-only edits
are intentionally non-material; no free-text contents are inspected for notifications.

Collection inserts in short booking transactions; email and HTTP never run under locks.
Claims lock **one** delivery with PostgreSQL `skip_locked`; expired 120-second leases are
recoverable. Every claim consumes an attempt. Completion matches the original token,
leased state and unexpired lease. Maximum five attempts, exponential delay starting at
30 seconds with multiplicative jitter in [1,2], base capped at 900 seconds.
Each channel succeeds/fails independently. HTTP 2xx means accepted, not proven delivery;
408/425/429/5xx and connection/timeouts retry. Other responses (including redirects) fail.
Booking Teams delivery uses `core.infrastructure.teams.service.post_teams_json()` for one
bounded HTTP attempt. The shared transport owns JSON serialization, timeouts, response
classification, response closure and sanitized transport logs; booking retains endpoint
allowlisting, verified-recipient payload construction, and durable retry policy. It disables
ambient proxies and redirects for this workflow. OTP retains the `send_ms_teams_notification()`
boolean compatibility wrapper and its explicitly configured proxy behavior.

Email uses `core.infrastructure.email.service.send_email()` with the existing
`emails/booking_confirmation.html` visual format and an allowlisted snapshot-only context.
Notification rendering does not invent a user's name, lab/equipment labels, project or
purpose, and has no CTA until a trusted booking detail URL is configured. Reminder copy
states that a notification does not change booking/resource status. The helper returns a
boolean, so a false result is retried by the booking delivery ledger.
Booking delivery sets `log_failure_details=False`, so helper failures are sanitized and
do not include recipient addresses or raw exception details. Raw transport exceptions,
response bodies, endpoint URLs and recipients must not be logged. Disable HTTP wire logs
and redact workflow URLs in platform error reporting/APM. The shared transport does not
log URLs, bodies, recipients, response bodies, or raw exception details. Network policy
must restrict egress to the approved workflow host.

The guarantee is **at-least-once attempted delivery**, bounded by expiry/retry policy,
not exactly once or guaranteed receipt. A crash after acceptance but before completion
can duplicate a message. Workflow consumers should deduplicate `event_id` for each private
recipient. Email has `X-LabMango-Event-ID`; transport-side dedupe is not assumed.
Notifications are best-effort across downtime: missed timely windows are not backfilled.

Creation/update expire after 24h; start expires at min(end,start+10m); inactivity expires
at min(end,collection+10m). Timely reminders revalidate immediately before outbound I/O.
There remains an unavoidable read/send race; no database locks are held across I/O.
Master disabled pauses collection/delivery. Disabled channels are skipped at delivery.
Changing cutoff forward expires rows preceding it. Events before activation are not collected:
start must be >= cutoff; inactive episode must be >= cutoff. No migration backfill.

## Configuration and workflow contract

All flags default false:

- `BOOKING_NOTIFICATIONS_ENABLED` — master switch.
- `BOOKING_NOTIFICATIONS_EMAIL_ENABLED` and `BOOKING_NOTIFICATIONS_TEAMS_ENABLED` — channel switches.
- `BOOKING_NOTIFICATIONS_ENABLEMENT_CUTOFF` — required ISO-8601 aware UTC timestamp when master enabled.
- `BOOKING_NOTIFICATIONS_TEAMS_WORKFLOW_URL` — dedicated administratively supplied secret endpoint.
  Never place its value in a command, log, document, ticket or test fixture.
- `BOOKING_NOTIFICATIONS_TEAMS_ALLOWED_HOSTS` — exact approved HTTPS host allowlist, no wildcard.
- `BOOKING_NOTIFICATIONS_QUEUE` — default `booking_notifications`; worker must consume it.

The workflow receives JSON `event_id`, `recipient_tenant_id`, `recipient_object_id`, `text`. It must deliver **only a
private chat to that verified directory object**, reject unavailable recipients, never broadcast/fallback to a
shared channel, deduplicate event IDs and provide its own bounded retry/failure alerting.
A 202 does not confirm the workflow's final private-chat action; operations must monitor
that downstream step. Outbound HTTP connect/read timeouts are 3/5 seconds. Booking email
uses the shared HTML email helper; SMTP connection timeout behavior is controlled by the
existing helper's Django mail backend configuration.
Application settings validate UTC cutoff and HTTPS/host/port/no-userinfo endpoint shape.
Production endpoint/identity/routing validation remains an operator responsibility.

## Scheduling, rollout, observability

After reviewed deployment and separately authorized additive migration, operators run the
`provision_booking_notification_schedules` management command. Default creates/updates
only this feature's schedules **disabled**. `--enable` explicitly enables them and requires
master/cutoff configuration. Repeating it is idempotent; unrelated schedules remain untouched.
Database beat is preserved: collect every 60s, deliver every 15s. Worker consumes configured
queue; explicit imports register nested tasks without enabling the legacy lifecycle task.
Each collection page handles at most 100 starts and 100 equipment candidates, keyset
continuations are separate tasks and finished streams are not rescanned in the chain.
Each delivery job claims at most five rows; soft/hard limits 80/90s, lease 120s.
Capacity is initially ~20 delivery rows/minute per schedule; tune schedule/concurrency
after measuring queue lag. Channels share queue capacity but not retry state.

Owner: Labs backend operations. Aggregate batch/outcome logs omit identifiers/payloads.
Use `booking_notification_health` for aggregate ready count, failed count, expired leases
and oldest pending age. Alert on any dead-letter increase, expired leases persisting >5m,
pending age >2m or no collector success >2m. Monitor broker queue depth and transport
latency in existing task monitoring. Export/alert wiring is a deployment task, not enabled
by this implementation. Investigate provider health/configuration without logging payloads;
do not automatically requeue permanent failures or stale reminders.

Retention: retain terminal ledger rows 30 days for operational diagnosis and dedupe;
do not purge pending/leased rows or rows for still-active bookings. Terminal rows protect
booking/user references (`PROTECT`). Cleanup requires a separately approved bounded job;
none runs implicitly. Deleting dedupe history can permit repeated events if qualifying
state remains, hence retain through booking end. JSON snapshot and delivery metadata are
internal operational data, not an employee activity history or management report.

Rollback: disable master and these beat schedules, drain workers; leave additive table in
place. Do not reverse the table migration with populated rows during ordinary rollback.
No production deploy, DB migration, schedule provisioning or live send performed here.

## Known gaps / required review gates

- Missing production booking-activation flow is deliberately NOT wired. Inactivity
  reminders require already approved `in_progress` bookings; no automatic activation added.
- Isolated tests use dummy DB and mocks. Real PostgreSQL transaction rollback, unique-key
  concurrency, `skip_locked`, lease recovery, migration application and query plans must
  be verified in authorized disposable CI before merge. No SQLite substitutes.
- Validate migration graph/model state offline; no production settings or env imports
  during local checks. Broader existing suite and production deployment checks not run.
- Workflow/private-UPN mapping, DNS/egress policy, downstream dedupe, monitoring export,
  schedule provisioning and retention cleanup need operational acceptance before enabling.

## Local verification handoff

Interpreter configured before execution: existing .venv, CPython 3.12.12; Django 5.2.13.
All Python verification uses `DJANGO_SETTINGS_MODULE=tests.notification_isolated_settings`,
which imports no environment settings and uses the dummy database backend. Focused tests
add a socket-level live-network blocker. No env files/secret values inspected, no real DB
connected or migrated, no live notifications, no schedule provisioning, no staging/merge/deploy.

- `python -m pytest -o addopts='' --ds=tests.notification_isolated_settings tests/unit/bench_booking_notifications -q`:
  passed (final count recorded in handoff). Initial collection error from incorrect Requests
  exception reference fixed and re-run successfully.
- `python -m ruff check` across touched Python boundaries: passed. Initial syntax/import/
  newline diagnostics fixed; final lint clean.
- `python -m mypy --config-file tests/notification_mypy.ini --follow-imports=silent` across
  13 implementation files: passed. Initial optional-type diagnostics fixed. Isolated config
  retains Django/DRF plugins; follows untyped Requests because stubs are absent; no dependency added.
- Migrations were later squashed into `labs/0001_initial` (2026-11-12); the additive-migration check no longer applies.
- `git diff --check` on modified existing implementation boundaries: passed.
- `python -m ruff format --check` on new implementation/test files: **failed**, nine files
  require formatting. No mass formatter was applied to avoid unrelated-file changes;
  formatting remains a review gate, not claimed clean.
- Editor diagnostics for seven principal new implementation files: no errors reported.
- PostgreSQL integration/concurrency, migration application, full suite, deploy checks,
  import-linter and independent review: **not run**. `lint-imports` unavailable locally.

