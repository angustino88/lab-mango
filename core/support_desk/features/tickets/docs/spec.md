# Feature Specification: Support Desk & Ticket Management (`core/support_desk/features/tickets`)

> Status: Implemented. Verified against `api/urls.py`, `api/views.py`, `application/policies.py` and migrations on 2026-11-09. This is the only ticket specification; it replaced the Jira-era draft (`docs/support-ticket-management-spec.md`, removed).

## 1. Domain Overview & Purpose
Internal incident / service-request desk with resource traceability (bench, equipment, license, station, room),
replacing the external Jira dependency. Modelled on ITIL service desks (Jira Service Management, Zendesk, ServiceNow):
typed tickets, impact/urgency-driven priority, SLA clocks, team queues, watchers, ticket links, CSAT and a dashboard.

## 2. Data Model & Invariants

### 2.1 `SupportTicket`
| Group | Fields |
|---|---|
| Identity | `key` (`SUP-000123`, immutable, unique), `number` (PG sequence `support_ticket_number_seq`), `idempotency_key` |
| Content | `subject` (200), `description`, `external_reference` (vendor RMA / legacy Jira key) |
| Classification | `ticket_type` (`incident`, `service_request`, `problem`, `change`, `question`), `source` (`web`, `email`, `phone`, `walk_in`, `api`, `system`), `impact` / `urgency` (`1` high … `3` low, optional), `category` FK, `priority` FK, `labels` M2M |
| Ownership | `requester`, `created_by`, `assignee`, `team` FK (defaults from `category.default_team`), `parent` FK (one level of sub-tickets) |
| Workflow | `status` FK, `version` (optimistic lock), `due_date`, `reopen_count` |
| Resolution | `resolution_code` (`fixed`, `workaround`, `cannot_reproduce`, `duplicate`, `wont_fix`, `user_error`, `vendor`), `resolution_summary`, `root_cause`, `resolved_by`, `resolved_at`, `closed_at` |
| SLA | `response_due_at`, `resolution_due_at`, `sla_paused_at`, `sla_paused_seconds`, `response_breached_at`, `resolution_breached_at`, `first_response_at` |
| CSAT | `csat_score` (1-5, DB check), `csat_comment`, `csat_submitted_at` |
| Timeline | `created_at`, `updated_at`, `last_activity_at` (bumped by every audit event except passive SLA events) |

Constraints: a ticket cannot be its own parent; sub-tickets are at most one level deep.

### 2.2 Configuration entities
- `SupportCategory` (`name`, `code` → options `sku`, `default_team`), `SupportPriority` (`rank`, `code`, `color_hex`, `response_target_minutes`, `resolution_target_minutes`, `is_default`).
- `SupportStatus` (`system_state` ∈ `open|active|waiting|done`, `color_hex`, `is_initial`, **`is_final`** = closed terminal status, **`pauses_sla`**). Validation: final ⇒ `done`; initial ⇒ `open`; `done` cannot pause SLA.
- `SupportStatusTransition` (`allowed_roles`, `requires_reason`, `requires_resolution`) - the only way status may change.
- `SupportTeam` (`code`, `lead`, `members`), `SupportLabel` (case-insensitively unique), `CannedResponse` (optional team scope; placeholders `{{requester_name}}`, `{{ticket_key}}`, `{{agent_name}}`).
- `SupportSettings` singleton: reopen/auto-close windows, attachment limits, comment edit window, `requesters_can_set_priority`, `sla_enabled`, `sla_at_risk_percent`, `csat_enabled`, `csat_window_days`, `default_ticket_type`.

### 2.3 Collaboration entities
`TicketWatcher` (unique per ticket+user), `TicketLink` (`relates_to`, `duplicates`, `blocks`, `caused_by`; unique, no self-links; `relates_to` is symmetric), `TicketComment`, `TicketAttachment`, `TicketResourceLink`.

### 2.4 `TicketActivity` (audit)
Append-only. Enforced by model `save/delete` guards **and** PostgreSQL triggers (`trg_prevent_ticket_activity_update|delete` calling `prevent_ticket_activity_modification()`, migration 0002). Event types now include `watcher_added/removed`, `ticket_linked/unlinked`, `sla_breached/paused/resumed`, `csat_submitted`. Field edits are recorded as `updated` with a `changes` map.

## 3. Business Rules

### 3.1 Roles and visibility (security)
- Support roles come only from Labs roles (`core.users.public`): Labs `admin` and superusers are support
  admins; Labs `coord` is a support agent; everyone else is a requester. Django group names grant nothing
  (owner decision 2026-11-11). Roles are configured on URS groups in Django admin.
- Agents/admins see all tickets. Requesters see tickets they requested, created, or watch.
- An invisible ticket is indistinguishable from a missing one (**404**), for list, detail, comments, activity, attachments (incl. download), resource history and every mutating command.
- Internal notes, restricted attachments and their activity entries are agent-only.

### 3.2 Priority resolution on create
`priority_id` → else derived from `impact × urgency` (score = impact + urgency − 1, spread over active priorities ordered by `rank`) → else the default priority → else `TicketCreationDisabledError`. If `requesters_can_set_priority` is off, a requester's `priority_id` is ignored.

