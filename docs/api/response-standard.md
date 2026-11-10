# REST API Response Standard

> **Implementation status:** The redesign is in progress. This document describes the target contract; it does not imply that every active endpoint has been audited or migrated. Existing endpoints that differ are drift to fix, not patterns to copy.

## 0. Scope and conventions (GEN)
- GEN-1 This standard applies to every HTTP/JSON API the project serves: browser, mobile, server-to-server and partner clients, including file transfer, streaming and webhooks.
- GEN-2 MUST, MUST NOT, SHOULD and MAY follow RFC 2119. An unmarked imperative rule is a MUST.
- GEN-3 Strict writer, tolerant reader: servers reject unknown request fields; clients ignore unknown response fields.
- GEN-4 Concrete shapes live in [response-golden-examples.md](response-golden-examples.md). Everything a client sends (headers, parameters, bodies, uploads, limits) is governed by [request-standard.md](request-standard.md) and [request-golden-examples.md](request-golden-examples.md). Where both documents mention the same behavior they agree. Per-resource field lists live in the OpenAPI schema, not here.
- GEN-5 If this standard and an HTTP RFC conflict, the RFC wins and the deviation is reported.
- GEN-6 Where this standard relies on IETF drafts (`Idempotency-Key`, rate-limit headers), the behavior documented here is the project contract. It is updated deliberately if the drafts change.

## 1. Transport and URLs (TRN)
- TRN-1 HTTPS only, with HSTS. No credentials or tokens ever travel over plain HTTP.
- TRN-2 Bodies are UTF-8 `application/json` unless a section defines another type. Unsupported request `Content-Type` → `415`. Unsatisfiable `Accept` → `406`.
- TRN-3 JSON is strict RFC 8259: no comments, trailing commas, duplicate keys, `NaN` or `Infinity`.
- TRN-4 Collection paths are lowercase, hyphenated, plural nouns. Identifiers go in the path. Nesting is at most one level (`/orders/{id}/items`). Resource and action paths MUST NOT end with a trailing slash. The slashless form is canonical project-wide; do not redirect or serve a slash-terminated alias.
- TRN-5 Query parameter names are `snake_case`.
- TRN-6 Verbs do not appear in resource paths. Non-CRUD operations are actions (section 10).
- TRN-7 Limits are enforced and documented: body size (`413`), URL length (`414`), request timeout, JSON nesting depth, array length.
- TRN-8 Responses support compression via `Accept-Encoding`.
- TRN-9 `HEAD` works wherever `GET` does. `OPTIONS` answers CORS preflight and reports `Allow`.

## 2. HTTP semantics (HTTP)
- HTTP-1 Methods:

| Method | Purpose | Safe | Idempotent | Success |
|---|---|---|---|---|
| GET | Read | yes | yes | `200`, `304` when conditional |
| HEAD | Read headers | yes | yes | `200` |
| POST | Create, action, start a job | no | only with `Idempotency-Key` | `201` create, `200` action result, `202` accepted |
| PUT | Replace | no | yes | `200` |
| PATCH | Partial update | no | SHOULD be | `200` |
| DELETE | Remove | no | yes | `204` |
| OPTIONS | Preflight, capabilities | yes | yes | `204` |

- HTTP-2 `GET` and `HEAD` MUST be side-effect free.
- HTTP-3 Status classes are honest: 2xx success, 3xx redirect or `304` only, 4xx caller fault, 5xx server fault. Never `200` with a failure body.
- HTTP-4 `201`, `202` and `303` responses carry `Location`. `405` carries `Allow`.
- HTTP-5 Repeating `DELETE` on an already-removed resource returns `404`.

