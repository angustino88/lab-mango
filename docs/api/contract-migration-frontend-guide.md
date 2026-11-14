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

### Catalog (reference-data) records, all features

| Field | Before | After |
| --- | --- | --- |
| Parent relation, e.g. `city_id`, `country_id`, `vendor_id`, `category_id` | bare integer | relation object named after the field: `city: {id, name}` |
| Many-to-many, e.g. `categories` | array of ids | array of `{id, name}`; written as `category_ids` |
| `active` (and other booleans) | boolean | `is_active`; list filter `?active=` → `?is_active=`; write key `is_active` |
| Choice columns (e.g. `value_type`) | plain string | `{value, label}` (written as the plain value) |
| Lab project `starts_on` / `ends_on` | date | `start_date` / `end_date` (read and write) |

### Downtime

| Field | Before | After |
| --- | --- | --- |
| `resource` | `{type, id}` | `{id, name, type}` |
| `state` | plain string | `{value, label}` |

### Licenses

| Field | Before | After |
| --- | --- | --- |
| `expiry_date` (a date-time) | `expiry_date` | `expires_at` |
| Agreement `valid_from` / `valid_until` | read and write | `start_date` / `end_date` |
| Agreement `billing_period` | plain string | `{value, label}` (written as the plain value) |

### Locations

| Field | Before | After |
| --- | --- | --- |
| Room slot `room`, station slot `station` | bare integer | `{id, name}` |
| Slot `occupied` | boolean | `is_occupied` |
| Room slot `slot_type` | plain string | `{value, label}` |
| City `country`, building `city` | nested object with `code` / `country` | `{id, name}` |
