# API contract migration: frontend guide

What changes on the wire as the API is brought in line with the standards ([ADR 007](../architecture/decisions/007-api-contract-gate.md)).
Each section lists the renames for one feature. The OpenAPI schema in `openapi/` is authoritative; regenerate
client types from it.

## Patterns that apply everywhere

| Before | After | Rule |
| --- | --- | --- |
| User as `{id, username, display_name}` or `{id, username, full_name}` | `{id, name}`, `name` = full name, else username | REL-3 |
| Lookup with extras (`{id, name, code}`, status with `color_hex`) | `{id, name}`; read extras from the lookup's catalog endpoint | REL-3, REL-5 |
| `room_id` (and other bare `<relation>_id`) in a response | `room: {id, name}` | NAM-8, RW-2 |
| Enum as `"open"` | `{"value": "open", "label": "Open"}` | ENU-1 |
| `active`, `occupied`, `overdue` | `is_active`, `is_occupied`, `is_overdue` | NAM-2 |
| `created`, `modified` | `created_at`, `updated_at` | NAM-3 |
| `period_start` / `period_end` | `period: {starts_at, ends_at}` | NAM-9 |
| `valid_from` / `valid_until`, `starts_on` / `ends_on` (dates) | `start_date` / `end_date` | NAM-3, NAM-9 |
| Polymorphic `{type, id, name}` | `{id, name, type}` (`type` stays a plain string) | REL-13 |

Write bodies are unchanged unless a section says so: relations are still written as `<relation>_id`, enums as
the plain `value` string.

## Changes by feature

Sections are added as each feature is migrated.

### Shared Labs shapes (rooms, stations, benches, equipment, licenses, bookings, downtime)

| Field | Before | After |
| --- | --- | --- |
| `actor`, `creator`, `borrower`, `ended_by`, `performed_by`, `auditor` | `{id, username, display_name}` | `{id, name}` |
| `availability` | `{value, blocked_by: {type, id, name}, condition, reason}` (plain strings) | `{status, blocked_by: {id, name, type}, condition, reason}`; `status`, `condition`, `reason` are `{value, label}` |
| Department `active` | boolean | `is_active` |
| Service record `kind`, `result` | plain string | `{value, label}`; `created` → `created_at` |
