# REST API Request Standard

> **Implementation status:** The redesign is in progress. This document describes the target contract; it does not imply that every active endpoint has been audited or migrated. Existing endpoints that differ are drift to fix, not patterns to copy.

This standard covers everything a client sends: methods, headers, path and query parameters, bodies, uploads, authentication and limits. It pairs with [response-standard.md](response-standard.md) (what the server returns) and [request-response-golden-examples.md](request-golden-examples.md) (concrete requests). Per-endpoint field lists live in the OpenAPI schema, not here.

## 0. Scope and basis (SCP)
- SCP-1 Applies to every HTTP/JSON API request, including file upload, bulk, action and search requests. Streaming and webhook payloads are covered by the response standard.
- SCP-2 MUST, MUST NOT, SHOULD and MAY follow RFC 2119. An unmarked imperative rule is a MUST.
- SCP-3 Strict reader on requests: the server validates everything and rejects what it does not understand. This mirrors the response standard, where clients are tolerant readers.
- SCP-4 Where the two standards mention the same behavior they agree. If they ever differ, the stricter rule applies and the conflict is reported.
- SCP-5 If this standard and an HTTP RFC conflict, the RFC wins and the deviation is reported.
- SCP-6 Real-world basis. This standard follows these specifications; where it adds a rule it says so.

| Area | Specification |
|---|---|
| HTTP semantics, methods, preconditions, status codes | RFC 9110 |
| JSON syntax | RFC 8259 |
| Partial update | RFC 7396 (JSON Merge Patch) |
| Date and time | RFC 3339 (profile of ISO 8601) |
| Multipart bodies | RFC 7578 |
| Filenames in headers | RFC 6266, RFC 8187 |
| Bearer tokens | RFC 6750 |
| Additional status codes (428, 429, 431) | RFC 6585 |
| Body digests | RFC 9530 (`Content-Digest`) |
| UUIDs | RFC 9562 |
| Language tags | BCP 47 (RFC 5646) |
| Trace propagation | W3C Trace Context |
| Idempotent retries | IETF draft `Idempotency-Key` header |
| Security | OWASP API Security Top 10 (2023) |
| Contract and validation | OpenAPI 3.1, JSON Schema 2020-12 |
| Unicode, codes | UAX #15 (NFC), ISO 4217, ISO 3166-1, ITU E.164 |

## 1. Methods and bodies (MTH)
- MTH-1 `GET`, `HEAD` and `DELETE` carry no body. A request that sends one returns `400` (`unexpected_body`). A `DELETE` takes its target and preconditions from the path and headers only.
- MTH-2 `POST`, `PUT` and `PATCH` carry a JSON object body, unless the endpoint documents otherwise (multipart upload, action with no parameters).
- MTH-3 An action with no parameters accepts an empty body (`Content-Length: 0`) or `{}`. Any other body is validated against the action's schema.
- MTH-4 A body that is required but empty returns `400` (`malformed_request`).
- MTH-5 `OPTIONS` carries no body and is answered without authentication for CORS preflight (response standard SEC-7).
- MTH-6 A method the route does not support returns `405` with `Allow`. Method override headers (`X-HTTP-Method-Override`) are not supported.
- MTH-7 `POST` is used for create, action and job start. It is never used to tunnel reads or deletes. The only read over `POST` is a documented search endpoint (SRC).

## 2. Headers (HDR)
- HDR-1 Request headers the API accepts and their rules:

| Header | Rule |
|---|---|
| `Authorization` | `Bearer <token>`, exactly one. See AUT. |
| `Content-Type` | Required when a body is sent. `application/json` (charset UTF-8 only), `application/merge-patch+json` on `PATCH`, `multipart/form-data` on documented upload endpoints. Anything else → `415`. |
| `Content-Length` / `Transfer-Encoding` | Body length is honored and enforced. A mismatch → `400`. Chunked bodies are limited as they stream (LIM-2). |
| `Content-Encoding` | Only where documented (`gzip`). Unsupported → `415`. Limits apply to the decompressed size (LIM-6). |
| `Accept` | `application/json` or `*/*`. Unsatisfiable → `406`. Absent means `application/json`. |
| `Accept-Language` | BCP 47 list. Selects localized text (response standard I18N-1). Invalid values are ignored and the default language applies. |
| `Idempotency-Key` | See WRT-8. |
| `If-Match` / `If-None-Match` | See WRT-9. |
| `X-Request-ID` | 32 lowercase hex characters. A valid value is honored, anything else is replaced and never rejected (TRC-1). |
| `traceparent` / `tracestate` | W3C Trace Context. Propagated, never validated for business logic. |
| `Origin` | Checked against the CORS allowlist and, for cookie auth, the CSRF rules (SAF-8). |
| `Range` | Only on download endpoints. |