## 3. Envelope (ENV)
- ENV-1 Every JSON response body is an object. Never a bare array or scalar.
- ENV-2 Success: `{"data": <object|array>, "meta": {...}}`. `meta` is optional on single resources.
- ENV-3 Error: `{"error": {...}}`. `data` and `error` MUST NOT appear together. No other top-level keys exist.
- ENV-4 Empty collection is `200` with `"data": []`. Missing single resource is `404`.
- ENV-5 Successful deletes return `204` with no body.
- ENV-6 Every documented `meta` key has a fixed meaning (`pagination`, `restricted_fields`). Ad-hoc keys are not added.
- ENV-7 Binary, streaming and redirect responses are not wrapped in the envelope (sections 15 and 16).

## 4. Errors (ERR)
- ERR-1 The HTTP status line carries the status. It is not duplicated in the body.
```json
{"error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [{"field": "email", "code": "invalid_format", "message": "Enter a valid email."}],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f90"
}}
```
- ERR-2 `code` (top level and in `details`) is machine-stable snake_case and never changes once released. `message` is human text, localizable, and may change. `details` is always present, `[]` when empty.
- ERR-3 The HTTP status is authoritative:

| Status | Use |
|---|---|
| 400 | Malformed request; unknown or invalid query parameter, filter, ordering or page size |
| 401 | Missing or invalid credentials (with `WWW-Authenticate`) |
| 403 | Authenticated but not allowed |
| 404 | Not found, or existence hidden (ERR-5) |
| 405 | Method not allowed (with `Allow`) |
| 406 | `Accept` cannot be satisfied |
| 408 | Request body not received in time |
| 409 | State conflict, e.g. invalid transition, duplicate, request still in progress |
| 410 | Permanently gone or expired, only where deliberately exposed |
| 411 | Body sent without a length |
| 412 | `If-Match` precondition failed |
| 413 | Body too large |
| 414 | URL too long |
| 415 | Unsupported media type |
| 422 | Semantic validation failed, including unknown or read-only fields in a write body |
| 428 | `If-Match` required but missing |
| 429 | Rate limited (with `Retry-After`) |
| 431 | Request headers too large |
| 500 | Unexpected server error |
| 502 / 504 | Upstream failure or timeout |
| 503 | Temporarily unavailable (with `Retry-After` when known) |

- ERR-4 Every error includes `request_id`: 32 lowercase hex characters, also returned as `X-Request-ID` on every response (OBS-1).
- ERR-5 Errors MUST NOT leak stack traces, SQL, file paths, internal hostnames or library names. When existence is sensitive, return `404`, not `403`.
- ERR-6 `details[].field` uses dotted paths for nested input (`shipping_address.postal_code`) and `[n]` for array items (`items[2].quantity`).
- ERR-7 Validation reports all failures it can find in one response, not only the first.
- ERR-8 Every failure path uses this envelope: unknown routes, framework errors, auth failures, gateway and proxy errors.
- ERR-9 `5xx` messages are generic. Detail goes to logs, correlated by `request_id`.
- ERR-10 Error messages never echo secrets or unsanitized input.
- ERR-11 This envelope is the project's single error format. Do not mix it with other formats on the same API.

## 5. Identifiers and relations (REL)
- REL-1 Every primary resource (an entity with its own lifecycle) has an `id`. It is the identifier used in URLs and in references to that resource. It is stable, immutable and never reused. Its type (integer, or string for non-numeric keys) is fixed per resource type (FMT-5). Integers above 2^53 are strings (FMT-4). `id` is always the first key of the object.
- REL-2 A resource type MAY also define `uid`: a non-sequential UUID for external or public references (shared links, redirect services, cross-system integration). `uid` is optional per resource type, not per request. If a type defines it, it is always present (NUL-3), read-only, immutable and unique, and it is the second key after `id`. URLs keep using `id`. Collections that define `uid` accept an equality filter `?uid=`.
- REL-3 A relation is `{"id", "name"}` or `null`. If the target type defines `uid`, the relation object carries it between `id` and `name`: `{"id", "uid", "name"}`. The shape is the same everywhere a type is referenced.
- REL-4 MUST NOT split one relation into sibling fields (`owner` + `owner_name`).
- REL-5 A lookup (taxonomy or controlled vocabulary managed as data) is a relation of the form `{"id", "name"}`.
  - `id` is the stable key. Clients branch on `id` and display `name`.
  - Controlled-vocabulary ids are seeded with fixed values, identical in every environment, never renumbered and never reused. Reference catalogs created by import or by users (manufacturers, projects, cities) have database ids, are not seeded, and clients do not branch on them.
  - Lookup classes are defined in [ADR 002](../architecture/decisions/002-catalog-and-selector-api.md) section 4.
  - `name` is display text and may change or be localized.
  - Lookups do not carry `uid` or `code`.
