# Design Note: Platform Feedback Integrated with Support Desk

- **Status:** Implemented (branch `feat/support-feedback-integration`)
- **Risk Tier:** T2 High-risk (model migration + check constraint + additive OpenAPI schema change)
- **Scope:** `core/support_desk` (backend) and `src/features/lab-support` + `src/components/layout/AppHeader.tsx` (frontend)

## 1. Goal & Architectural Decision

Collect structured user feedback (bug reports, feature requests, UX/general feedback, and support requests) from anywhere in the Lab Mango web application **directly inside the existing Support Desk (`core/support_desk`)**, without introducing a separate web-rating subsystem or duplicating attachments, comments, audit trails, or notification outbox infrastructure.

### Why integrate with Support Desk instead of building a separate feedback app
- **Zero duplicated infrastructure:** Reuses `SupportTicket` numbering (`SUP-XXXXXX`), `TicketAttachment` (magic-byte check, SHA-256, MinIO/local storage, pluggable scanning, permission-scoped download), `TicketComment` (public replies + staff-only internal notes + canned responses), `TicketActivity` (PG-trigger append-only audit log), `SupportTeam` routing, `NotificationOutbox` (Email + in-app WebSocket), and per-ticket post-resolution **CSAT** (`POST /api/support/tickets/{key}/actions/submit-csat`).
- **Clean ITIL separation:** `feature_request` and `feedback` tickets bypass SLA clocks (`NON_SLA_TICKET_TYPES`) so product suggestions never cause false SLA breach alerts or skew agent SLA dashboards, while `bug` reports retain SLA tracking.

## 2. Schema & Invariants (`core/support_desk/migrations/0005_ticket_feedback_context.py`)

Additive fields on `SupportTicket`:
- `page_path`: `CharField(max_length=255, blank=True, default="")` — sanitized relative web app route (query string and fragment stripped).
- `client_context`: `JSONField(default=dict, blank=True)` — flat, allowlisted non-sensitive client diagnostics (`browser`, `os`, `viewport`, `theme`, `app_version`, `language`; max 64 chars per value).
- `ticket_type` & `SupportSettings.default_ticket_type`: extended `TicketType` enum with `bug`, `feature_request`, `feedback`.
- **PostgreSQL invariant:** `CheckConstraint(condition=Q(page_path="") | Q(page_path__startswith="/"), name="ticket_page_path_relative")`.

## 3. API Compatibility & Security

- **100% backward compatible:**
  - All existing endpoints, methods, and payloads continue to work unchanged.
  - `category_id` on `POST /api/support/tickets` is now optional (`allow_null=True`); when omitted, `resolve_category` picks an active category whose `code` matches `ticket_type`, falling back to `general`, then the first active category.
  - `page_path` and `client_context` are optional on `POST /api/support/tickets` and exposed on `TicketDetailSerializer`.
  - `can_submit_csat` (boolean, `NAM-2`) is exposed on `TicketDetailSerializer`, reusing a serializer-context-cached `SupportSettings.get_solo()` instance (zero additional SQL queries).
  - `page_path` added to `TICKET_FILTERS` (`exact`) and `search_fields`.
- **Security & privacy:**
  - `sanitize_page_path` strips `?query` and `#fragment` and rejects external URLs, protocol-relative paths, `..` traversal segments, and control characters.
  - `sanitize_client_context` enforces a strict key allowlist and string length bounds.
  - Existing object-level authorization (`visible_tickets`, `can_view_ticket`, `can_submit_csat`) remains deny-by-default.

## 4. Write Safety & Concurrency

- `create_ticket` validates and sanitizes `page_path` and `client_context` before opening `transaction.atomic()` and retains idempotent creation via `idempotency_key`.
- `update_ticket` re-evaluates open SLA deadlines atomically inside the optimistic-locked `version` update when reclassifying between SLA and non-SLA ticket types.
- `submit_csat` enforces requester-only ownership, `csat_enabled`, `SystemState.DONE`, and `csat_window_days`.

## 5. Frontend Experience (`beauty`)

- **Global Quick Trigger (`AppHeader.tsx`):** Accessible from every page (away from the bottom-right `<ChatWidget />`), opening the lazy-loaded `FeedbackSupportModal`.
- **`FeedbackSupportModal`:** Segmented icon-pill selector (`Support`, `Bug`, `Feature`, `Feedback`), dynamic per-type guided Details prompt with optional template insertion, privacy notice, `Attachments (0/5)` with square upload tile + drag-and-drop + clipboard paste (`Ctrl+V`), transparent opt-out page & browser diagnostics, and UUID `idempotency_key` submission.
- **Support Queue & Detail (`LabSupport.tsx`, `SupportTicketDetail.tsx`):** Type filter, new badges/icons/outcomes for `bug` / `feature_request` / `feedback`, CSAT KPI card for staff, diagnostic context card in Record Details, and interactive post-resolution `TicketCsatCard` (`1–5★` + comment) for requesters.