- HDR-2 Header names are case-insensitive. Values are not trimmed beyond RFC 9110 rules.
- HDR-3 A singleton header (`Authorization`, `Content-Type`, `Content-Length`, `Idempotency-Key`) sent more than once returns `400`.
- HDR-4 Unknown headers are ignored. Nothing in a custom header changes behavior unless this standard or the OpenAPI schema documents it.
- HDR-5 Business data never travels in headers. Headers carry credentials, negotiation, preconditions, idempotency and tracing only.
- HDR-6 Total header size above the documented limit returns `431`.
- HDR-7 `Expect: 100-continue` is honored so that clients can have a large body refused (`401`, `403`, `413`, `415`) before sending it.

## 3. Path parameters (PTH)
- PTH-1 A path identifier is the resource's `id` (response standard REL-1). Integer ids are positive decimal integers: no sign, no leading zeros, no whitespace, within the documented range.
- PTH-2 A path identifier that is malformed, out of range, or points to nothing the caller may see returns `404`, never `400`. This avoids leaking which ids exist (response standard REL-11).
- PTH-3 String ids and `uid` values are matched case-sensitively, except UUIDs, which are accepted in any case and canonicalized to lowercase.
- PTH-4 Path segments are percent-decoded once. Encoded slashes, `..`, null bytes and backslashes are rejected with `404`.
- PTH-5 All API paths, including collections, resources and actions, MUST NOT end with a trailing slash. The slashless path is canonical; a trailing-slash alias MUST NOT be added or redirected.
- PTH-6 Identifiers appear in the path or in a documented `<relation>_id` body field, never in custom headers.
- PTH-7 Nesting is at most one level. A child id under the wrong parent (`/orders/184/items/9/` where item 9 belongs to order 7) returns `404`.

## 4. Query parameters (QRY)
- QRY-1 Query parameters are allowlisted per endpoint. An unknown parameter returns `400` (`invalid_query`), including on write endpoints.
- QRY-2 Names are `snake_case`. A singleton parameter sent twice returns `400`. Multi-value parameters use comma-separated values (`status=a,b`), not repeated keys.
- QRY-3 Types follow the same strictness as bodies (TYP): booleans are `true` / `false`, numbers are plain decimal, datetimes carry `Z` or an offset, enums use `value`.
- QRY-4 An empty value (`?status=`) is invalid and returns `400`. Absence means "no filter".
- QRY-5 Filter naming: equality `<field>=`, ranges `<field>_after` / `<field>_before` (dates and datetimes, inclusive start, exclusive end) and `<field>_min` / `<field>_max` (numbers, inclusive). `uid=` is an equality filter where the type defines `uid`.
- QRY-6 `ordering` is a comma-separated list of allowlisted fields, each optionally prefixed with `-` for descending. Unknown fields → `400`.
- QRY-7 `q` has a documented minimum and maximum length (default guidance: 1 to 200). It is a search term and is never interpreted as a query language, regex or field expression.
- QRY-8 `page_size` above the maximum, `page` below 1 and malformed `cursor` values return `400`. Cursors are opaque and are never built by clients. An expired or tampered cursor returns `400` (`invalid_cursor`).
- QRY-9 `fields` and `expand` exist only if implemented consistently. Unknown names return `400`.
- QRY-10 Credentials, tokens and personal data never appear in the query string, because URLs end up in logs, browser history and referrers.
- QRY-11 Parameters are percent-decoded once, and values are validated after decoding. Total URL length above the documented limit returns `414`.
- QRY-12 Query errors use `details[].field` with the parameter name (`ordering`, `page_size`).