- REL-6 Never mix bare ids and relation objects for the same relation.
- REL-7 For hierarchical lookups, lists return only the most specific level. Detail responses may include ancestors as lookup objects. A child never repeats its parents inside its own object.
- REL-8 Large related collections are sub-resources. Inline only a `*_count` and a `*_url`.
- REL-9 Small bounded to-many relations may be arrays of relation objects on read, written as `<relation>_ids` arrays with replace semantics.
- REL-10 A relation input that points to nothing returns `422` with `does_not_exist` on that field.
- REL-11 Ids may be sequential and guessable, and `uid` is not a secret either. Access control never relies on an identifier being hard to guess (SEC-2). Where existence is sensitive, return `404`.
- REL-12 Historical references (`created_by`, `updated_by`, and similar) survive deletion or anonymization of their target: the relation keeps its `id` and its `name` becomes a documented placeholder (for example `"Deleted user"`). A relation is `null` only if it was never set.

## 6. Types and formats (FMT)
- FMT-1 Datetime: ISO 8601 UTC with `Z`. Date: `YYYY-MM-DD`. Duration: ISO 8601 (`PT15M`). Precision is fixed per field and documented (whole seconds by default). A field never mixes precisions (FMT-5).
- FMT-2 Money: `{"amount": "1299.00", "currency": "EUR"}`. Amount is a decimal string, currency is ISO 4217. Never floats.
- FMT-3 Booleans are `true`/`false`. Never `0/1` or `"yes"`.
- FMT-4 Integers above 2^53 are strings. Quantities needing exact decimals are decimal strings. Measurements where floating point is acceptable are JSON numbers with documented precision.
- FMT-5 A field MUST keep one type across all responses and states.
- FMT-6 Units are explicit in the field name or object (`size_bytes`, `{"value": 5, "unit": "mm"}`).
- FMT-7 A money field's name states its role and holds the whole money object. `amount` appears only inside that object. Process names are not used as money field names.
- FMT-8 Strings are UTF-8, NFC-normalized. Length limits are documented. Over-length input returns `422`, never silent truncation. Empty string is rejected unless the field documents it.
- FMT-9 Standard codes: country ISO 3166-1 alpha-2, language BCP 47, timezone IANA name, phone E.164, currency ISO 4217.
- FMT-10 Coordinates are `{"latitude": <number>, "longitude": <number>}` in WGS 84, or GeoJSON where geometry is needed.
- FMT-11 URLs in bodies are absolute paths for same-API links and absolute URLs for external ones.

## 7. Null and empty values (NUL)
- NUL-1 Unknown or unset scalar: `null`. Never `""` or `0` as a stand-in.
- NUL-2 Collections are `[]` or `{}`, never `null`.
- NUL-3 Fields are always present. Do not omit keys to mean null. Permission-gated fields follow SEC-3.
- NUL-4 All-or-nothing groups are `null` when absent, never partially filled.
- NUL-5 `PATCH` follows JSON Merge Patch (RFC 7396): an omitted key is unchanged, `null` clears the field, objects merge recursively, arrays replace entirely.

## 8. Naming (NAM)
- NAM-1 Keys are `snake_case`, English, descriptive nouns.
- NAM-2 Booleans use `is_` / `has_` / `can_`.
- NAM-3 Timestamps end in `_at`, dates in `_date`, counts in `_count`, URLs in `_url`.
- NAM-4 One name per concept across the API (one word for descriptions, one for status).
- NAM-5 No abbreviations unless industry standard (`url`, `id`, `ip`).
- NAM-6 Write inputs for relations are `<relation>_id` (to-many: `<relation>_ids`), for entities and lookups alike.
- NAM-7 Event types are `<resource>.<past_tense_event>` (`order.confirmed`).

