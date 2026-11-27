# Lab Assistant (chatbot) — endpoint specification

Status: **proposed, needs owner approval** · 2026-11-27 · Risk tier **T2** (new public API, authn/authz,
booking writes, possible migration for spec matching)

The Lab Assistant is a separate application (the **assistant service**). The Lab Mango frontend embeds the chat
UI and signs the user in with the existing Entra ID (MSAL) login. The assistant service runs the LLM and calls Lab
Mango **as that user**. This document defines every endpoint the full ("advanced") assistant needs:

| Part | What | Owner |
|---|---|---|
| [A](#part-a--assistant-service-api) | Endpoints the assistant service exposes to the frontend (chat, actions, preferences, admin) | Assistant team |
| [B](#part-b--lab-mango-tool-catalog) | Lab Mango endpoints the assistant calls as LLM tools: existing ones plus new ones | Lab Mango backend |
| [C](#part-c--new-lab-mango-endpoints-full-contracts) | Full contracts for the **new** Lab Mango endpoints | Lab Mango backend |

"Exists" means the route is in `openapi/openapi-full.json` at commit `8e3a619`. Response shapes of existing routes
were not checked field by field against the assistant's needs (not verified).

---

## 0. Architecture and cross-cutting rules

```
Browser (Lab Mango FE)
   │  the user's Lab Mango access token (10 min), sent on every request
   ▼
Assistant service ── LLM, tool router, conversation store, proposal store, audit log
   │  the same token, forwarded for that request only
   ▼
Lab Mango /api/...  (all authorization stays here)
```

| # | Rule |
|---|---|
| X1 | **Auth: pass-through (decided).** The frontend sends its Lab Mango access token to the assistant as `Authorization: Bearer`, as it does to Lab Mango; the assistant forwards it unchanged. No service account, shared key or superuser. Lab Mango checks every call against that user's own permissions. The token lives 10 minutes (`SIMPLE_JWT`) and is held in frontend memory; the 7-day refresh token is an HttpOnly cookie the assistant never sees. See X9 for the safeguards this choice needs |
| X2 | **Tool filtering.** Tools are offered per user from `GET /api/users/me` permissions. Lab Mango still enforces each call (deny-by-default, object-scoped) |
| X3 | **Writes need human confirmation.** The LLM can only create an *action proposal*. The Lab Mango write is sent only by `POST /v1/action-proposals/{id}/actions/confirm`, after a user click, with `Idempotency-Key` = proposal UUID |
| X4 | **Stored text is data.** Booking reasons, equipment names, ticket text, notification text and uploads go to the LLM inside delimited data blocks, never as instructions |
| X5 | **Audit.** The assistant records every tool call: user, tool, arguments, Lab Mango status and `request_id`, latency, proposal id |
| X6 | **Traffic tagging.** Every Lab Mango call sends `X-Request-Id` and `User-Agent: lab-assistant/<version>`. Lab Mango's per-user throttle (`THROTTLE_USER`, default 300/min) still applies |
| X7 | **Time.** All times are RFC 3339 with offset. The assistant resolves "tomorrow 9" in the user's time zone (preference, else the lab time zone from `GET /api/labs/bench-bookings/policy`) and always repeats the absolute time back in the proposal |
| X9 | **Pass-through safeguards.** The token can do everything its user can, so: (a) the assistant never stores, logs or caches a token or the `Authorization` header, and holds it only for the request in flight; a stored proposal contains no credential, and `confirm` carries a fresh token; (b) the assistant treats the token as opaque and authenticates by calling `GET /api/users/me` with it (it holds no signing key), caching the result by token hash for at most the token's lifetime; (c) it calls only an allowlist of Lab Mango routes, the tools in Part B, and never a route or host taken from a client or model; (d) the Lab Mango base URL comes from a server-side allowlist keyed by a department or backend name sent by the frontend, never from a URL the client supplies (SSRF); (e) writes still need the confirm click (X3), which is the main guard against a manipulated model; (f) bearer tokens in headers, so no cookies and no CSRF surface on the assistant; (g) TLS only, between all three parts |
| X8 | **Envelope.** Both services follow `docs/api/response-standard.md`: `{"data": …, "meta": …}` or `{"error": {code, message, details, request_id}}`, slashless paths, `snake_case` query names |

---

## Part A — Assistant service API

Base path `/v1`. All routes need the user's Lab Mango access token (X1) unless marked. Ids are UUIDs.

### A1. Session and capabilities

| Method / path | Purpose |
|---|---|
| `GET /v1/me` | The user as the assistant sees them: Lab Mango id, name, roles, permissions (cached ≤ 5 min from `GET /api/users/me`), enabled skills |
| `GET /v1/capabilities` | Enabled skills (`bookings`, `equipment`, `approvals`, `operations`, `support`, `knowledge`), starter prompts per skill, limits (max message length, attachments allowed) |

```json
{"data": {
  "skills": [
    {"key": "bookings", "label": "Bench bookings", "starter_prompts": ["What are my bookings this week?", "Book a bench with a PC tomorrow 9–12"]},
    {"key": "equipment", "label": "Equipment lookup", "starter_prompts": ["Find a free 4-channel oscilloscope ≥ 1 GHz for Friday"]}
  ],
  "limits": {"max_message_chars": 4000, "max_attachments": 3, "attachment_types": ["image/png", "image/jpeg", "application/pdf"]}
}}
```

### A2. Conversations and messages

| Method / path | Purpose |
|---|---|
| `POST /v1/conversations` | Start a conversation. Body: `{"title"?: str, "context"?: {"page": "bench" \| "equipment" \| "booking" \| "dashboard", "resource_id"?: int}}`. `context` lets "book this bench" work from a detail page. `201` + `Location` |
| `GET /v1/conversations` | The user's conversations, newest first. Query: `page`, `page_size` (≤ 50), `q` (title search), `archived` |
| `GET /v1/conversations/{id}` | Metadata: title, context, created/updated, message count, open proposals |
| `PATCH /v1/conversations/{id}` | Rename or archive: `{"title"?, "archived"?}` |
| `DELETE /v1/conversations/{id}` | Delete one's own conversation and its messages. `204` |
| `GET /v1/conversations/{id}/messages` | History, oldest first, cursor pagination (`cursor`, `page_size` ≤ 100) |
| `POST /v1/conversations/{id}/messages` | Send a message and stream the answer (A3). Body: `{"content": str, "attachment_ids"?: [uuid], "client_message_id": uuid}`. `client_message_id` makes a resend safe |
| `POST /v1/conversations/{id}/messages/{message_id}/actions/regenerate` | Answer the same user message again (streams like A3) |
| `POST /v1/conversations/{id}/actions/stop` | Stop the running answer. Tool calls already sent are not undone; writes never run without confirmation anyway |

**Message object**

```json
{"id": "…", "role": "user" | "assistant", "content": "…", "created_at": "…",
 "cards": [ /* A3 card payloads */ ], "proposal_ids": ["…"], "tool_calls": [{"tool": "list_my_bookings", "status": "ok"}],
 "feedback": null | {"rating": "up" | "down"}}
```

### A3. Streaming events (`text/event-stream`)

The response to `POST …/messages` is a stream of Server-Sent Events. Each `data:` line is one JSON object.

| `event` | Payload | UI use |
|---|---|---|
| `message.started` | `{message_id}` | Show the answer bubble |
| `token` | `{text}` | Append text |
| `tool.started` | `{call_id, tool, label}` e.g. label "Checking bench availability" | Progress line |
| `tool.finished` | `{call_id, status: "ok" \| "denied" \| "error", error_code?}` | Progress line done. `denied` means Lab Mango returned `403` |
| `card` | `{type, data}`. Types: `booking_list`, `booking`, `bench_list`, `bench_schedule`, `equipment_list`, `equipment_match`, `approval_list`, `downtime_list`, `notification_list`, `stat`, `citation_list` | Render rich results instead of text tables |
| `action_proposal` | Proposal object (A4) | Render a Confirm/Reject card |
| `suggestion_chips` | `{chips: [str]}` | Quick follow-ups ("Show other times", "Notify me when free") |
| `message.completed` | `{message_id, usage: {input_tokens, output_tokens}}` | Finish |
| `error` | `{code, message}` codes: `rate_limited`, `upstream_unavailable`, `model_error`, `context_too_long`, `cancelled` | Show error |

Keep-alive comment every 15 s. A reconnect with `Last-Event-ID` resumes a stream that is still running.

### A4. Action proposals (confirmed writes)

A proposal is a Lab Mango write the LLM prepared and the user has not yet approved.

| Method / path | Purpose |
|---|---|
| `GET /v1/action-proposals?state=pending&conversation_id=` | The user's proposals |
| `GET /v1/action-proposals/{id}` | One proposal |
| `PATCH /v1/action-proposals/{id}` | Let the user edit allowed fields before confirming (e.g. `reason`, `project_id`). The assistant re-runs the preview check |
| `POST /v1/action-proposals/{id}/actions/confirm` | Send the write. The assistant checks: owner = caller, `state = pending`, not expired, permission still present. Then it calls Lab Mango with `Idempotency-Key = id`. Repeat-safe: a confirmed proposal returns the stored result |
| `POST /v1/action-proposals/{id}/actions/reject` | Decline. The LLM is told, so it can offer alternatives |

**Proposal object**

```json
{"data": {
  "id": "5d1c…", "conversation_id": "…", "state": "pending",
  "kind": "bench_booking.create",
  "summary": "Book bench A-12 (Room 3.01) on Fri 28 Nov 2026, 09:00–12:00 for project Apollo",
  "warnings": ["Needs approval: longer than 4 hours"],
  "payload": {"bench_id": 12, "starts_at": "2026-11-28T09:00:00+07:00", "ends_at": "2026-11-28T12:00:00+07:00", "project_id": 4, "reason": "Firmware validation"},
  "editable_fields": ["reason", "project_id"],
  "preview": { /* response of the Lab Mango check endpoint, if any */ },
  "expires_at": "2026-11-27T10:10:00Z",
  "result": null
}}
```

`state`: `pending` → `confirmed` | `rejected` | `expired` | `failed`. `result` holds the Lab Mango response
(`data` or `error`) after confirm.

**Proposal kinds** (each maps to exactly one Lab Mango write; see Part B for permissions)

| `kind` | Lab Mango write |
|---|---|
| `bench_booking.create` | `POST /api/labs/bench-bookings` |
| `bench_booking.create_series` | Several `POST /api/labs/bench-bookings`, one key each (`{proposal_id}:{n}`); the result lists each occurrence separately |
| `bench_booking.update` | `PATCH /api/labs/bench-bookings/{id}` |
| `bench_booking.cancel` | `POST /api/labs/bench-bookings/{id}/actions/cancel` |
| `bench_booking.approve` / `.reject` | `POST /api/labs/bench-bookings/{id}/actions/approve` / `reject` |
| `slot_watch.create` / `.cancel` | `POST /api/labs/bench-slot-watches` / `…/{id}/actions/cancel` |
| `bench_booking.follow` | `POST /api/labs/bench-bookings/{id}/actions/follow` |
| `equipment_reservation.create` / `.cancel` | `POST /api/labs/equipment-reservations` / `…/{batch_id}/actions/cancel` |
| `downtime.create` / `.end` | `POST /api/labs/downtimes` / `…/{id}/actions/end` |
| `support_ticket.create` | `POST /api/support/tickets` |
| `notification.mark_all_read` | `POST /api/notifications/actions/mark-all-read` (low risk; may skip confirmation, owner decision) |

### A5. Attachments

| Method / path | Purpose |
|---|---|
| `POST /v1/attachments` | Upload (multipart, ≤ 10 MB, types from `/v1/capabilities`). Returns `{id, kind, expires_at}`. Used for a photo of an asset label or a broken device |
| `GET /v1/attachments/{id}` | Metadata; owner only |
| `DELETE /v1/attachments/{id}` | Remove. Unused attachments expire after 24 h |

### A6. Preferences, memory and suggestions

| Method / path | Purpose |
|---|---|
| `GET /v1/me/preferences` / `PATCH /v1/me/preferences` | `{time_zone, language, default_project_id, preferred_bench_type_ids, preferred_location_ids, default_booking_hours, proactive_suggestions: bool}`. Used to fill gaps ("book my usual bench") |
| `GET /v1/me/memories` | Facts the assistant saved about the user ("prefers benches near the window"), each with source message |
| `DELETE /v1/me/memories/{id}` · `DELETE /v1/me/memories` | Forget one or all |
| `GET /v1/me/suggestions` | Proactive cards when chat opens, built live with the caller's token: upcoming booking in < 1 h, booking hit by a new downtime (with alternatives from C1), a pending approval older than 24 h (operators), overdue loan (operators). `{data: [{type, title, card, actions: [prompt]}]}` |

### A7. Feedback

| Method / path | Purpose |
|---|---|
| `POST /v1/messages/{id}/feedback` | `{"rating": "up" \| "down", "reason"?: "wrong" \| "unhelpful" \| "unsafe" \| "other", "comment"?: str}`. Idempotent per user and message |

### A8. Administration (assistant admins = Lab Mango `admin` role)

| Method / path | Purpose |
|---|---|
| `GET /v1/admin/usage?from=&to=&group_by=day\|skill\|tool` | Messages, users, tokens, cost, tool error rates |
| `GET /v1/admin/audit-events?user_id=&tool=&status=&from=&to=` | Tool-call audit log (X5). No message text unless retention policy allows |
| `GET /v1/admin/feedback?rating=down` | Feedback for quality review |
| `GET /v1/admin/tools` · `PATCH /v1/admin/tools/{tool}` | Turn a tool on/off or limit it to roles without redeploying (`{"enabled": bool, "roles": [...]}`) |
| `GET /v1/admin/knowledge-sources` · `POST …` · `POST …/{id}/actions/reindex` | Manage documents used for policy and how-to answers (C7) |
| `GET /v1/admin/evaluations` · `POST /v1/admin/evaluations` | Run the regression question set against a model or prompt version and see scores |

### A9. Operations (no user token; internal network only)

| Method / path | Purpose |
|---|---|
| `GET /healthz` | Process alive |
| `GET /readyz` | Database, LLM provider and Lab Mango (`GET /api/schema/` HEAD) reachable |

---

## Part B — Lab Mango tool catalog

Tool names are what the LLM sees. **Permission** is the Lab Mango permission (`core/users/permissions.py`) that
makes the tool visible. "(confirm)" means the tool only creates an A4 proposal.

### B0. Identity and resolution

| Tool | Endpoint | Permission | State |
|---|---|---|---|
| `whoami` | `GET /api/users/me` | any signed-in user | Exists |
| `resolve_resource` | **`GET /api/labs/resources/lookup`** (C6) | any; results filtered by what the user may read | **New** |
| `booking_policy` | **`GET /api/labs/bench-bookings/policy`** (C5) | `bench_booking.manage_own` | **New** |

### B1. Bookings — all users

| Tool | Endpoint | Permission | State |
|---|---|---|---|
| `list_my_bookings` | `GET /api/labs/bench-bookings?view_side=my_booking&status=&approval_status=&starts_at_after=&starts_at_before=&ordering=starts_at` | `bench_booking.manage_own` | Exists |
| `get_booking` | `GET /api/labs/bench-bookings/{booking_id}` · `GET /api/labs/bench-bookings/code/{booking_code}` | `bench_booking.manage_own` | Exists |
| `find_bench` | `GET /api/labs/benches/booking-choices?q=&has_computing=` | `bench_booking.manage_own` | Exists |
| `list_lab_projects` | `GET /api/labs/lab-projects/options` | `bench_booking.manage_own` | Exists |
| `find_available_benches` | **`GET /api/labs/benches/availability`** (C1) | `bench_booking.manage_own` | **New** |
| `bench_schedule` | **`GET /api/labs/benches/availability?bench_id=…`** (C1, single bench, busy periods) | `bench_booking.manage_own` | **New** |
| `check_booking` | **`POST /api/labs/bench-bookings/actions/check`** (C2) | `bench_booking.manage_own` | **New** |
| `create_booking` (confirm) | `POST /api/labs/bench-bookings` + `Idempotency-Key` | `bench_booking.manage_own` | Exists; **key support new (C3)** |
| `create_booking_series` (confirm) | C2 with `occurrences[]`, then one create per occurrence | `bench_booking.manage_own` | Uses C2 + C3 |
| `reschedule_booking` (confirm) | `PATCH /api/labs/bench-bookings/{booking_id}` + `Idempotency-Key` | owner, or `bench_booking.manage_any` | Exists; **key new (C3)** |
| `cancel_booking` (confirm) | `POST /api/labs/bench-bookings/{booking_id}/actions/cancel` + `Idempotency-Key` | owner, or `bench_booking.manage_any` | Exists; **key new (C3)** |
| `follow_booking` (confirm) | `POST /api/labs/bench-bookings/{booking_id}/actions/follow` | `bench_booking.manage_own` | Exists |
| `watch_bench_slot` (confirm) | `POST /api/labs/bench-slot-watches` | `bench_booking.manage_own` | Exists |
| `list_my_slot_watches` / `cancel_slot_watch` (confirm) | `GET /api/labs/bench-slot-watches` · `POST …/{watch_id}/actions/cancel` | `bench_booking.manage_own` | Exists |

### B2. Equipment and resources — lab operators

| Tool | Endpoint | Permission | State |
|---|---|---|---|
| `equipment_filter_options` | `GET /api/labs/equipment/filters` · `…/equipment-categories/options` · `…/equipment-kinds/options` · `…/equipment-types/options` · `…/equipment-manufacturers/options` · `…/equipment-product-models/options` | `lab_operations.manage` | Exists |
| `list_spec_definitions` | `GET /api/labs/equipment/reference-data/specification-definitions` | `lab_operations.manage` | Exists |
| `search_equipment` | `GET /api/labs/equipment?q=&category=&kind=&type=&manufacturer=&product_model_id=&status=&condition=&lifecycle_state=&assigned=&on_loan=&loan_overdue=&department_id=&owner_id=` | `lab_operations.manage` | Exists |
| `count_equipment` | `GET /api/labs/equipment/facets?dimension=` (same filters) | `lab_operations.manage` | Exists |
| `match_equipment` | **`POST /api/labs/equipment/actions/match`** (C4) | `lab_operations.manage` | **New** |
| `get_equipment` | `GET /api/labs/equipment/{id}` · `…/{equipment_id}/placement` · `…/{equipment_id}/loan` · `…/{equipment_id}/status-changes` | `lab_operations.manage` | Exists |
| `bench_equipment` | `GET /api/labs/benches/{bench_id}/equipment` | `lab_operations.manage` | Exists |
| `list_benches` / `list_rooms` / `list_stations` | `GET /api/labs/benches` · `/rooms` · `/stations` and their `/status-summary` | `lab_operations.manage` | Exists |
| `list_downtimes` | `GET /api/labs/downtimes?state=&resource_type=&resource_id=` | `lab_operations.manage` | Exists |
| `create_downtime` / `end_downtime` (confirm) | `POST /api/labs/downtimes` · `POST …/{downtime_id}/actions/end` | `lab_operations.manage` | Exists |
| `computing_activity` | `GET /api/labs/equipment/computing/activity-summary` · `GET /api/labs/equipment/{equipment_id}/activity` | `lab_operations.manage` | Exists |
| `list_loans` / `list_reservations` | `GET /api/labs/equipment-loans` · `GET /api/labs/equipment-reservations` | `lab_operations.manage` | Exists |
| `reserve_equipment` / `cancel_reservation` (confirm) | `POST /api/labs/equipment-reservations` · `POST …/{batch_id}/actions/cancel` | `lab_operations.manage` | Exists (key support not verified) |
| `list_licenses` | `GET /api/labs/licenses?…` · `/licenses/status-summary` | `lab_operations.manage` | Exists |
| `monitoring_events` | `GET /api/labs/monitoring-events?…` | `lab_operations.manage` | Exists |

### B3. Approvals — booking approvers

| Tool | Endpoint | Permission | State |
|---|---|---|---|
| `list_pending_approvals` | `GET /api/labs/bench-bookings?approval_status=pending&ordering=starts_at` | `bench_booking.approve` | Exists |
| `approve_booking` / `reject_booking` (confirm) | `POST /api/labs/bench-bookings/{booking_id}/actions/approve` / `reject` + `Idempotency-Key` (UUID, already required) | `bench_booking.approve` | Exists |
| `list_all_bookings` | `GET /api/labs/bench-bookings?view_side=booking_calendar&bench_id=&creator_id=&…` | `bench_booking.manage_any` | Exists |

### B4. Insight, notifications, support, knowledge

| Tool | Endpoint | Permission | State |
|---|---|---|---|
| `lab_status` | `GET /api/labs/dashboard/summary` · `GET /api/labs/benches/status-summary` | `dashboard.read` | Exists |
| `my_usage` | `GET /api/labs/leaderboard/users/{id}/weekly-usage` · `…/assessment` | `leaderboard.read` (own) | Exists |
| `lab_analytics` | `GET /api/labs/analytics/booked-vs-used` · `…/lab-usage-by-timeframe` · `…/equipment-availability` · `…/user-booking-efficiency` | `lab_operations.manage` | Exists |
| `list_notifications` / `unread_count` | `GET /api/notifications` · `GET /api/notifications/unread-count` | any | Exists |
| `mark_notifications_read` (confirm or direct) | `POST /api/notifications/actions/mark-all-read` · `…/{notification_id}/actions/mark-read` | any | Exists |
| `create_support_ticket` (confirm) | `POST /api/support/tickets` | any (body fields not verified) | Exists |
| `my_support_tickets` | `GET /api/support/tickets` | any | Exists |
| `search_knowledge` | Assistant-side index of approved documents (A8 knowledge sources); answers cite their source | any | **New, assistant only** |

---

## Part C — New Lab Mango endpoints: full contracts

All follow `docs/api/response-standard.md` and `request-standard.md`. Each is read-only unless stated, bounded
(fixed `limit` caps) and checks permissions server-side, scoped to each object. Feature owner is in brackets.

### C1. `GET /api/labs/benches/availability` — free benches and busy periods [bench_bookings]

**Status: implemented.** The response is one object (`ENV-6` allows no ad-hoc `meta` keys), booleans follow NAM-2, and
busy reasons are only `booking` and `downtime` (benches not in service, or whose station or room is not, are never
listed). `q` matches name or SKU. Six queries whatever the number of benches.

**Why:** `GET /api/labs/benches/booking-choices` cannot filter by time, so "find a free bench tomorrow 9–12" and
"when is A-12 free this week?" are impossible today.

**Permission:** `bench_booking.manage_own`. Downtime `booking_access = lab_operators` windows count as free only for
callers with `bench_booking.book_during_downtime`.

| Query | Type | Notes |
|---|---|---|
| `starts_at`, `ends_at` | RFC 3339 / date | Required. Window ≤ 14 days |
| `bench_id` | int, comma list ≤ 20 | Restrict to these benches (single-bench schedule) |
| `type_id`, `bench_group_id`, `setup_location_id` | int, comma list | Same meanings as `GET /api/labs/benches` |
| `has_computing` | bool | Same as booking-choices |
| `q` | string 1–100 | Bench name or UID |
| `min_free_minutes` | int ≥ 10 | Return benches with any free period at least this long, not only fully free (for "any 2 hours tomorrow") |
| `mode` | `fully_free` (default) \| `any_free` | |
| `limit` | int ≤ 20, default 10 | No pagination: this is a ranked answer, not a listing |

**Response `200`**

```json
{"data": {
  "window_starts_at": "2026-11-28T09:00:00+07:00", "window_ends_at": "2026-11-28T17:00:00+07:00",
  "is_truncated": false,
  "benches": [
    {"bench": {"id": 12, "uid": "…", "name": "A-12"},
     "station": {"id": 7, "uid": "…", "name": "Station 2"},
     "room": {"id": 3, "uid": "…", "name": "Room 3.01"},
     "type": {"id": 2, "name": "Firmware bench"},
     "has_computing": true,
     "is_fully_free": false,
     "is_favorite": true,
     "next_free_at": "2026-11-28T09:00:00+07:00",
     "free_periods": [{"starts_at": "2026-11-28T09:00:00+07:00", "ends_at": "2026-11-28T13:00:00+07:00"}],
     "busy_periods": [{"starts_at": "2026-11-28T13:00:00+07:00", "ends_at": "2026-11-28T17:00:00+07:00", "reason": {"value": "booking", "label": "Booked"}}]}
  ]}}
```

- `busy_periods[].reason`: `booking` or `downtime`. **Other users' names, booking codes and booking reasons are never
  returned** (open question Q2).
- Ranking: fully free first, then favorites, then the longest free period, then name.
- Errors: `400 validation_failed` (bad range, window > 14 days, `min_free_minutes` without `mode=any_free`),
  `400 invalid_query` (unknown parameter), `403`.

### C2. `POST /api/labs/bench-bookings/actions/check` — booking preview, no write [bench_bookings]

**Status: implemented**, including `suggest_alternatives`. Field names follow NAM-2: `is_bookable`, `can_book_all`, `approval_status`.

**Why:** the assistant must show a correct preview before the user confirms. Today the only way to learn whether a
booking works is to create it.

**Permission:** as create (`bench_booking.manage_own`; editing another user's booking needs `manage_any`).
**Writes nothing**, takes no locks, needs no `Idempotency-Key`. The result is advice: create still checks again
under its own locks.

**Request**

```json
{"bench_id": 12, "starts_at": "2026-11-28T09:00:00+07:00", "ends_at": "2026-11-28T12:00:00+07:00",
 "project_id": 4, "reason": "Firmware validation",
 "booking_id": null,
 "occurrences": null,
 "suggest_alternatives": true}
```

- `booking_id`: set to check a *change* of an existing booking (same rules as PATCH).
- `occurrences`: optional list (≤ 10) of `{starts_at, ends_at}` for a series. The bench, project and reason stay
  the same. Each occurrence is checked on its own.
- Unknown fields → `422` (strict writer).

**Response `200`** (also when the booking is not possible: the check itself succeeded)

```json
{"data": {
  "results": [{
    "starts_at": "2026-11-28T09:00:00+07:00", "ends_at": "2026-11-28T12:00:00+07:00",
    "is_bookable": false,
    "approval_status": {"value": "approved", "label": "Approved"},
    "problems": [{"code": "bench_booking_conflict", "field": null, "message": "The bench is not free for the requested period."}],
    "alternatives": [
      {"bench": {"id": 15, "uid": "…", "name": "A-15"}, "starts_at": "2026-11-28T09:00:00+07:00", "ends_at": "2026-11-28T12:00:00+07:00"},
      {"bench": {"id": 12, "uid": "…", "name": "A-12"}, "starts_at": "2026-11-28T12:00:00+07:00", "ends_at": "2026-11-28T15:00:00+07:00"}]}],
  "can_book_all": false}}
```

- `problems[].code` uses the **same codes as create and PATCH** (e.g. `bench_booking_conflict`,
  `lab_project_not_found`, field validation codes for minimum duration, start in the past, bench not in service, no
  computing, downtime), so preview and real write never disagree in wording.
- `approval_status`: the approval the booking would have after the write; `pending` when the duration is over `LONG_BOOKING_APPROVAL_THRESHOLD` (4 h today).
- Field problems use code `invalid` with the field name, as the write's `422` details do.
- `alternatives` (only with `suggest_alternatives`, only for a valid period that is not bookable): up to two free
  benches of the same type for the same period, then the same bench's next free slot of the same length within a day.
  A change does not count its own slot as busy. Free now, not held.
- Errors (request itself bad): `400 invalid_request`, `404` bench, project or booking not visible to the caller,
  `403 permission_denied`.
- Implementation: reuse the create and update policy functions (`application/policies.py`) on a read-only
  snapshot. No copy of the rules.

### C3. `Idempotency-Key` on booking create, change and cancel [bench_bookings]

**Status: implemented (phase 1).** Receipts live in `BenchBookingWriteReceipt` (migration `labs.0006`). An API-key caller sending a key gets `400 idempotency_key_unsupported`.

**Why:** today only approve and reject (and reference-data create) honor `Idempotency-Key`
(`core/labs/features/bench_bookings/api/views.py:266`). A retried confirm after a timeout must not make a second
booking or fail with a confusing conflict (WRT-7, WRT-8).

| Route | Change |
|---|---|
| `POST /api/labs/bench-bookings` | Accept `Idempotency-Key` (UUID). **Optional** for compatibility; the assistant always sends it |
| `PATCH /api/labs/bench-bookings/{booking_id}` | Same |
| `POST /api/labs/bench-bookings/{booking_id}/actions/cancel` | Same |
| `POST /api/labs/bench-bookings/code/{booking_code}/actions/cancel` | Same |

Behavior, matching the existing approve/reject handling: same key + same user + same body → replay the stored first
response with `Idempotency-Replayed: true`. Same key + different body → `422 idempotency_key_reuse`. A key that is
not a UUID → `400 invalid_idempotency_key`. Key lifetime ≥ 24 h. The race guard stays the database overlap
constraint; the key only makes retries safe. Making the key **required** later is a breaking change and needs its own
plan.

### C4. `POST /api/labs/equipment/actions/match` — equipment by specs and free time [equipment]

**Status: implemented**, with the `value_number` migration (`labs.0007`, a PostgreSQL generated column, so nothing
can leave it stale). Differences from the draft below: filters are ids (`category_id`, `kind_id`, `type_id`,
`manufacturer_id`, `product_model_id`, `department_id`, `room_id`); the response is
`{"is_truncated", "matches": [...]}` and each match has `is_full_match`, `location` (current bench, station, room or
note, as text), `condition` and `is_on_loan` instead of `placement`/`availability` objects; `status` is
`{value, label}`. With a window, busy units are left out rather than marked. Four queries whatever the size.

**Why:** `GET /api/labs/equipment` filters by category, model and status, not by spec values
(`ProductModelSpecification.value`, stored as text) or by time window. Operators ask "a 4-channel scope ≥ 1 GHz free
on Friday".

**Permission:** `lab_operations.manage`. **Read-only.** It uses POST because the requirements are a structured
list; OpenAPI marks it safe, and it is never cached as a write.

**Request**

```json
{"category": "oscilloscope",
 "kind": null, "type": null, "manufacturer": null, "product_model_id": null,
 "requirements": [
   {"spec_definition_id": 31, "op": "gte", "value": "1", "unit": "GHz", "required": true},
   {"spec_definition_id": 32, "op": "gte", "value": "4", "required": true},
   {"spec_definition_id": 40, "op": "in", "value": ["USB", "LAN"], "required": false}
 ],
 "available_from": "2026-11-28T08:00:00+07:00", "available_until": "2026-11-28T17:00:00+07:00",
 "location": {"room_id": null, "setup_location_id": null, "department_id": null},
 "include_near_matches": true,
 "limit": 20}
```

| Field | Rules |
|---|---|
| `requirements[]` | ≤ 10. `op`: `eq`, `neq`, `gte`, `lte`, `between` (`value: [min, max]`), `in`, `contains`. Numeric ops only for `value_type = number` definitions; `unit` is converted to the definition's unit (SI prefixes) or rejected |
| `required` | `false` means it affects ranking only |
| `available_from/until` | Optional, ≤ 31 days. Excludes units with an overlapping loan, reservation or downtime, units whose lifecycle state is not usable, and condition `out_of_service` |
| `limit` | ≤ 50 |

**Response `200`**

```json
{"data": [
  {"equipment": {"id": 501, "uid": "EQ-0501", "name": "Scope SC-07"},
   "product_model": {"id": 88, "name": "Keysight DSOX4104A"},
   "score": 1.0,
   "requirements": [
     {"spec_definition_id": 31, "name": "Bandwidth", "status": "matched", "actual": "1 GHz"},
     {"spec_definition_id": 32, "name": "Channels", "status": "matched", "actual": "4"},
     {"spec_definition_id": 40, "name": "Interface", "status": "unknown", "actual": null}],
   "placement": {"bench": {"id": 12, "uid": "B-0012", "name": "A-12"}, "room": {"id": 3, "uid": "R-0301", "name": "Room 3.01"}},
   "availability": {"available": true, "busy_periods": []},
   "condition": {"value": "operational", "label": "Operational"},
   "on_loan": false}
],
 "meta": {"matched_count": 3, "near_match_count": 2, "truncated": false}}
```

- `requirements[].status`: `matched`, `missed`, `unknown` (the model has no value for that spec).
- Near matches (`include_near_matches`) miss at most one required requirement and come after full matches.
- Errors: `400 invalid_query`, `422 validation_failed` (unknown definition, numeric op on a text spec, bad unit).
- Numbers: `value_number` holds `value` as `numeric(38, 12)` when it is a plain decimal (sign, point or comma, at
  most 24 integer digits), else null; indexed with `definition`. Exponents such as `1e3` are not numbers here.

### C5. `GET /api/labs/bench-bookings/policy` — the caller's booking rules [bench_bookings]

**Status: implemented (phase 1).** No `ETag` yet; `Cache-Control: private, max-age=300`.

**Why:** the rules live only in code (`application/policies.py`). The assistant should explain them and plan
around them, not guess.

**Permission:** `bench_booking.manage_own`. Values reflect the caller's role.

```json
{"data": {
  "time_zone": "Asia/Ho_Chi_Minh",
  "min_duration_minutes": 10,
  "start_grace_minutes": 10,
  "approval_required_above_minutes": 240,
  "max_horizon_days": null,
  "is_computing_required": true,
  "can_book_during_operator_downtime": false,
  "can_manage_others_bookings": false,
  "can_approve": false,
  "slot_watch": {"is_enabled": true, "lead_minutes": 15, "max_active": 20}
}}
```

`null` means no limit. Values come from the same constants and settings the commands use, so they cannot drift.
Cacheable per user (`Cache-Control: private, max-age=300`).

### C6. `GET /api/labs/resources/lookup` — turn a name or code into a resource [labs, composes features via `public.py`]

**Status: implemented** as feature `core/labs/features/resource_lookup`. Matching is exact UID, exact SKU, exact name,
prefix, then contains (no trigram ranking). `type` and `match` are `{value, label}`; each row also carries `sku`.
**Lab operators only** (`lab_operations.manage`): members are refused with `403`. The access-policy test lists the routes members may read and this one is deliberately not on it. Members find benches with `benches/booking-choices?q=` and `benches/availability?q=`.

**Why:** users type "A-12", "SC-07", a UID or a SKU, or the assistant reads one from a label photo. Today each
resource type has its own list, so the assistant would need up to five searches.

**Permission:** lab operators (`lab_operations.manage`): rooms, stations, benches, equipment and licenses.

| Query | Notes |
|---|---|
| `q` | Required, 1–100 chars. Exact UID/SKU first, then name prefix, then trigram match |
| `types` | Comma list: `room`, `station`, `bench`, `equipment`, `license`. Default: everything the caller may read |
| `limit` | ≤ 10 per type, default 5 |

```json
{"data": [
  {"type": {"value": "equipment", "label": "Equipment"}, "match": {"value": "sku_exact", "label": "Exact SKU"},
   "resource": {"id": 501, "uid": "…", "name": "Scope SC-07"}, "sku": "SC-07", "context": "A-12"},
  {"type": {"value": "bench", "label": "Bench"}, "match": {"value": "prefix", "label": "Starts with"},
   "resource": {"id": 12, "uid": "…", "name": "A-12"}, "sku": "BN-A12", "context": "Station 2 · Room 3.01"}
]}
```

Errors: `400 invalid_query`. A useful command palette for the web app too.

### C7. Not a Lab Mango endpoint: knowledge sources

Policy and how-to answers ("Can I bring my own laptop?", calibration steps) come from documents the owner approves.
The assistant indexes them (A8) and cites the source in a `citation_list` card. Lab Mango gets no new endpoint. If
lab SOPs later live in Lab Mango, add a read-only document endpoint then.

---

## Feature → endpoint map

| Feature | Who | Assistant (A) | Lab Mango (B/C) |
|---|---|---|---|
| My bookings Q&A | All | A2, A3 | `list_my_bookings`, `get_booking` |
| Book a bench by need and time | All | A2–A4 | C1, C2, `create_booking` + C3 |
| Recurring booking ("every Monday 9–12 for 4 weeks") | All | A4 `create_series` | C2 `occurrences`, C3 |
| Reschedule or cancel | All | A4 | C2 `booking_id`, PATCH/cancel + C3 |
| Notify me when free | All | A4 | slot watches, follow |
| "Book my usual bench" | All | A6 preferences/memory | C1, C2 |
| Proactive reminders and rebooking after downtime | All | A6 suggestions | `list_my_bookings`, `list_notifications`, C1 |
| Booking rules Q&A | All | A3 | C5 + knowledge (C7) |
| Equipment by spec and time | Operators | A3 `equipment_match` card | C4, C6, B2 resolvers |
| Where is / who has device X | Operators | A5 label photo | C6, `get_equipment` placement and loan |
| Reserve matched equipment | Operators | A4 | `reserve_equipment` |
| Put a resource into downtime | Operators | A4 | `create_downtime` |
| Approval inbox | Approvers | A4, A6 suggestions | B3 |
| Lab status and usage | All / operators | A3 `stat` card | B4 |
| Report a problem | All | A4, A5 photo | `create_support_ticket`, C6 |
| Admin, quality, cost | Assistant admins | A8 | — |

## New Lab Mango work summary

| ID | Endpoint | Migration | Tier | State |
|---|---|---|---|---|
| C3 | `Idempotency-Key` on booking create, PATCH, cancel | `labs.0006` (`BenchBookingWriteReceipt`) | T2 | Implemented |
| C2 | `POST /api/labs/bench-bookings/actions/check` (+ `suggest_alternatives`) | No | T2 | Implemented |
| C5 | `GET /api/labs/bench-bookings/policy` | No | T1 | Implemented |
| C1 | `GET /api/labs/benches/availability` | No (index use not checked with `EXPLAIN` on production-sized data) | T2 | Implemented |
| C6 | `GET /api/labs/resources/lookup` | No | T2 | Implemented |
| C4 | `POST /api/labs/equipment/actions/match` | `labs.0007` (`value_number` generated column + index) | T2 | Implemented |

All six are on branch `claude/admiring-shannon-ta8b0l`, not merged: T2 review and owner approval are still needed.

## Rollout

1. **Read-only pilot:** pass-through auth with X9, A1–A3, A7, A9, read tools in B1–B4. No proposals yet.
2. **Booking writes:** C3, C2, C5, then A4 for booking create, change and cancel and for slot watches.
3. **Finding things:** C1, C6, A6 preferences and suggestions, B3 approvals.
4. **Operators advanced:** C4 (with migration), reservations and downtime proposals, A5 attachments.
5. **Knowledge and admin:** C7 knowledge sources, A8 evaluations.

## Decisions

Owner decision on Q1, and recommended defaults for the rest (owner said to take the best choice; change any of
them before build):

| # | Question | Decision |
|---|---|---|
| Q1 | Auth between assistant and Lab Mango | **Pass-through** of the user's Lab Mango access token, with the safeguards in X9. A scoped Microsoft access token (new scope, endpoints opted in with `with_entra_access_token()`) stays an option for later; it would need its own design note and approval |
| Q2 | May members see who booked a busy bench? | **No.** Busy time is "Booked" or "Downtime" only (as built) |
| Q3 | May approvers approve or reject from chat? | **Yes, through the confirm card only.** Lab Mango still refuses self-approval and non-approvers |
| Q4 | Which numeric specs first for C4? | **No fixed list.** Matching is generic over any `number` specification definition (built) |
| Q5 | Retention | **Default:** conversations 90 days or until the user deletes them; tool-call audit 1 year, metadata only (user, tool, status, `request_id`, latency, proposal id) with no message text; attachments 24 hours if unused. Needs owner confirmation against policy |
| Q6 | Skip confirmation for `notification.mark_all_read`? | **Yes**, it is low risk and reversible by the user. Every other write confirms |
| Q7 | Maximum booking horizon? | **None**, as in the code; `max_horizon_days` stays `null` |