## 5. Body format (BDY)
- BDY-1 The body is the resource object itself. There is no `data` wrapper, no `meta` and no envelope on requests.
- BDY-2 The top level is a JSON object. A bare array, scalar or `null` returns `400`.
- BDY-3 JSON is strict RFC 8259 in UTF-8: no comments, trailing commas, `NaN`, `Infinity`, single quotes or unquoted keys. Invalid syntax returns `400` (`malformed_request`).
- BDY-4 Duplicate keys at any level return `400`. A UTF-8 byte order mark returns `400`. Invalid UTF-8 and lone surrogates return `400`.
- BDY-5 Structural limits are enforced while parsing: maximum size, nesting depth, keys per object, array length and string length (LIM-1). Exceeding a structural limit returns `400` (depth, keys) or `413` (size).
- BDY-6 Keys are `snake_case`, case-sensitive, and match the schema exactly. Unknown keys return `422` (`unknown_field`), never ignored (response standard RW-3).
- BDY-7 Values for read-only and server-managed fields (`id`, `uid`, audit fields, computed fields, `status` where it changes only through actions) return `422` (`read_only_field`), even when they equal the current value.
- BDY-8 A response body is not a valid request body. Clients build requests from writable fields (response standard RW-7).
- BDY-9 Write-only fields (passwords, secrets) are accepted in requests and never returned. They are marked `writeOnly` in the schema.
- BDY-10 Object nesting mirrors the response structure for groups (`shipping_address`, `discount`) and uses flat `<relation>_id` fields for relations (response standard NAM-6).