## 9. Enums and status (ENU)
- ENU-1 Enum fields return `{"value": "...", "label": "..."}`. `value` is stable snake_case. `label` is localizable.
- ENU-2 Filters and writes use `value`, never `label`.
- ENU-3 Clients MUST handle unknown enum values gracefully. Adding a value is non-breaking.
- ENU-4 Status-specific extra data has a documented schema per status value, not an untyped object.
- ENU-5 Use an enum when values are fixed in code and drive behavior. Use a lookup (REL-5) when values are admin-managed data.
- ENU-6 State is modeled as a status enum plus audit data, not as a set of booleans.

## 10. Resource structure and actions (STR, ACT)
- STR-1 Group related fields into one object. A group is at least two fields, or a money/quantity object.
- STR-2 Every primary resource that is created or changed through the API includes `created_at` and `updated_at`: UTC timestamps (FMT-1), read-only, always present (NUL-3). `updated_at` changes whenever a write changes stored data (a no-op write does not change it, see request standard WRT-5) and never on a read.
- STR-3 Soft-delete marker (`deleted_at`) is visible only to roles allowed to see deleted records. Soft-deleted resources otherwise behave as `404`.
- STR-4 List responses are summaries: no heavy or fast-changing data, no redundant hierarchy levels.
- STR-5 Free-form extension data goes in a single `metadata` object.
- STR-6 Related URLs are plain `*_url` fields. No `links` envelope.
- STR-7 `created_by` and `updated_by` are included when the API records actors. They are `null` for system-initiated changes (imports, scheduled jobs). Callers without permission to see them get `null` and the field names in `meta.restricted_fields` (SEC-3).
- STR-8 Exceptions to STR-2: lookups (REL-5) carry no audit fields. Immutable records (logs, events) carry `created_at` only. Async jobs follow ASY-2. Computed or read-only views carry none.
- STR-9 `updated_at` is for display and sync. It is never a concurrency token (RW-5).
- ACT-1 A non-CRUD operation on a resource is `POST /<collection>/{id}/actions/<verb>`. Collection-level: `POST /<collection>/actions/<verb>`.
- ACT-2 An action returns the full updated detail shape (`200`) or a status resource (`202`, section 13).
- ACT-3 A disallowed state transition returns `409` with `invalid_state_transition`.
- ACT-4 Non-idempotent actions support `Idempotency-Key` (RW-6).
- ACT-5 Something with its own lifecycle (an export, an upload) is modeled as a resource, not an action.

## 11. Collections (COL)
- COL-1 All lists are paginated with a documented, server-enforced maximum page size. A larger `page_size` returns `400`, never silently clamped.
- COL-2 Two pagination styles exist; each endpoint declares one, never both:
  - Page style: `page`, `page_size`. `meta.pagination` has `count`, `page`, `page_size`, `next`, `previous`.
  - Cursor style (large or fast-changing data): `cursor`, `page_size`. `meta.pagination` has `count` (`null` if not computed), `page_size`, `next_cursor`, `previous_cursor`. Cursors are opaque, and clients never build them.
- COL-3 Filtering and search use only endpoint-declared, allowlisted query parameters. Conventions: equality `status=confirmed` (and `uid=` where defined), multiple values `status=a,b`, ranges `<field>_after` / `<field>_before` (datetimes and dates) and `<field>_min` / `<field>_max` (numbers), free text `q`. Sorting (`ordering=-created_at,name`) exists only where implemented and allowlisted. Do not imply universal `ordering` or `q`.
- COL-4 Unknown filter, ordering or query keys return `400`, never silently ignored.
- COL-5 Where sorting is supported it is deterministic (unique tiebreaker such as `id`).
- COL-6 Each collection endpoint documents its accepted query parameters.
- COL-7 `?fields=` and `?expand=` exist only if implemented consistently across the API. Expansion depth is bounded.
- COL-8 `next` / `previous` are ready-to-call URLs that preserve all filters.
- COL-9 Collections that can exceed a documented size (default guidance: 10,000 rows) MUST use cursor style. Deep offset pagination is not allowed on them.

