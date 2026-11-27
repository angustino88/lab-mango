# Lab Assistant (chatbot) — API endpoint proposal

Status: **proposed, needs owner approval** · 2026-11-27 · Risk tier **T2** (new public API, authn/authz, booking writes)

The Lab Assistant is a separate application (the "assistant service"). The Lab Mango frontend embeds the
chat UI and signs the user in with the existing Entra ID (MSAL) login. The assistant service runs the LLM and
calls Lab Mango **as that user**. This document lists:

- **Part A**: the endpoints the assistant service exposes to the frontend.
- **Part B**: the Lab Mango endpoints the assistant uses as LLM tools. Most already exist. A few are new, and
  each one fills a gap found in the current API.

"Exists" means the route is in `openapi/openapi-full.json` on `main` (commit `8e3a619`). Response
shapes were not checked line by line against the assistant's needs.

---

## 0. Architecture and security decisions

```
Browser (Lab Mango FE, MSAL) ──Entra token (aud = assistant API)──▶ Assistant service ──OBO token (aud = Lab Mango API)──▶ Lab Mango /api/...
                                                                     │  LLM + tool router
                                                                     └─ conversation store, audit log
```

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | How the assistant authenticates to Lab Mango | **Entra On-Behalf-Of (OBO)**: the frontend gets a token for the assistant API, and the assistant exchanges it for a Lab Mango token. Alternative: the frontend sends a Lab Mango token for the assistant to pass through (simpler, but the assistant then holds a token that can do anything the user can) | Lab Mango keeps authorization server-side, deny-by-default and object-scoped (AGENTS.md rule 5). **No service account or superuser key** |
| D2 | Which tools the LLM sees | Filtered per user from `GET /api/users/me` permissions (see B0). A member never sees operator tools | Smaller prompt, fewer wrong tool calls. Lab Mango still enforces every call |
| D3 | Writes (create, change or cancel a booking; reserve equipment; approve) | **Two-step: preview, then confirm.** The LLM can only *propose* a write. The user clicks **Confirm** in the UI, and that click (not the LLM) sends the write with an `Idempotency-Key` | Prompt-injection and hallucination safety. Lab Mango sees one deliberate request, and a retry cannot create two bookings |
| D4 | Untrusted text | Booking reasons, equipment names, ticket text and other stored data go to the LLM as **data**, never as instructions | Any user can write text that another user's assistant reads |
| D5 | Audit | The assistant logs every tool call (user, tool, arguments, status, `request_id`). Lab Mango's existing audit covers the writes themselves | Lets you trace "the bot booked this" |
| D6 | Rate limits | Per-user limit on messages in the assistant; Lab Mango keeps its DRF throttles. Tool calls carry `X-Request-Id` and a client tag (e.g. `User-Agent: lab-assistant/1`) | Lab Mango can tell assistant traffic apart and limit it on its own |

---

## Part A — Assistant service API (frontend → assistant)

All routes need the user's Entra token. JSON envelope as in `docs/api/response-standard.md`.

| Method / path | Purpose |
|---|---|
| `GET /v1/capabilities` | What this user can ask for: enabled skills (`bookings`, `equipment`, ...) built from their Lab Mango permissions, plus suggested starter prompts. The UI uses it for the empty state |
| `POST /v1/conversations` | Start a conversation. Optional `context` (e.g. `{page: "bench", bench_id: 12}`) so "book this bench" works from a detail page |
| `GET /v1/conversations` | The user's own conversations, paginated |
| `GET /v1/conversations/{id}` | Conversation metadata |
| `DELETE /v1/conversations/{id}` | Delete one's own conversation (retention, privacy) |
| `GET /v1/conversations/{id}/messages` | Message history, paginated |
| `POST /v1/conversations/{id}/messages` | Send a user message. Response is **SSE stream** (`text/event-stream`): `token`, `tool_call` (name + status, for "Checking availability…"), `card` (structured result: booking list, bench list, equipment table), `action_proposal`, `done`, `error` |
| `POST /v1/conversations/{id}/actions/stop` | Stop a running answer |
| `GET /v1/action-proposals/{id}` | A proposed write: kind, a readable summary, the exact payload, `expires_at` (e.g. 10 min), state `pending/confirmed/rejected/expired/failed` |
| `POST /v1/action-proposals/{id}/actions/confirm` | The user confirms. The assistant checks the proposal is pending, not expired and owned by this user, then sends the Lab Mango write with `Idempotency-Key = proposal id`. Returns the Lab Mango result. Safe to repeat |
| `POST /v1/action-proposals/{id}/actions/reject` | The user declines. The LLM is told, so it can offer alternatives |
| `POST /v1/messages/{id}/feedback` | Thumbs up/down + optional comment (quality evaluation) |

---

## Part B — Lab Mango tools (assistant → Lab Mango, as the user)

### B0. Identity and tool filtering — all users

| Tool | Endpoint | State |
|---|---|---|
| `whoami` | `GET /api/users/me` (profile, roles, permissions) | Exists |

