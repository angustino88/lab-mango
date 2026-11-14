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

### Benches

| Field | Before | After |
| --- | --- | --- |
| Setup assignment `equipment` | `{id, uid, sku, name, kind}` | `{id, uid, name}`; the kind moves to the row as `equipment_kind: {id, name}` |
| Reference-data `types`, `groups`, `stations`; station reference-data `types`, `rooms` | unchanged keys | unchanged; marked `x-embedded-resource` in the schema |

### Expenses and financial report

| Field | Before | After |
| --- | --- | --- |
| Expense `expense_type`, `billing_period`; payment `transaction_type` | plain string | `{value, label}` on read; written as the plain value |
| Expense `valid_from` / `valid_until` | read and write | `start_date` / `end_date` |
| Payment `paid_at` (a date) | read and write | `paid_date` |
| Report `room_id` + `room_name` (items and `by_room`) | two keys | `room: {id, name}` |
| Report `expense_type`, `billing_period`, `payment_status`, `status` | plain string | `{value, label}` |
| Report item `valid_from` / `valid_until` | dates | `start_date` / `end_date` |

### Bench bookings: lab projects

| Field | Before | After |
| --- | --- | --- |
| `active`, `starts_on`, `ends_on` | | `is_active`, `start_date`, `end_date`; list filter `?active=` → `?is_active=` |

### Procurement

| Field | Before | After |
| --- | --- | --- |
| Purchase `status`; transaction `transaction_type`; allocation `resource_kind` | plain string | `{value, label}` on read; written as the plain value |
| Purchase detail `created` / `modified` | | `created_at` / `updated_at` |

### Monitoring events

| Before | After |
| --- | --- |
| `computer_id`, `computer_name` | `computer: {id, name}` |
| `bench: {id, sku, bench_name}` | `bench: {id, name}` |
| `agent_id`, `event_id` | `agent_key`, `event_key` |
| `action` (string) | `{value, label}` |
| `subject_type`, `subject_id`, `subject_name` | `subject: {type, key, name}` |
| `remote_user_displayname` | `remote_user_display_name` |
| Duplicates `source`, `event_type`, `category`, `object_name`, `object_id`, `details`, `details_str`, `created`, `modified` | removed; use `agent_key`, `action`, `subject`, `payload`, `occurred_at`, `reported_at` |

The write body is unchanged, including its legacy aliases.

### Resource audit

| Field | Before | After |
| --- | --- | --- |
| Audit `resource_type`, `resource_id`, `resource_name`, `resource_sku` | four keys | `resource: {id, name, type}` |
| Audit `auditor` | `{id, username, display_name}` | `{id, name}` |
| Audit `result` | plain string | `{value, label}` (written as the plain value) |
| Catalog item `resource_type` | plain string | `{value, label}` |
| Catalog item `expiry_date`, `deleted` | | `expires_at`, `is_deleted` |
| Catalog `meta.server_time` | | `meta.sync_started_at` |

### Leaderboard

`last_remote` → `last_remote_at`.

### Notifications

| Field | Before | After |
| --- | --- | --- |
| `message_type` | plain string | `{value, label}` on read; written as the plain value |
| `expiry_date` | read and write | `expires_at` |
| `target_user` | integer | `{id, name}` or `null` |
| `created` / `modified` | | `created_at` / `updated_at` |

### Equipment

| Field | Before | After |
| --- | --- | --- |
| `warranty_until` (date) | read and write | `warranty_end_date` |
| `calibration_required` | read and write | `is_calibration_required` |
| `calibration_overdue` | | `is_calibration_overdue` |
| Loan `batch_id`, `booking_id` | integers | `batch: {id, name}`, `booking: {id, name}` (name = booking code) |
| Loan `overdue` | | `is_overdue` |
| Reservation `batch_id` | integer | `batch: {id, name}` |
| Placement `target_type` | plain string | `{value, label}` |
| Category `capabilities` | array of strings | array of `{value, label}` |
| Kind `category`, type `kind`, product model `manufacturer` | integer | `{id, name}` |
| Product model specification `definition_id`, `name` | two keys | `definition: {id, name}`; `value_type` is `{value, label}` |
| Reference-data `owners` | `{id, username}` | `{id, name}` |
| Department / group catalog `active` | | `is_active`; group `department` is `{id, name}` |
| Computing activity `status`, `modified` | | `status` is `{value, label}`; `updated_at` |

### Resource mappings

| Before | After |
| --- | --- |
| Room slot `room_id`; station `room_id`, `slot_id`; station slot `station_id` | `room`, `slot`, `station` as `{id, name}` |
| Bench `setup_location_id`, `station_slot_id` | `setup_location`, `station_slot` as `{id, name}` |
| Equipment `bench_id`; assignment `monitor` | `bench: {id, name}`; `is_monitored` |
| License assignment `equipment_id`, `license_id` | `equipment`, `license` as `{id, name}` |

### Dashboard

| Before | After |
| --- | --- |
| `bench_group: {id, name, description}` | `{id, name}` |
| `location: {station_id, station_name, room_id, room_name, building_name, slot_label}` | `location: {station, room, building, slot_label}` with `{id, name}` relations |
| Booking `user: {id, username, display_name}` | `{id, name}` |

### Analytics

| Before | After |
| --- | --- |
| `period_start` / `period_end` (summary, booked-vs-used, equipment availability, finance) | `period: {starts_at, ends_at}` |
| Booked-vs-used `bench_id` + `bench_name` | `bench: {id, name}` |
| Equipment availability `equipment_id` + `equipment_name` | `equipment: {id, name}` |
| Finance breakdown `source` | `{value, label}` |

### Agent API (`/agent/*`, `/api/agents`)

| Before | After |
| --- | --- |
| Agent `equipment` (integer), `equipment_sku`, `equipment_name` | `equipment: {id, name}` |
| Agent `state`, `key_algorithm`, `key_storage`; activity `status`; session log `access_type` | `{value, label}` |
| Agent `created` / `modified` | `created_at` / `updated_at` |
| Info `backend_id` | `backend_key` |
| Session log `event_id`, `login_time`, `logout_time` (request and response) | `event_key`, `login_at`, `logout_at` |
| `eligible`, `checked_in`, `completed`, `extended` | `is_eligible`, `is_checked_in`, `is_completed`, `is_extended` |
| Extension refusal `details[].limit` | `details[].limit_at` |

The stub agent (`tools/stub_agent.py`) reads `backend_key`.

### Routing sync

No change: its payloads follow `docs/agent-platform/routing-sync.md` (response standard GEN-7) and carry
`x-protocol-spec` in the schema.

### Licenses

License product `vendor`: `{id, name, created_at, updated_at}` → `{id, name}`.

### Leaderboard (wire fix)

Persona, lab and export rows were sent unserialized, so `last_remote` was still on the wire. They are now
serialized: the key is `last_remote_at`, as documented.