## 12. Read vs write (RW)
- RW-1 Separate read and write serializers.
- RW-2 Read nests relation objects. Write accepts relation inputs per NAM-6.
- RW-3 Unknown fields and read-only fields (`id`, `uid`, audit fields, computed values) in a write body return `422` (`unknown_field`, `read_only_field`). Read-only fields are marked `readOnly` in the schema.
- RW-4 `POST` creates (`201` + `Location`). `PUT` replaces: omitted optional writable fields reset to their default or `null`. `PATCH` applies NUL-5. `DELETE` removes. Writes return the full detail shape.
- RW-5 Concurrency: resources that can be edited concurrently return a strong `ETag`, derived from a version counter or content hash and never from `updated_at`, and require `If-Match` on `PUT`, `PATCH` and `DELETE`: missing → `428`, mismatch → `412`. Write responses return the new `ETag`.
- RW-6 Idempotency: unsafe or retried operations accept an `Idempotency-Key` request header, scoped to credential and endpoint and retained for a documented period.
  - Replay with the same key and body returns the original status and body plus `Idempotency-Replayed: true`.
  - Same key, different body → `422` (`idempotency_key_reuse`).
  - Same key while the first request is still running → `409` (`request_in_progress`).
- RW-7 Clients build write bodies from the OpenAPI schema and omit `readOnly` fields. Because RW-3 is strict, a response body is not echoed back unchanged into `PUT` or `PATCH`.

## 13. Asynchronous work (ASY)
- ASY-1 An operation that may exceed the documented synchronous time budget returns `202` with `Location` to a status resource, never a blocked request.
- ASY-2 The status resource has `id`, `status` (enum), `progress` (0 to 100 or `null`), `result_url` (`null` until succeeded), `error` (`null` unless failed; same shape as the ERR-1 error object), `created_at`, `updated_at`, `completed_at`.
- ASY-3 `status.value` is one of `queued`, `running`, `succeeded`, `failed`, `canceled`. The last three are terminal.
- ASY-4 While work is not terminal, polling responses carry `Retry-After`.
- ASY-5 Cancellation is the action `POST .../actions/cancel`. Canceling a terminal job is `409`.
- ASY-6 Results are retained for a documented period, then `410`.
- ASY-7 Failures inside a job are reported on the status resource, not as an HTTP error on the poll.

## 14. Bulk operations (BLK)
- BLK-1 Bulk writes use a dedicated endpoint (`POST /<collection>/bulk`) with an `{"operations": [...]}` body and a documented maximum size. Never an array body (ENV-1).
- BLK-2 Atomic by default: all operations succeed or none are applied, and a failure is a normal error with `details[].field` paths like `operations[1].data.name`. Partial mode must be requested explicitly (`"mode": "partial"`) and returns `200` with per-item results in `data`.
- BLK-3 Bulk endpoints support `Idempotency-Key` (RW-6).

## 15. Files and binary content (FIL)
- FIL-1 A file is a resource with metadata: `id` (and optional `uid`), `name`, `content_type`, `size_bytes`, `checksum` (`{"algorithm", "value"}`), `status` (enum), `download_url`, audit fields. JSON never inlines file bytes or base64 blobs.
- FIL-2 Small uploads use `multipart/form-data` to the resource endpoint. Large uploads are two-step: create an upload record (returns a short-lived `upload` object with `url`, `method`, `headers`, `expires_at`), the client sends the bytes, then calls the `complete` action. The server verifies size, checksum and sniffed content type before the file becomes `ready`.
- FIL-3 Maximum size and allowed content types are documented and enforced (`413`, `415`, or `422` with `invalid_file`).
- FIL-4 Downloads go through a permission-checked endpoint that either streams or returns `302` to a short-lived signed URL. Download responses are not wrapped in the envelope.
- FIL-5 Download responses set `Content-Type` from validated metadata, `Content-Disposition` with a sanitized filename (RFC 6266 / 5987), `X-Content-Type-Options: nosniff`, and support `Range` (`206`, `Accept-Ranges: bytes`) and `ETag`.
- FIL-6 User-supplied active content (HTML, SVG, scripts) is served as an attachment or from a separate sandbox origin, never inline from the API origin.
- FIL-7 A client-supplied filename is metadata only and is never used as a storage path.