## 6. Types and formats (TYP)
- TYP-1 Types are strict. The server never coerces: `"17"` for an integer, `1` for a boolean, `17` for a string, or `"true"` for a boolean returns `422` (`invalid_type`).
- TYP-2 Integers are plain integer literals within the documented range (default: signed 53-bit safe range). A fraction or exponent (`1.0`, `1e3`) is not an integer and is invalid. Integers above 2^53 are sent as strings (response standard FMT-4).
- TYP-3 Decimals and money amounts are strings, matched by `^-?[0-9]+(\.[0-9]+)?$`: no exponent, no leading `+`, no thousands separators, no whitespace. The number of decimal places may not exceed the currency's minor units or the field's documented scale, otherwise `422` (`invalid_precision`). Negative values only where documented (`min_value` otherwise).
- TYP-4 Money is `{"amount": "<decimal string>", "currency": "<ISO 4217 uppercase>"}`, the same object that is read. Unknown currencies return `422` (`invalid_choice`).
- TYP-5 Booleans are `true` or `false`.
- TYP-6 Enums are sent as the plain `value` string, case-sensitive snake_case (`"status": "confirmed"`), never as the `{value, label}` object and never as the `label`. Unknown values return `422` (`invalid_choice`).
- TYP-7 Datetimes are RFC 3339: `YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)`. A datetime without `Z` or an offset returns `422` (`invalid_format`). Years are 0001 to 9999. Leap seconds (`:60`) are rejected. The server converts to UTC, stores and returns `Z` (response standard FMT-1). Fractional precision above the field's documented precision is rejected, not truncated.
- TYP-8 Dates are `YYYY-MM-DD` and must be real calendar dates. Durations are ISO 8601 (`PT15M`). Wall-clock times that must stay local are a local datetime without offset plus an IANA `timezone` field (response standard I18N-2).
- TYP-9 Strings are UTF-8 and are normalized to NFC. Control characters other than `\n` and `\t` (and `\n` only in single-line fields) are rejected. A string made only of whitespace is empty. An empty string is rejected unless the field documents it (response standard FMT-8). Whitespace is trimmed only on fields documented as trimmed, and over-length input is rejected, never truncated.
- TYP-10 Relations are written as `<relation>_id` (integer, or the target's documented id type) and to-many relations as `<relation>_ids`. A bare id or null is accepted only where the field is documented nullable. The object form `{id, name}` is not accepted on write.
- TYP-11 Standard codes: country ISO 3166-1 alpha-2 uppercase (`DE`), language BCP 47, timezone IANA name, phone E.164 (`+4971112345678`), currency ISO 4217 uppercase. Lowercase country or currency codes are rejected, not corrected.
- TYP-12 Email: maximum 254 characters, one address, no display name, domain lowercased on storage. URLs: absolute `https` URL (or documented schemes), maximum 2,048 characters, no embedded credentials, no whitespace.
- TYP-13 Coordinates are `{"latitude", "longitude"}` as JSON numbers in WGS 84, latitude -90 to 90, longitude -180 to 180.
- TYP-14 UUIDs are RFC 9562 hyphenated strings, accepted in any case.
- TYP-15 Arrays have a documented minimum and maximum length. An array that is a set (`tag_ids`) rejects duplicates (`duplicate_values`). Order is preserved where it is documented as meaningful.
- TYP-16 `null` is accepted only on fields documented nullable. On any other field it returns `422` (`null_not_allowed`).

## 7. Validation (VAL)
- VAL-1 Every request is validated against its OpenAPI / JSON Schema before any side effect. Schemas set `additionalProperties: false`, mark `required`, `readOnly` and `writeOnly`, and express nullability as a type array (`["string", "null"]`).
- VAL-2 Validation reports every failure it can find in one response, up to a documented maximum (default guidance: 100), not only the first (response standard ERR-7).
- VAL-3 Validation order inside a body: structure and unknown or read-only fields, then types, then formats, then ranges and lengths, then relation existence, then cross-field rules.
- VAL-4 Error codes in `details[].code` are stable. The standard set:

| Code | Meaning |
|---|---|
| `required` | Required field is missing |
| `null_not_allowed` | `null` on a non-nullable field |
| `invalid_type` | Wrong JSON type |
| `invalid_format` | Right type, wrong format (datetime, email, URL, phone, UUID, decimal) |
| `invalid_choice` | Not an allowed enum value or code |
| `invalid_precision` | Too many decimal places |
| `min_length`, `max_length` | String length |
| `min_value`, `max_value` | Number range |
| `min_items`, `max_items` | Array length |
| `duplicate_values` | Duplicates in a set |
| `unknown_field` | Key not in the schema |
| `read_only_field` | Server-managed field sent |
| `does_not_exist` | Relation id not found or not visible to the caller |
| `invalid_file` | File failed type, size or content checks |
| `checksum_mismatch` | Declared digest does not match the bytes |
| `duplicate_operation` | Same target twice in one bulk request |
| `invalid_json` | Body is not valid JSON (with `field` `$`) |
| `max_depth` | Nesting deeper than the limit (with `field` `$`) |

- VAL-5 Cross-field rules attribute the error to the field the client should change. When no single field fits, the error uses `"field": "$"` for the whole body.
- VAL-6 A relation id the caller may not access returns `does_not_exist`, the same as an id that does not exist (response standard REL-10, REL-11).
- VAL-7 Shape and value problems are `422`. Conflicts with current state are `409` and are checked only after validation passes: uniqueness violations (`already_exists`, with `details[].field`), disallowed state transitions (`invalid_state_transition`), and `request_in_progress`.
- VAL-8 Validation never reveals data the caller could not read, and error messages never echo secrets or unsanitized input (response standard ERR-10).
- VAL-9 Messages are localized via `Accept-Language`. Codes are not.
- VAL-10 Validation is deterministic: the same request against the same state yields the same errors in the same order.

## 8. Write semantics (WRT)
- WRT-1 `POST` creates. The server assigns `id`, `uid` and audit fields. Client-supplied ids are never accepted. `PUT` never creates: an unknown target returns `404`.
- WRT-2 `PUT` replaces the writable representation. All required writable fields must be present. Omitted optional fields reset to their documented default (or `null`), and groups omitted become `null`.
- WRT-3 `PATCH` follows JSON Merge Patch (RFC 7396). An omitted key is unchanged, `null` clears a nullable field (or a whole group), objects merge recursively, and arrays replace entirely. `Content-Type` is `application/merge-patch+json`; `application/json` is accepted with the same meaning. JSON Patch (`application/json-patch+json`) is not supported and returns `415`.
- WRT-4 `null` on a non-nullable field in `PUT` or `PATCH` returns `422` (`null_not_allowed`). An empty `PATCH` body `{}` is valid and changes nothing.
- WRT-5 A `PUT` or `PATCH` whose result equals the stored state is a no-op: it returns `200` with the current representation, and `updated_at` and `ETag` do not change.
- WRT-6 Defaults apply on `POST` and `PUT` only, and are documented in the schema. `PATCH` never re-applies defaults.
- WRT-7 Every write is all-or-nothing. A `4xx` response means nothing was persisted. After a `5xx`, a timeout or a lost connection the outcome is unknown, and clients retry with the same `Idempotency-Key`.
- WRT-8 Idempotency:
  - Sent on `POST` and on non-idempotent `PATCH` actions. Never needed on `GET`, `PUT` or `DELETE`. Endpoints may require it (documented); a missing key then returns `400` (`idempotency_key_required`).
  - The key is a UUID (RFC 9562), at most 64 characters. Anything else returns `400` (`invalid_idempotency_key`).
  - Scope is credential plus method plus path. The server stores a fingerprint of the body and keeps keys for a documented period (default guidance: 24 hours).
  - Replay with the same body returns the original status and body plus `Idempotency-Replayed: true`, without re-running side effects or re-checking preconditions.
  - Same key with a different body or path returns `422` (`idempotency_key_reuse`). Same key while the first request is still running returns `409` (`request_in_progress`).
  - Only completed outcomes are stored, with the exception of `5xx` responses, which are not stored so that a retry can run.
- WRT-9 Preconditions (RFC 9110): `If-Match` carries one or more quoted strong ETags, or `*` for "any current version". Required on `PUT`, `PATCH` and `DELETE` for resources that need concurrency control: missing → `428`, no match → `412`. Weak validators (`W/"..."`) never match `If-Match`. `If-None-Match` on `GET` returns `304`. A `PUT` or `POST` never uses `If-None-Match: *` to mean create-if-absent unless documented.
- WRT-10 Side effects stay out of safe methods: a `GET` never changes state, even for counters, "last seen" or audit.
- WRT-11 Business actions that change state go through actions (ACB-1), not through direct writes of the `status` field.
- WRT-12 Concurrent requests on one resource are serialized per resource. The loser gets `412` when it used `If-Match`, otherwise last write wins and the behavior is documented per endpoint.

## 9. Actions and bulk (ACB)
- ACB-1 An action is `POST /<collection>/{id}/actions/<verb>` (collection level: `POST /<collection>/actions/<verb>`). Its body is defined per action, unknown fields return `422`, and an empty body is valid when the action takes no parameters.
- ACB-2 Actions take the same headers as writes: `If-Match` where the resource is concurrency-controlled, `Idempotency-Key` for non-idempotent ones.
- ACB-3 A bulk request is `POST /<collection>/bulk` with the body `{"mode": "atomic" | "partial", "operations": [...]}`. `mode` defaults to `atomic`.
- ACB-4 An operation is `{"action": "create" | "update" | "delete" | "<verb>", "id": <id>, "data": {...}, "if_match": "\"<etag>\""}`. `id` is absent for `create` and required otherwise. `data` follows the same rules as the corresponding single request, including strictness. `if_match` carries the per-operation precondition.
- ACB-5 The number of operations has a documented maximum (default guidance: 100). More returns `422` (`max_items`) on `operations`. An empty list returns `422` (`min_items`).
- ACB-6 Operations run in order. The same target twice in one request returns `422` (`duplicate_operation`). One request addresses one collection.
- ACB-7 Validation errors use paths of the form `operations[1].data.description`.
- ACB-8 Atomic mode applies everything or nothing. Partial mode validates and applies each operation independently and reports per-operation results (response standard BLK-2).
- ACB-9 Bulk requests support `Idempotency-Key`, and SHOULD require it.

## 10. Files and uploads (UPL)
- UPL-1 Small uploads use `multipart/form-data` (RFC 7578) with exactly one `file` part and optional text parts named after writable fields. Part names are case-sensitive. A missing `file` part, a second `file` part or an unknown part returns `422` (`required`, `duplicate_values`, `unknown_field`).
- UPL-2 The declared size is enforced while streaming. Exceeding it stops the upload and returns `413`. Limits cover the whole body, each part, the number of parts (default guidance: 20) and the file.
- UPL-3 The part's `Content-Type` and filename are hints. The server sniffs the content type, checks it against the allowlist, and returns `415` or `422` (`invalid_file`) on mismatch. The filename from `Content-Disposition` (RFC 6266 / 8187) is stored as metadata and is never used as a storage path.
- UPL-4 Large uploads are two-step. Step 1 sends `{"name", "content_type", "size_bytes", "checksum": {"algorithm": "sha256", "value": "<lowercase hex>"}}`. The server answers with a short-lived upload target. The client sends the bytes to that target. Step 3 calls the `complete` action, and the server verifies size, checksum and sniffed type.
- UPL-5 Checksum algorithms are an allowlist (`sha256`). A client MAY send `Content-Digest` (RFC 9530) on a direct upload, and the server then verifies it and returns `422` (`checksum_mismatch`) on a difference.
- UPL-6 Files are scanned or validated asynchronously where required. The resource stays `pending` until it is `ready` or `rejected`.
- UPL-7 Upload endpoints do not accept JSON bodies containing file bytes or base64 strings.
- UPL-8 Resumable or ranged uploads exist only where documented. `Range` on an upload endpoint otherwise returns `400`.

## 11. Search requests (SRC)
- SRC-1 A search too complex for query parameters MAY use `POST /<collection>/search` with the body `{"filter": {...}, "ordering": [...], "page": 1, "page_size": 25}` (or `cursor` instead of `page`).
- SRC-2 It is a read: it returns `200` with the standard list envelope, creates nothing, and needs no `Idempotency-Key`. It is not cacheable.
- SRC-3 The filter grammar is documented, allowlisted per field and operator, bounded in depth and number of conditions, and never passed to the database as raw text.
- SRC-4 The same validation, pagination and limit rules apply as for list queries (QRY).

## 12. Authentication in requests (AUT)
- AUT-1 Credentials travel in one `Authorization: Bearer <token>` header (RFC 6750). Tokens are opaque, bounded in length, and never in the query string, path, body or other headers.
- AUT-2 Two credentials in one request (two `Authorization` headers, or a header plus a cookie session) return `400`.
- AUT-3 `Basic` is accepted only on documented token endpoints. Passwords and secrets appear in bodies only on credential endpoints, as write-only fields, over TLS.
- AUT-4 First-party browser clients may use a secure cookie. State-changing requests then require CSRF protection (SAF-8).
- AUT-5 A missing, malformed or expired credential returns `401` with `WWW-Authenticate`. A valid credential without the required scope returns `403` (`insufficient_scope`).
- AUT-6 A request body or query never carries tenant or user identity that overrides the credential (response standard SEC-15).

## 13. Limits and abuse resistance (LIM)
- LIM-1 Limits are enforced, documented in OpenAPI, and defined per endpoint. Default guidance:

| Limit | Default guidance | Status |
|---|---|---|
| JSON body size | 1 MiB | `413` |
| Direct upload size | documented per endpoint | `413` |
| Total header size | 8 KiB | `431` |
| URL (path + query) | 2,048 characters | `414` |
| JSON nesting depth | 32 | `400` |
| Keys per object | 1,000 | `400` |
| Array length | documented per field (default 1,000) | `422` `max_items` |
| String length | documented per field | `422` `max_length` |
| Bulk operations | 100 | `422` `max_items` |
| Multipart parts | 20 | `413` |
| Search term `q` | 200 characters | `400` |
| Body read time | 30 seconds | `408` |

- LIM-2 Size limits are enforced while the body streams. `Content-Length` over the limit is refused before reading, and chunked bodies are cut off when they pass it.
- LIM-3 Slow or stalled bodies hit the read timeout and return `408`. Connections are closed after the response.
- LIM-4 Rate limits and per-credential concurrency limits apply to every endpoint (response standard SEC-10). Upload, export and authentication endpoints have stricter limits.
- LIM-5 A body sent without `Content-Length` or chunked encoding returns `411`.
- LIM-6 Decompressed size is limited the same as the body, with a compression-ratio limit to stop decompression bombs.
- LIM-7 A request refused by a limit never partially executes.

## 14. Request safety (SAF)
- SAF-1 Object-level authorization is checked for every identifier in the path, the query and the body (OWASP API1). Ids are guessable, so authorization never depends on secrecy (response standard REL-11).
- SAF-2 Property-level authorization: callers may only write fields their role allows (OWASP API3). A forbidden field returns `403` (`permission_denied`) with the field in `details`. Mass assignment is blocked by the strict schema (BDY-6, BDY-7).
- SAF-3 `Content-Type: application/json` is required for JSON bodies. `text/plain`, `application/x-www-form-urlencoded` and other "simple" types are refused with `415`, which keeps cross-site form posts from reaching the API.
- SAF-4 XML, YAML and other body formats are not accepted (`415`). This removes XXE and unsafe-deserialization paths.
- SAF-5 Inputs are parameterized, never concatenated into queries or commands. Filters, ordering and `fields` are allowlists, never raw column names or expressions.
- SAF-6 Any URL the server will fetch (webhook targets, import URLs) is validated: allowlisted scheme, resolved address not private, loopback or link-local, redirects not followed, and the resolved address pinned for the request (OWASP API7).
- SAF-7 Resource consumption is bounded (LIM) and business flows that can be abused (account creation, password reset, exports) have extra limits (OWASP API4, API6).
- SAF-8 Cookie-authenticated state changes require a CSRF token header plus an `Origin` check. A failure returns `403` (`csrf_failed`).
- SAF-9 Request bodies are not logged by default. Logs redact `Authorization`, cookies, write-only fields and personal data.
- SAF-10 File names, paths and object keys derived from input are sanitized or generated, never trusted.

## 15. Order of checks (CHK)
- CHK-1 Checks run in this order, and the first failure wins:

| Step | Check | Status |
|---|---|---|
| 1 | Connection, header, URL and declared-size limits | `431`, `414`, `413`, `408`, `411` |
| 2 | Route and method | `404`, `405` |
| 3 | Path identifier syntax | `404` |
| 4 | Authentication | `401` |
| 5 | Rate limit | `429` |
| 6 | Content negotiation (`Content-Type`, `Accept`, `Content-Encoding`) | `415`, `406` |
| 7 | Body parse and structural limits | `400`, `413` |
| 8 | Authorization: scope, then object | `403`, `404` |
| 9 | Idempotency lookup | replay, `409`, `422` |
| 10 | Preconditions (`If-Match`) | `428`, `412` |
| 11 | Validation (VAL-3 order) | `422` |
| 12 | Uniqueness and state conflicts | `409` |
| 13 | Execute atomically | `2xx`, `5xx` |

- CHK-2 A rate limit keyed by IP MAY run before authentication. A limit keyed by credential runs after it.
- CHK-3 An idempotent replay returns the stored response without re-running steps 10 to 13.
- CHK-4 A response never discloses information from a later step to a caller who failed an earlier one.

## 16. Tracing and correlation (TRC)
- TRC-1 A valid client `X-Request-ID` (32 lowercase hex) is honored. A missing or invalid one is replaced by a generated id, and the request is never rejected for it. The value appears on the response and on every log line (response standard OBS-1).
- TRC-2 `traceparent` and `tracestate` are accepted and propagated downstream.
- TRC-3 `Idempotency-Key` and `X-Request-ID` are different: the first identifies a logical operation across retries, the second a single HTTP exchange.

## 17. Compatibility of request contracts (CMP)
- CMP-1 Non-breaking: a new optional request field, a new optional query parameter, a new enum value accepted, a new endpoint, looser validation or larger limits.
- CMP-2 Breaking: a new required field, a removed or renamed field, a changed type, format or meaning, tighter validation, a lower limit, a changed default, or a different error code for the same fault.
- CMP-3 A deprecated request field keeps being accepted for at least one release, marked `deprecated: true` in OpenAPI, with `Deprecation` and `Sunset` headers on responses that use it. It is never silently ignored.
- CMP-4 Request breaking changes follow the same approval and migration plan as response ones (response standard VER-1).

## 18. Documentation and testing (TST)
- TST-1 Every endpoint documents its request: method, path and query parameters, headers, body schema (types, `required`, nullability, defaults, limits, `readOnly`, `writeOnly`), preconditions, idempotency, scopes, error cases and an example.
- TST-2 Request examples in the docs are valid against the schema and validated in CI (response standard DOC-3).
- TST-3 Contract tests send one invalid request per rule and assert both the status and the `details[].code`: each of the VAL-4 codes, wrong `Content-Type`, body on `GET`, duplicate keys, oversize body, stale `If-Match`, missing `If-Match`, idempotency replay and mismatch.
- TST-4 Property or fuzz tests send random JSON, oversized and deeply nested bodies, and invalid Unicode, and assert that no request returns `5xx` or partially writes.
- TST-5 Authorization tests cover every id in a request: a caller outside the tenant or role gets `404` or `does_not_exist`, never data.
- TST-6 Breaking-change classification (CMP-2) is checked in CI by comparing schema versions.

## 19. Agent review procedure
1. Identify the request type: read, create, replace, partial update, delete, action, bulk, upload or search.
2. Check the design against every applicable section.
3. Output a table: `Rule ID | Status (pass/violation) | Fix`.
4. List breaking changes (CMP-2) and the migration plan.
5. Confirm the OpenAPI request schema was updated and the examples validate.