The tool list follows permissions (`core/users/permissions.py`):
`bench_booking.manage_own` → feature 1 · `lab_operations.manage` → feature 2 ·
`bench_booking.approve` / `manage_any` → operator booking tools.

### B1. Feature 1 — personal bookings and creating a bench booking (all users)

| Tool | Endpoint | State | Notes |
|---|---|---|---|
| `list_my_bookings` | `GET /api/labs/bench-bookings?view_side=my_booking&status=&starts_at_after=&starts_at_before=&ordering=starts_at` | Exists | "What are my bookings this week?" |
| `get_booking` | `GET /api/labs/bench-bookings/{booking_id}` · `GET /api/labs/bench-bookings/code/{booking_code}` | Exists | Look up by ID or by the code the user types |
| `find_bench` | `GET /api/labs/benches/booking-choices?q=&has_computing=` | Exists | Resolve "bench A-12" to an ID. **No time filter** (see gap G1) |
| `list_lab_projects` | `GET /api/labs/lab-projects/options` | Exists | `project_id` is required to create a booking |
| `find_available_benches` | **`GET /api/labs/benches/availability`** | **New (G1)** | Query: `starts_at`, `ends_at` (required), `type_id`, `bench_group_id`, `setup_location_id`, `has_computing`, `equipment_category`, `q`, `limit` (≤20). Returns benches free for the whole window, plus each busy bench's `next_free_at`. Respects lifecycle, downtime `booking_access` and the caller's role. Read-only |
| `check_booking` | **`POST /api/labs/bench-bookings/actions/check`** | **New (G2)** | Same body as create (`bench_id, starts_at, ends_at, project_id, reason`). **Writes nothing.** Returns `{bookable, needs_approval, conflicts[], blocked_by, suggestions[]}` with the same validation codes as create. This becomes the action-proposal preview |
| `create_booking` *(confirm only)* | `POST /api/labs/bench-bookings` + `Idempotency-Key` | Exists, **idempotency missing (G3)** | Sent only by `/v1/action-proposals/{id}/actions/confirm` |
| `reschedule_booking` *(confirm only)* | `PATCH /api/labs/bench-bookings/{booking_id}` | Exists | `starts_at`, `ends_at`, `bench_id`, `reason`, `project_id` |
| `cancel_booking` *(confirm only)* | `POST /api/labs/bench-bookings/{booking_id}/actions/cancel` | Exists | |
| `watch_bench_slot` *(confirm only)* | `POST /api/labs/bench-slot-watches` · `POST /api/labs/bench-bookings/{id}/actions/follow` | Exists | "Tell me when A-12 is free tomorrow afternoon" |
| `list_my_slot_watches` | `GET /api/labs/bench-slot-watches` | Exists | Includes `availability` (busy blocks, next free time) |

Example conversation: *"Book a bench with a PC tomorrow 9–12 for project X"* → `list_lab_projects` →
`find_available_benches` → `check_booking` → proposal card → user confirms → `create_booking`.

### B2. Feature 2 — equipment and resource lookup (lab operators, `lab_operations.manage`)

| Tool | Endpoint | State | Notes |
|---|---|---|---|
| `resolve_equipment_terms` | `GET /api/labs/equipment/filters` · `GET /api/labs/equipment-categories/options` · `.../equipment-kinds/options` · `.../equipment-types/options` · `.../equipment-manufacturers/options` · `.../equipment-product-models/options` | Exists | Map words such as "Keysight scope" to filter IDs before searching |
| `list_spec_definitions` | `GET /api/labs/equipment/reference-data/specification-definitions` | Exists | Which specs a category has (name, unit, value type) |
| `search_equipment` | `GET /api/labs/equipment?q=&category=&kind=&type=&manufacturer=&product_model_id=&status=&condition=&lifecycle_state=&assigned=&on_loan=&loan_overdue=&department_id=&owner_id=` | Exists | Attribute search. **Cannot filter by spec values or free time** (G4) |
| `count_equipment` | `GET /api/labs/equipment/facets?dimension=...` (same filters) | Exists | "How many oscilloscopes are out of service?" |
| `match_equipment` | **`POST /api/labs/equipment/actions/match`** | **New (G4)** | Read-only search with a structured body: `category`, `requirements: [{spec_definition_id, op: eq/gte/lte/in/contains, value}]`, optional `available_from/available_until` (no loan, reservation or downtime in the window), `location`, `limit` (≤50). Returns ranked units with `matched[]`, `missing[]`, `unknown[]` per requirement (so "≥ 1 GHz, 4 channels" shows near matches), plus current location (bench/station/room) and availability. POST only because the body is structured; it must not change anything (OpenAPI marks it read-only) |
| `get_equipment` | `GET /api/labs/equipment/{id}` · `GET /api/labs/equipment/{equipment_id}/placement` · `.../loan` | Exists | Details and specs; where it is; who has it |
| `bench_equipment` | `GET /api/labs/benches/{bench_id}/equipment` | Exists | "What is on bench A-12?" |
| `list_benches` / `rooms` / `stations` | `GET /api/labs/benches` · `/rooms` · `/stations` (+ `/status-summary`) | Exists | Resource lookups and status |
| `current_downtimes` | `GET /api/labs/downtimes?state=current,scheduled&resource_type=` | Exists | "What is in maintenance right now?" |
| `computing_activity` | `GET /api/labs/equipment/computing/activity-summary` | Exists | Which PCs are in use or offline |
| `loans_and_reservations` | `GET /api/labs/equipment-loans` · `GET /api/labs/equipment-reservations` | Exists | "Who has the spectrum analyzer?", overdue loans |
| `reserve_equipment` *(confirm only)* | `POST /api/labs/equipment-reservations` + `Idempotency-Key` | Exists | All-or-nothing reservation after `match_equipment` |
| `licenses` | `GET /api/labs/licenses?…` · `/licenses/status-summary` | Exists | Expiring or unassigned licenses |