## 16. Streaming and realtime (STM)
- STM-1 Server-Sent Events use `text/event-stream`. Each event has `id`, `event` and a JSON `data` line using the event envelope of EVT-1. A comment line is sent as heartbeat. Clients resume with `Last-Event-ID`. Responses carry `Cache-Control: no-cache`.
- STM-2 Large exports stream as `application/x-ndjson`, one JSON object per line. An error after the status line is sent ends the stream with a final line `{"error": {...}}`.
- STM-3 WebSocket messages are JSON objects `{"type", "data"}`. Authentication happens at the handshake or the first message with a short-lived token. Long-lived credentials never go in the URL. `Origin` is checked.
- STM-4 Streaming endpoints document reconnection, ordering and heartbeat intervals.

## 17. Webhooks and events (EVT)
- EVT-1 An event is `{"id", "type", "created_at", "data"}`. `id` is a unique string. `data` is the documented resource shape or, for sensitive resources, a thin payload with only `id` and a `*_url`.
- EVT-2 Delivery is at-least-once and unordered. Receivers dedupe by event `id` and order by timestamps in the data.
- EVT-3 Deliveries are signed: headers `Webhook-Id`, `Webhook-Timestamp`, `Webhook-Signature` (HMAC-SHA256 over `id.timestamp.body`). Receivers reject timestamps outside a documented tolerance. Two secrets may be active during rotation.
- EVT-4 Receivers answer `2xx` within the documented timeout. Failures retry with exponential backoff and jitter, then the endpoint is disabled with a notification.
- EVT-5 Target URLs are validated at registration and at delivery: HTTPS only, no private, loopback or link-local addresses (SSRF).
- EVT-6 Deliveries are listable and replayable through the API.
- EVT-7 New event types are non-breaking. Receivers ignore unknown types.

## 18. Caching and conditional requests (CCH)
- CCH-1 Every response states caching intent. Authenticated JSON: `Cache-Control: private, no-cache`. Sensitive data and all error responses: `no-store`. Public reference data: `public, max-age=<n>`.
- CCH-2 Detail `GET` returns a strong `ETag`. `If-None-Match` matching returns `304` with no body. Lists may return `ETag`.
- CCH-3 `Last-Modified` and `If-Modified-Since` are optional additions.
- CCH-4 `Vary` lists every request header that changes the representation (`Accept`, `Accept-Language`, `Accept-Encoding`, `Origin` when CORS varies).
- CCH-5 `POST` responses are not cacheable.