### 3.3 SLA
- Deadlines are set at creation from the priority targets (wall-clock minutes). Disabled via `sla_enabled`; tickets with a target-less priority have none.
- Entering a `pauses_sla` status stores `sla_paused_at`; leaving it pushes pending due dates out by the paused time and accumulates `sla_paused_seconds`. A requester reply that auto-resumes a ticket (waiting → active) does the same.
- Only a **public reply by an agent other than the requester** sets `first_response_at` (internal notes never stop the response clock).
- Changing priority re-bases open deadlines on `created_at + target + paused`. Reopening restarts the resolution clock.
- `support_desk.flag_sla_breaches` stamps `*_breached_at` exactly once, writes an `sla_breached` activity and notifies assignee + team lead.
- API exposes `sla` = `{state, paused, response{state,due_at,breached_at}, resolution{…}}`, `state ∈ none|ok|at_risk|breached|paused|met`.

### 3.4 Notifications (transactional outbox)
Recipients: requester, assignee, **watchers** (never for internal notes), **team members** for new/routed tickets (all agents if no team). Outbox rows are leased (`SELECT … FOR UPDATE SKIP LOCKED` + 5-minute lease) so concurrent workers never double-send; e-mail bodies are HTML-escaped and deep links absolute (`SUPPORT_DESK_BASE_URL`).

### 3.5 Attachments
Type/size/count limits (from `SupportSettings`) and magic-byte checks. Scanning is pluggable: set `SUPPORT_DESK_ATTACHMENT_SCANNER` to a dotted callable `(attachment) -> AttachmentScanStatus`. Without it uploads are `clean` immediately and verified by SHA-256 integrity; with it uploads start `pending` and **cannot be downloaded** (409) until scanned clean.

## 4. API
Base `/api/support/`. All responses use the [standard envelope](../../../../../docs/api/response-standard.md). `{key}` is the ticket key. "any" means `HasAPIKey | IsAuthenticated`; "visible" applies §3.1. Generated contract: `openapi/support-desk-tickets.yml`.

| Method & Path | Access | Purpose |
|---|---|---|
| `GET/POST tickets` | any / any | List (scoped, filterable) / create |
| `GET tickets/stats?days=30` | agent | Workload, SLA health, throughput, CSAT |
| `GET/PATCH tickets/{key}` | visible (requester may edit only while `open`) | Detail / partial update (`version` required); `labels`, `team_id`, `parent_key` are agent-only; `null` clears `team_id`, `due_date`; empty `parent_key` clears parent |
| `POST tickets/{key}/assign` | agent | Assign / reassign (`version` optional) |
| `POST tickets/{key}/transitions` | per `SupportStatusTransition.allowed_roles` | Change status; accepts `reason`, `resolution_code` as the transition requires |
| `POST/DELETE tickets/{key}/resources` | link: agent, or a requester who can view the resource; unlink: agent | Link / unlink lab resources |
| `POST/DELETE tickets/{key}/watchers` | visible (self) / agent (others) | Follow / unfollow (`user_id` optional) |
| `GET/POST tickets/{key}/links`, `DELETE …/links/{id}` | read: visible; write: agent | Ticket links |
| `POST tickets/{key}/csat` | requester | Rate 1-5 within `csat_window_days` of resolution |
| `GET/POST tickets/{key}/comments`, `PATCH/DELETE …/comments/{id}` | visible; edit/delete by author within the edit window | Public replies and agent-only internal notes |
| `GET/POST tickets/{key}/attachments`, `DELETE …/attachments/{id}`, `GET attachments/{id}/download` | visible | Upload, remove, download (blocked until scanned clean, §3.5) |
| `GET tickets/{key}/activity` | visible | Audit trail (agent-only entries hidden from requesters) |
| `GET resources/{type}/{id}/tickets` | any (scoped) | Resource incident history |
| `GET {categories,priorities,statuses,teams,labels}/options` | any | Flat `{id, sku, name}` selectors ([ADR 002](../../../../../docs/architecture/decisions/002-catalog-and-selector-api.md)); category/team `sku` = `code`, priority `sku` = `code` or `null`, label/status `sku` = `null` |
| `GET {categories,priorities,statuses,teams,labels}`, `GET …/{id}` | any | Catalog read |
| `POST {categories,…}`, `PATCH/DELETE …/{id}` | admin | Catalog configuration |
| `GET canned-responses[?ticket=KEY]` | agent | Usable templates, optionally rendered for a ticket |
| `GET/POST admin/{transitions,canned-responses}`, `PATCH/DELETE …/{id}` | read: any; write: admin | Workflow and canned-response configuration |
| `GET/PATCH admin/settings` | read: any; write: admin | Singleton settings |

### Ticket list filters
`key, status, status_id, system_state, priority_id, category_id, requester_id, assignee_id, unassigned, team_id, no_team, ticket_type, source, impact, urgency, label, parent_key, watcher_id, resolution_code, external_reference, resource_type, resource_id, created_after/before, updated_after/before, resolution_due_after/before`; search over `key, subject, description, external_reference`; ordering by `priority, created_at, updated_at, last_activity_at, resolution_due_at, number, id`.

## 5. Background Tasks (Celery)
`process_notification_outbox`, `auto_close_resolved_tickets` (moves to the `is_final` status), `scan_pending_attachments`, **`flag_sla_breaches`** (schedule every 1-5 minutes).

## 6. Operational notes
- Migrations: one squashed `0001_initial` (2026-11-12, before production) creates the schema, the `pg_trgm` label search index, the ticket number sequence and the activity immutability triggers. Existing tickets get **no retroactive SLA**. `0005` adds the `pg_trgm` label search index (ADR 002).
- Not yet implemented (deliberate follow-ups): business-hours calendars, automatic assignment (round-robin / load based), e-mail-to-ticket ingestion, automation rules.