### B3. Feature 3 — further features (proposed)

| # | Feature | Who | Endpoints | State |
|---|---|---|---|---|
| F1 | **Approval inbox**: "What bookings are waiting for me?", then approve or reject from chat | `bench_booking.approve` | `GET /api/labs/bench-bookings?approval_status=pending` · `POST .../{id}/actions/approve` · `.../actions/reject` *(confirm only)* | Exists |
| F2 | **Notifications digest**: "Anything new for me?" | All | `GET /api/notifications` · `GET /api/notifications/unread-count` · `POST /api/notifications/actions/mark-all-read` | Exists |
| F3 | **Report a problem** with a bench or device: a support ticket with the resource linked | All | `POST /api/support/tickets` (+ resource reference) | Exists (link fields not checked) |
| F4 | **Put a resource into downtime** after a report: "Mark scope SC-07 out of service until Friday" | Operators | `POST /api/labs/downtimes` *(confirm only)* · `.../actions/end` | Exists |
| F5 | **Lab status at a glance**: "How busy is lab 3 today?" | All (dashboard) / operators (analytics) | `GET /api/labs/dashboard/summary` · `GET /api/labs/benches/status-summary` · `GET /api/labs/analytics/booked-vs-used` · `.../lab-usage-by-timeframe` | Exists |
| F6 | **My usage**: "How many hours did I book this month?" | All | `GET /api/labs/leaderboard/users/{id}/weekly-usage` · `.../assessment` | Exists |
| F7 | **Smart rebooking**: when a booked bench goes into downtime, the assistant offers alternatives | All | `find_available_benches` (G1) + notification hook | New (needs G1) |
| F8 | **How-to and policy Q&A** (booking rules, SOPs, safety): retrieval over approved lab docs | All | Assistant-side search index; source documents chosen by the owner | New, assistant only |
| F9 | **Booking rules for the user**: max length, how far ahead they can book, when approval is needed | All | **`GET /api/labs/bench-bookings/policy`** | **New (G5)**. Stops the LLM guessing rules; `check_booking` stays the final word |

---

## Gaps in Lab Mango (new backend work)

| ID | Gap | Proposed endpoint | Owner feature | Risk |
|---|---|---|---|---|
| G1 | No search for benches free in a time window; `booking-choices` takes only `q` and `has_computing` | `GET /api/labs/benches/availability` | bench_bookings (reads benches via `public.py`) | T2 (booking rules, query budget; bounded `limit`) |
| G2 | No dry-run before create; the LLM would have to try the create to learn the errors | `POST /api/labs/bench-bookings/actions/check` | bench_bookings (reuse create validation; no write) | T2 |
| G3 | `POST /api/labs/bench-bookings` does not appear to honor `Idempotency-Key` (WRT-7/8); a retried confirm could make two bookings. The overlap constraint stops two bookings of the same bench, but idempotency should still be added | Add `Idempotency-Key` to booking create, patch and cancel | bench_bookings | T2 |
| G4 | Equipment search cannot filter by spec values (`ProductModelSpecification.value` is a string per definition) or by free time window | `POST /api/labs/equipment/actions/match` | equipment | T2 (numeric compare on text values needs a typed column or parsing; index plan) |
| G5 | Booking rules are only in code (`policies.default_approval_status`, ...) | `GET /api/labs/bench-bookings/policy` | bench_bookings | T1 |

Not needed in Lab Mango: conversation storage, action proposals and the LLM. All of these stay in the assistant
service, so Lab Mango gains no chat state.

## Rollout order (suggestion)

1. **Read-only pilot:** D1 OBO, B0, the B1 reads, the B2 reads and F2. No writes, so the security risk is low.
2. **G1 + G2 + G3**, then booking writes through confirm-only proposals.
3. **G4** equipment matching, then F1, F3 and F4.
4. F7–F9.

## Open questions for the owner

1. OBO (recommended) or pass-through token (D1)?
2. Should members see other users' names in availability results, or only "busy"?
3. May the assistant approve or reject bookings (F1), or only list them?
4. Which numeric specs must `match_equipment` support first (e.g. bandwidth, channels, voltage)? This decides
   whether G4 needs a typed value column.
5. Retention period for conversation history and the tool-call audit log.