## 19. Security (SEC)
- SEC-1 Every endpoint authenticates, except explicitly public ones (health, public docs). Credentials travel in `Authorization` (Bearer) or, for first-party browsers, a secure cookie. Never in the URL. Tokens are short-lived. `401` carries `WWW-Authenticate`.
- SEC-2 Authorization is deny-by-default and checked per object and per sensitive field. Every identifier in a path or body is authorized against the caller (no IDOR), because ids are guessable (REL-11).
- SEC-3 Permission-gated fields stay present (NUL-3) as `null` for callers without permission, and `meta.restricted_fields` lists their names. `null` for an authorized caller therefore always means unset. Fields that must not be disclosed as existing are removed from that API surface's schema.
- SEC-4 Never return secrets, tokens, password hashes or internal paths. A generated secret is shown once, at creation.
- SEC-5 Validate every input against a schema: type, length, range, enum, array size, nesting depth. Use parameterized queries. Never evaluate user input as code or templates.
- SEC-6 Mass assignment protection: only whitelisted fields are writable (RW-3).
- SEC-7 CORS uses an explicit origin allowlist, never `*` with credentials, and minimal allowed methods and headers. Preflight responses set `Access-Control-Max-Age`. `Access-Control-Expose-Headers` lists the headers clients need (`ETag`, `Location`, `Retry-After`, `X-Request-ID`, rate-limit headers).
- SEC-8 Cookie authentication uses `Secure; HttpOnly; SameSite`. State-changing requests require CSRF protection (token or custom header, plus `Origin` check). Header-based Bearer auth does not.
- SEC-9 API responses set `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` and `Referrer-Policy: no-referrer`.
- SEC-10 Rate limit every endpoint per credential and per IP, stricter for authentication and expensive endpoints. `429` carries `Retry-After`. One documented set of rate-limit headers appears on every response.
- SEC-11 Authentication failures are uniform (no user enumeration), with backoff or lockout.
- SEC-12 Server-side fetches of client-supplied URLs go through an allowlist and resolved-address checks (SSRF).
- SEC-13 Minimize personal data. Logs redact credentials and personal data. Request bodies are not logged by default.
- SEC-14 Security-relevant actions are audit-logged with actor, target and `request_id`.
- SEC-15 Multi-tenant scope comes from credentials or the route, never from a client-writable body field. Cross-tenant access returns `404`.
- SEC-16 The scopes or roles each endpoint requires are documented. A valid credential that lacks one returns `403` (`insufficient_scope`) with `WWW-Authenticate: Bearer error="insufficient_scope"`.

## 20. Localization (I18N)
- I18N-1 `Accept-Language` selects localizable text: `label`, lookup `name`, and error `message`. Responses carry `Content-Language`. The default language is the fallback. Codes and `value`s are never localized.
- I18N-2 Instants are UTC (FMT-1). When wall-clock meaning matters, send a local datetime without offset plus an IANA `timezone` field.
- I18N-3 Number, currency and date display formatting is the client's job. The API sends machine formats only.
- I18N-4 Sorting and collation rules are documented per endpoint.

## 21. Observability and operations (OBS)
- OBS-1 A valid client `X-Request-ID` is honored, otherwise one is generated. It appears on every response and every log line.
- OBS-2 W3C `traceparent` is accepted and propagated.
- OBS-3 Logs are structured and include `request_id`, actor, route, status and latency.
- OBS-4 `/health/live` and `/health/ready` return `200` or `503`, need no authentication, and expose no internal detail.
- OBS-5 Metrics and diagnostics endpoints are internal-only.

## 22. Versioning and compatibility (VER)
- VER-1 Redesigned in place at `/api/`, with no parallel versioned route prefixes. Breaking changes are allowed as part of the explicitly approved redesign. After release, breaking changes require owner approval and a documented migration/deprecation plan.
- VER-2 Non-breaking: new optional response field, new endpoint, new enum value, new optional query parameter, looser validation. Breaking: removing or renaming a field, changing a type, format or meaning, tighter validation, changed defaults, status codes or error codes.
- VER-3 Deprecated fields and endpoints remain for at least one release, marked `deprecated: true` in OpenAPI, with `Deprecation` and `Sunset` headers and a `Link` to the migration guide.
- VER-4 Clients MUST ignore unknown response fields (GEN-3).

## 23. Performance (PRF)
- PRF-1 Nested output requires `select_related` / `prefetch_related` (or equivalent). No N+1.
- PRF-2 Query counts are asserted in tests for list and detail endpoints.
- PRF-3 No endpoint has an unbounded response: pages, expansions and bulk sizes are capped.
- PRF-4 Work above the synchronous time budget becomes asynchronous (ASY-1).
- PRF-5 Expensive aggregates (`count`) may be `null` rather than computed (COL-2).

## 24. Documentation and testing (DOC)
- DOC-1 The OpenAPI schema is the contract. It is updated in the same change as the code.
- DOC-2 Every endpoint documents request, response, error cases, auth, permission-gated fields, limits and an example.
- DOC-3 Examples in docs are valid against the schema (validated in CI).
- DOC-4 Contract tests check responses against the schema for every endpoint, including error responses.
- DOC-5 Breaking-change classification (VER-2) is checked in CI by comparing schema versions.

## 25. Agent review procedure
1. Identify which sections apply to the endpoint: plain CRUD, collection, action, async, bulk, file, stream or webhook.
2. Check the design against every applicable section.
3. Output a table: `Rule ID | Status (pass/violation) | Fix`.
4. List breaking changes and the version plan.
5. Confirm the OpenAPI schema was updated.

## 26. Selector and options endpoints (OPT)
- OPT-1 `GET /api/<root>/<resource>/options` (canonical, no trailing slash, TRN-4) is reserved for selector data only. Lists, detail views and actions MUST NOT use it. It is a sibling of the `<resource>` collection. Inverse forms (`/options/<resource>`) and alternative names (`select-list`) MUST NOT be used. Route naming and the route ledger: [ADR 002](../architecture/decisions/002-catalog-and-selector-api.md).
- OPT-2 The response is `{"data": [{"id": ..., "sku": ..., "name": ...}]}`. Each item has exactly these three keys, and the set is fixed for every options endpoint (ENV-2). An empty match returns `"data": []` (ENV-4).
- OPT-3 `id` is the value submitted in writes and relation fields (REL-1). `name` is the display text (I18N-1). `sku` is the secondary identifier, shown as a badge or used for search. `sku` is a string or `null`, the same type on every options endpoint (FMT-5). It is stable: never derived from mutable display text, rank or position, and never a copy of `id`. Clients never submit or branch on `sku`.
- OPT-4 Items MUST NOT carry any key beyond `id`, `sku` and `name`. `uid`, status, audit fields, relations and metadata belong on the list or detail endpoint. Any change to the key set is a schema change reviewed under VER-2.
- OPT-5 The endpoint accepts only the allowlisted query parameters of the list endpoint, validated by the same FilterSet / query serializer. Unknown parameters return `400` (COL-4). Availability flags such as `assignable=true` MUST be documented in the schema.
- OPT-6 The endpoint is not paginated (COL-2 does not apply). It returns the full matching set up to a documented hard cap, for example 1000. Over the cap it returns `400` with `too_many_results`; it never silently truncates.
- OPT-7 Ordering is fixed to `order_by("name", "id")`. Clients cannot change it, and the endpoint has no `ordering` parameter.
- OPT-8 The query selects only `id`, `sku` and `name` (`.only("id", "sku", "name")`), uses `Exists(...)` / `~Exists(...)` for relation filters to avoid joins and duplicate rows, and its query count is asserted in tests (PRF-2).
- OPT-9 Search is `q` only (QRY-7), case-insensitive, matching `name` and `sku`. `search` and other aliases are not accepted. Each filter has exactly one name, `<relation>_id` for relations (NAM-6).
- OPT-10 `include_ids` (comma-separated positive integers, unique, at most 50) adds the listed rows regardless of active state, `q` or filters, when the caller may read them. Unreadable or missing ids are omitted silently (REL-11). These rows count toward the cap and follow OPT-7 ordering. Writes still reject retired ids.
- OPT-11 Each options endpoint declares a size class. Small: returns all active rows. Large: requires `q` or a declared parent filter; without one it returns `400` `invalid_query`. The cap is one project constant, lowered per resource only. Moving an endpoint from small to large is breaking (VER-2).
- OPT-12 Enums (ENU-5) have no options endpoint. Their values are published as `{value, label}` in the schema or in filter metadata, never with synthetic integer ids.
- OPT-13 Options responses return a strong `ETag`, honor `If-None-Match` with `304` (CCH-2), use `Cache-Control: private, no-cache` and `Vary: Accept-Language`.
