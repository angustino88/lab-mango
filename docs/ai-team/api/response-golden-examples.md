# API Golden Examples

> These examples define the target contract. Endpoint-by-endpoint migration is still in progress; see [API response design](../../api-response-design.md) for audit status.

Reference implementations of the [REST API Response Standard](response-standard.md).
When a design differs from these, the agent MUST justify the difference or fix it.
Resource names (`orders`, `products`, `attachments`) are illustrative. Rule IDs after each example point to the standard.

Conventions used throughout:
- Every primary resource has an `id`, used in URLs and references. `id` is the first key.
- `uid` is optional per resource type. `orders`, `products` and `attachments` define it (second key). `customers`, `users` and `audit-events` do not.
- Relations are `{"id", "name"}`. When the target type defines `uid`, the relation is `{"id", "uid", "name"}` everywhere that type is referenced.
- Lookups are `{"id", "name"}` with fixed seeded ids.
- Enums use `{"value", "label"}`.
- Every response carries `X-Request-ID`. Rate-limit headers (here `RateLimit-*`) appear on every response but are shown only in section A to keep examples short.

## A. List, page style: GET /api/orders

`GET /api/orders?status=confirmed&created_at_after=2026-10-01T00:00:00Z&ordering=-created_at&page=1&page_size=2`

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Cache-Control: private, no-cache
Vary: Accept, Accept-Language, Accept-Encoding
Content-Language: en
X-Request-ID: b1f2c3d4e5f60718293a4b5c6d7e8f01
RateLimit-Limit: 600
RateLimit-Remaining: 598
RateLimit-Reset: 41
```
```json
{
  "data": [
    {
      "id": 184,
      "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "number": "ORD-2026-000184",
      "status": {"value": "confirmed", "label": "Confirmed"},
      "customer": {"id": 17, "name": "Acme GmbH"},
      "total": {"amount": "1299.00", "currency": "EUR"},
      "item_count": 3,
      "created_at": "2026-10-14T09:30:00Z",
      "updated_at": "2026-10-15T14:02:11Z"
    },
    {
      "id": 183,
      "uid": "a1b2c3d4-0000-4000-8000-000000000002",
      "number": "ORD-2026-000183",
      "status": {"value": "confirmed", "label": "Confirmed"},
      "customer": {"id": 17, "name": "Acme GmbH"},
      "total": {"amount": "89.90", "currency": "EUR"},
      "item_count": 1,
      "created_at": "2026-10-13T16:45:00Z",
      "updated_at": "2026-10-13T16:45:00Z"
    }
  ],
  "meta": {
    "pagination": {
      "count": 42,
      "page": 1,
      "page_size": 2,
      "next": "/api/orders?status=confirmed&created_at_after=2026-10-01T00:00:00Z&ordering=-created_at&page=2&page_size=2",
      "previous": null
    }
  }
}
```
Patterns: ENV-2, REL-1..3, REL-8 (`item_count`, no inline items), COL-1..3, COL-8, STR-4 (summary only), FMT-1, FMT-2, ENU-1, CCH-1, CCH-4, SEC-10.

Lookup by the optional uid, for example from a redirect service: `GET /api/orders?uid=7c9e6679-7425-40de-944b-e07fc1f90ae7` returns a one-item page (REL-2).

Empty result: `200` with `"data": []` and `"count": 0` (ENV-4). Page size above the maximum: `400` (section P).

## B. List, cursor style: GET /api/audit-events

`GET /api/audit-events?page_size=2&cursor=eyJpZCI6MTAyfQ`

```json
{
  "data": [
    {
      "id": 101,
      "type": "order.confirmed",
      "actor": {"id": 5, "name": "J. Meyer"},
      "target_url": "/api/orders/184",
      "created_at": "2026-10-15T14:02:11Z"
    },
    {
      "id": 100,
      "type": "order.created",
      "actor": {"id": 5, "name": "J. Meyer"},
      "target_url": "/api/orders/184",
      "created_at": "2026-10-14T09:30:00Z"
    }
  ],
  "meta": {
    "pagination": {
      "count": null,
      "page_size": 2,
      "next_cursor": "eyJpZCI6OTl9",
      "previous_cursor": "eyJpZCI6MTAxfQ"
    }
  }
}
```
Patterns: COL-2 (cursor style, `count` is `null` when not computed), PRF-5, NAM-7. Cursors are opaque; clients pass them back unchanged. This type has no `uid`.

## C. Detail: GET /api/orders/{id}

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Cache-Control: private, no-cache
ETag: "a91f"
X-Request-ID: b1f2c3d4e5f60718293a4b5c6d7e8f02
```
```json
{
  "data": {
    "id": 184,
    "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "number": "ORD-2026-000184",
    "status": {
      "value": "confirmed",
      "label": "Confirmed",
      "metadata": {"payment_reference": "PAY-8841", "expected_ship_date": "2026-10-20"}
    },
    "channel": {"id": 2, "name": "Online"},
    "customer": {"id": 17, "name": "Acme GmbH"},
    "sales_rep": null,
    "shipping_address": {
      "line_1": "Hauptstrasse 12",
      "line_2": null,
      "postal_code": "70173",
      "city": "Stuttgart",
      "country": "DE"
    },
    "billing_address": null,
    "total": {"amount": "1299.00", "currency": "EUR"},
    "discount": null,
    "item_count": 3,
    "items_url": "/api/orders/184/items",
    "description": null,
    "metadata": {},
    "created_at": "2026-10-14T09:30:00Z",
    "updated_at": "2026-10-15T14:02:11Z",
    "created_by": {"id": 5, "name": "J. Meyer"},
    "updated_by": {"id": 5, "name": "J. Meyer"}
  },
  "meta": {"restricted_fields": []}
}
```
Patterns: REL-1..3, NUL-1..4 (absent relations and groups are `null`, all keys always present), REL-5, STR-1 (grouped address), STR-2, STR-7, ENU-4 (status metadata), FMT-2, RW-5 (`ETag`), SEC-3.

Same resource for a caller without permission to see prices: `"total": null`, `"discount": null` and `"meta": {"restricted_fields": ["total", "discount"]}`. Keys stay present (NUL-3, SEC-3).

Because ids are guessable, a caller who requests an order they may not see gets `404`, not `403` (REL-11, ERR-5).

Audit fields (STR-2, STR-7..9). A scheduled job shipped this order, so there is no human actor for the last change:
```json
{
  "created_at": "2026-10-14T09:30:00Z",
  "updated_at": "2026-10-16T06:00:00Z",
  "created_by": {"id": 5, "name": "J. Meyer"},
  "updated_by": null
}
```
If user 5 is later erased, `created_by` stays `{"id": 5, "name": "Deleted user"}` (REL-12). For a caller without permission to see actors, `created_by` and `updated_by` are `null` and `"meta": {"restricted_fields": ["created_by", "updated_by"]}` tells the client the `null` means "hidden", not "system". `updated_at` is for display and sync only. Concurrency uses the `ETag` (RW-5, STR-9). Lookups carry no audit fields, and immutable records such as audit events carry `created_at` only (STR-8).

## D. Conditional read: GET with If-None-Match

```http
GET /api/orders/184
If-None-Match: "a91f"
```
```http
HTTP/1.1 304 Not Modified
ETag: "a91f"
Cache-Control: private, no-cache
X-Request-ID: b1f2c3d4e5f60718293a4b5c6d7e8f03
```
No body. Patterns: CCH-2.

## E. Create: POST /api/orders

Request (write serializer takes `<relation>_id`, and no read-only fields such as `id` or `uid`):
```http
POST /api/orders
Content-Type: application/json
Idempotency-Key: 5d41402a-bc4b-4a2c-9f0e-1b7c0e6e9a11
```
```json
{
  "customer_id": 17,
  "channel_id": 2,
  "shipping_address": {
    "line_1": "Hauptstrasse 12", "line_2": null,
    "postal_code": "70173", "city": "Stuttgart", "country": "DE"
  },
  "description": null
}
```
Response:
```http
HTTP/1.1 201 Created
Location: /api/orders/184
ETag: "a91f"
```
Body: the full detail shape from section C. The server assigns `id` and `uid`.

A replay with the same key and body returns the same `201` and body with `Idempotency-Replayed: true`. Same key with a different body returns `422` (`idempotency_key_reuse`). Same key while the first request still runs returns `409` (`request_in_progress`). Patterns: NAM-6, RW-2, RW-4, RW-6.

## F. Replace: PUT /api/orders/{id}

```http
PUT /api/orders/184
If-Match: "a91f"
```
The body is the complete writable representation (same fields as section E). Optional writable fields that are omitted reset to their default or `null`. Response: `200` with the full detail shape and a new `ETag`. Patterns: RW-4, RW-5.

## G. Partial update: PATCH /api/orders/{id}

Merge Patch semantics: omitted keys unchanged, `null` clears, objects merge, arrays replace (NUL-5).
```http
PATCH /api/orders/184
If-Match: "a91f"
```
```json
{
  "description": "Deliver to loading dock B",
  "shipping_address": {"line_2": "Dock B"},
  "discount": null
}
```
Response: `200 OK` with the full detail shape from C (never just the changed fields) and a new `ETag`. A stale `If-Match` returns `412`, a missing one `428` (section P).

## H. Delete: DELETE /api/orders/{id}

```http
DELETE /api/orders/184
If-Match: "a91f"
```
`204 No Content`, empty body (ENV-5). A repeated delete returns `404` with the standard error body (HTTP-5).

## I. Action: POST /api/orders/{id}/actions/cancel

```json
{"reason": "Customer changed their mind"}
```
Response: `200 OK` with the full detail shape from C, now with `"status": {"value": "canceled", "label": "Canceled", "metadata": {...}}` and a new `ETag`.

Disallowed transition, `409`:
```json
{
  "error": {
    "code": "invalid_state_transition",
    "message": "A shipped order cannot be canceled.",
    "details": [{"field": "status", "code": "transition_not_allowed", "message": "shipped -> canceled"}],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f04"
  }
}
```
Patterns: ACT-1..3, ENU-6.

## J. Asynchronous job: POST /api/orders/exports

Job resources use a string `id` (a UUID). The type is fixed for this resource (FMT-5, REL-1).

Start:
```http
HTTP/1.1 202 Accepted
Location: /api/orders/exports/e4a1f7b2-0000-4000-8000-000000000010
Retry-After: 5
```
```json
{
  "data": {
    "id": "e4a1f7b2-0000-4000-8000-000000000010",
    "status": {"value": "queued", "label": "Queued"},
    "progress": null,
    "result_url": null,
    "error": null,
    "created_at": "2026-10-16T08:12:00Z",
    "updated_at": "2026-10-16T08:12:00Z",
    "completed_at": null
  }
}
```
Poll while running (`200`, with `Retry-After: 5`): `"status": {"value": "running", "label": "Running"}`, `"progress": 40`.

Succeeded: `"status": {"value": "succeeded", "label": "Succeeded"}`, `"progress": 100`, `"result_url": "/api/orders/exports/e4a1f7b2-0000-4000-8000-000000000010/download"`, `"completed_at": "2026-10-16T08:12:41Z"`. The result URL is a permission-checked download endpoint (FIL-4).

Failed (the poll itself is still `200`, ASY-7):
```json
{
  "data": {
    "id": "e4a1f7b2-0000-4000-8000-000000000010",
    "status": {"value": "failed", "label": "Failed"},
    "progress": 40,
    "result_url": null,
    "error": {
      "code": "export_failed",
      "message": "The export could not be completed.",
      "details": [],
      "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f05"
    },
    "created_at": "2026-10-16T08:12:00Z",
    "updated_at": "2026-10-16T08:12:30Z",
    "completed_at": "2026-10-16T08:12:30Z"
  }
}
```
Cancel with `POST .../exports/{id}/actions/cancel`. A canceled or finished job returns `409`. After the retention period, polling returns `410`. Patterns: ASY-1..7, RW-6.

## K. Bulk: POST /api/orders/bulk

Atomic (default):
```json
{
  "operations": [
    {"action": "update", "id": 184, "data": {"description": "Dock B"}},
    {"action": "update", "id": 183, "data": {"description": "Dock C"}}
  ]
}
```
Success: `200` with `"data"` holding one result per operation, in order:
```json
{
  "data": [
    {"index": 0, "id": 184, "status_code": 200},
    {"index": 1, "id": 183, "status_code": 200}
  ]
}
```
Failure applies nothing and returns `422`:
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more operations are invalid.",
    "details": [{"field": "operations[1].data.description", "code": "max_length", "message": "Ensure this field has no more than 500 characters."}],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f06"
  }
}
```
Partial mode (`"mode": "partial"` in the request): `200` with a result per operation, each success or failure inline:
```json
{
  "data": [
    {"index": 0, "id": 184, "status_code": 200},
    {
      "index": 1,
      "id": 183,
      "status_code": 422,
      "error": {
        "code": "validation_failed",
        "message": "One or more fields are invalid.",
        "details": [{"field": "data.description", "code": "max_length", "message": "Ensure this field has no more than 500 characters."}],
        "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f06"
      }
    }
  ]
}
```
Patterns: BLK-1..3.

## L. Files

Metadata resource (`GET /api/attachments/{id}`). The `order` relation carries `uid` because orders define it (REL-3):
```json
{
  "data": {
    "id": 20,
    "uid": "c0ffee00-0000-4000-8000-000000000020",
    "order": {"id": 184, "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "name": "ORD-2026-000184"},
    "name": "invoice.pdf",
    "content_type": "application/pdf",
    "size_bytes": 482113,
    "checksum": {"algorithm": "sha256", "value": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"},
    "status": {"value": "ready", "label": "Ready"},
    "download_url": "/api/attachments/20/download",
    "created_at": "2026-10-16T09:00:00Z",
    "updated_at": "2026-10-16T09:00:05Z",
    "created_by": {"id": 5, "name": "J. Meyer"},
    "updated_by": {"id": 5, "name": "J. Meyer"}
  }
}
```

Small upload: `POST /api/orders/{id}/attachments` with `multipart/form-data` returns `201` and the metadata above.

Large upload, step 1: `POST /api/orders/{id}/attachments/uploads`
```json
{"name": "scan.tiff", "content_type": "image/tiff", "size_bytes": 734003200, "checksum": {"algorithm": "sha256", "value": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"}}
```
```http
HTTP/1.1 201 Created
Location: /api/attachments/21
```
```json
{
  "data": {
    "id": 21,
    "uid": "c0ffee00-0000-4000-8000-000000000021",
    "status": {"value": "pending", "label": "Pending upload"},
    "upload": {
      "url": "https://storage.example.com/uploads/abc123?signature=...",
      "method": "PUT",
      "headers": {"Content-Type": "image/tiff"},
      "expires_at": "2026-10-16T09:15:00Z"
    },
    "download_url": null
  }
}
```
Step 2: the client sends the bytes to `upload.url`. Step 3: `POST /api/attachments/{id}/actions/complete`. The server verifies size, checksum and sniffed type, then returns `200` with the metadata shape and `"status": {"value": "ready", ...}`. A failed check returns `422` with `invalid_file`.

Download: `GET /api/attachments/{id}/download`, either a redirect:
```http
HTTP/1.1 302 Found
Location: https://storage.example.com/downloads/abc123?signature=...
Cache-Control: no-store
```
or a stream:
```http
HTTP/1.1 200 OK
Content-Type: application/pdf
Content-Length: 482113
Content-Disposition: attachment; filename="invoice.pdf"; filename*=UTF-8''invoice.pdf
Accept-Ranges: bytes
ETag: "5e1c"
X-Content-Type-Options: nosniff
```
With `Range: bytes=0-1023` the response is `206 Partial Content` with `Content-Range: bytes 0-1023/482113`. Neither response uses the envelope (ENV-7). Patterns: FIL-1..7.

## M. Streaming

Event ids are unique strings (EVT-1).

Server-Sent Events, `GET /api/orders/events` (`Accept: text/event-stream`):
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
```
```text
: heartbeat

id: 9f1d6a1e-0000-4000-8000-000000000301
event: order.confirmed
data: {"id": "9f1d6a1e-0000-4000-8000-000000000301", "type": "order.confirmed", "created_at": "2026-10-16T09:10:00Z", "data": {"id": 184, "order_url": "/api/orders/184"}}
```
A reconnecting client sends `Last-Event-ID` to resume.

NDJSON export, `GET /api/orders/export.ndjson` (`Content-Type: application/x-ndjson`), one object per line, no envelope:
```text
{"id": 184, "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "number": "ORD-2026-000184", "created_at": "2026-10-14T09:30:00Z"}
{"id": 183, "uid": "a1b2c3d4-0000-4000-8000-000000000002", "number": "ORD-2026-000183", "created_at": "2026-10-13T16:45:00Z"}
{"error": {"code": "internal_error", "message": "The export was interrupted.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f07"}}
```
The last line shows how a mid-stream failure is reported after the `200` has been sent (STM-2). Patterns: STM-1..4, EVT-1.

## N. Webhook delivery

The platform sends to the subscriber's URL:
```http
POST /hooks/orders HTTP/1.1
Host: receiver.example.com
Content-Type: application/json
Webhook-Id: 9f1d6a1e-0000-4000-8000-000000000301
Webhook-Timestamp: 1792141800
Webhook-Signature: v1,Zm9vYmFyYmF6cXV4...
```
```json
{
  "id": "9f1d6a1e-0000-4000-8000-000000000301",
  "type": "order.confirmed",
  "created_at": "2026-10-16T09:10:00Z",
  "data": {
    "id": 184,
    "order_url": "/api/orders/184"
  }
}
```
`Webhook-Id` equals the event `id`. The receiver verifies the HMAC over `Webhook-Id.Webhook-Timestamp.body`, rejects stale timestamps, dedupes by event `id`, and answers `2xx` quickly. Anything else is retried with backoff (EVT-1..6).

## O. Lookup hierarchy and relation writes: /api/products

Detail (ancestors allowed, REL-7):
```json
{
  "data": {
    "id": 42,
    "uid": "9c03dbc8-c0f2-4f45-9508-223ebc63f42a",
    "category": {"id": 1, "name": "Computing"},
    "type": {"id": 4, "name": "Workstation"},
    "sku": "SKU-1042",
    "name": "Acquisition workstation",
    "owner": {"id": 9, "name": "A. Scientist"},
    "tags": [{"id": 11, "name": "Lab"}, {"id": 14, "name": "Shared"}],
    "price": {"amount": "1299.00", "currency": "EUR"},
    "created_at": "2026-10-14T09:30:00Z",
    "updated_at": "2026-10-15T14:02:11Z",
    "created_by": {"id": 9, "name": "A. Scientist"},
    "updated_by": {"id": 9, "name": "A. Scientist"}
  },
  "meta": {"restricted_fields": []}
}
```
List item (STR-4, REL-7): only the most specific lookup, no `category`.
```json
{
  "id": 42,
  "uid": "9c03dbc8-c0f2-4f45-9508-223ebc63f42a",
  "type": {"id": 4, "name": "Workstation"},
  "sku": "SKU-1042",
  "name": "Acquisition workstation",
  "owner": {"id": 9, "name": "A. Scientist"},
  "updated_at": "2026-10-15T14:02:11Z"
}
```
Write: every relation uses `<relation>_id`, small to-many uses `<relation>_ids` with replace semantics (NAM-6, REL-9):
```json
{"type_id": 4, "owner_id": 9, "tag_ids": [11, 14], "sku": "SKU-1042", "name": "Acquisition workstation", "price": {"amount": "1299.00", "currency": "EUR"}}
```
Localization: with `Accept-Language: de`, `name` and `label` come back localized and the response carries `Content-Language: de`. `id`, `value` and error `code` never change (I18N-1).

## P. Errors

Every error uses the envelope of ERR-1, has a `request_id`, and is sent with `Cache-Control: no-store`.

Validation, `422` (nested and array paths, all failures at once):
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "customer_id", "code": "does_not_exist", "message": "Customer not found."},
      {"field": "shipping_address.postal_code", "code": "required", "message": "This field is required."},
      {"field": "tag_ids[1]", "code": "does_not_exist", "message": "Tag not found."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f10"
  }
}
```

Unknown or read-only field in a write body, `422`:
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "id", "code": "read_only_field", "message": "This field cannot be set."},
      {"field": "uid", "code": "read_only_field", "message": "This field cannot be set."},
      {"field": "colour", "code": "unknown_field", "message": "Unknown field."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f11"
  }
}
```

Malformed request, `400`:
```json
{"error": {"code": "malformed_request", "message": "Request body is not valid JSON.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f12"}}
```

Unknown filter or invalid page size, `400` (COL-1, COL-4):
```json
{
  "error": {
    "code": "invalid_query",
    "message": "One or more query parameters are invalid.",
    "details": [
      {"field": "ordering", "code": "invalid_choice", "message": "'colour' is not sortable."},
      {"field": "page_size", "code": "max_value", "message": "Maximum page size is 100."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f13"
  }
}
```

Unauthenticated, `401` (with `WWW-Authenticate: Bearer realm="api", error="invalid_token"`):
```json
{"error": {"code": "unauthenticated", "message": "Authentication credentials are missing or invalid.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f14"}}
```

Forbidden, `403`:
```json
{"error": {"code": "permission_denied", "message": "You do not have permission to perform this action.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f15"}}
```

Not found, `404` (also used when existence must stay hidden, ERR-5, REL-11):
```json
{"error": {"code": "not_found", "message": "Order not found.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f16"}}
```

Method not allowed, `405` (with `Allow: GET, POST`):
```json
{"error": {"code": "method_not_allowed", "message": "Method not allowed.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f17"}}
```

Not acceptable, `406`; unsupported media type, `415`:
```json
{"error": {"code": "unsupported_media_type", "message": "Content-Type must be application/json.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f18"}}
```

Conflict, `409` (see section I for `invalid_state_transition`):
```json
{"error": {"code": "request_in_progress", "message": "A request with this Idempotency-Key is still being processed.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f19"}}
```

Precondition failed, `412`; precondition required, `428`:
```json
{"error": {"code": "precondition_failed", "message": "The resource was modified by someone else. Reload and retry.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1a"}}
```
```json
{"error": {"code": "precondition_required", "message": "This request requires an If-Match header.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1b"}}
```

Body too large, `413`:
```json
{"error": {"code": "payload_too_large", "message": "Request body exceeds the maximum size.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1c"}}
```

Rate limited, `429` (with `Retry-After: 30`):
```json
{"error": {"code": "rate_limited", "message": "Too many requests.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1d"}}
```

Unexpected error, `500` (generic, no internals, ERR-9):
```json
{"error": {"code": "internal_error", "message": "An unexpected error occurred.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1e"}}
```

Unavailable, `503` (with `Retry-After: 60`):
```json
{"error": {"code": "service_unavailable", "message": "The service is temporarily unavailable.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f1f"}}
```

## Q. Operations, CORS and deprecation

Health, `GET /health/ready` (no authentication, no internals, OBS-4):
```json
{"data": {"status": {"value": "ready", "label": "Ready"}}}
```
When not ready: `503` with the standard error envelope.

CORS preflight, `OPTIONS /api/orders` from an allowed origin:
```http
HTTP/1.1 204 No Content
Access-Control-Allow-Origin: https://app.example.com
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE
Access-Control-Allow-Headers: Authorization, Content-Type, If-Match, If-None-Match, Idempotency-Key, X-Request-ID
Access-Control-Expose-Headers: ETag, Location, Retry-After, X-Request-ID, RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset
Access-Control-Max-Age: 600
Vary: Origin
```
An origin outside the allowlist gets no `Access-Control-*` headers (SEC-7).

Deprecated endpoint or field (VER-3):
```http
Deprecation: @1792000000
Sunset: Wed, 01 Jul 2027 00:00:00 GMT
Link: </docs/migrations/orders-v2>; rel="deprecation"; type="text/html"
```

## S. Selector and options endpoint: GET /api/<resource>/options

`GET /api/equipment/options?category=Computing&status=available`

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Cache-Control: private, no-cache
Vary: Accept, Accept-Language, Accept-Encoding
Content-Language: en
X-Request-ID: b1f2c3d4e5f60718293a4b5c6d7e8f90

{
    "data": [
        {
            "id": 101,
            "sku": "EQ-COMP-001",
            "name": "Apple MacBook Pro 16"
        },
        {
            "id": 102,
            "sku": "EQ-COMP-002",
            "name": "Dell Precision 5570"
        }
    ]
}
```

Rules applied: `OPT-1` to `OPT-13` (see response-standard.md, section 26).

## R. Anti-patterns (the agent MUST flag these)

| Bad | Good | Rule |
|---|---|---|
| `[{"id": 1}]` | `{"data": [{"id": 1}]}` | ENV-1 |
| `{"data": {...}, "error": null}` or `{"success": true}` | `{"data": {...}}` | ENV-3 |
| `200` with `{"success": false}` | `422` with `{"error": {...}}` | HTTP-3 |
| resource without `id`, identified only by `name` or `sku` | `id` first key on every primary resource | REL-1 |
| `"id": "42"` here and `"id": 42` elsewhere for the same resource | one type per resource | REL-1, FMT-5 |
| `uid` present on some responses of a type, absent on others | `uid` always present or never defined for the type | REL-2, NUL-3 |
| `uid` used as the URL key while `id` is also exposed | URLs use `id`, `uid` via `?uid=` | REL-1, REL-2 |
| relying on a hard-to-guess id for access control | per-object authorization, `404` when hidden | REL-11, SEC-2 |
| `"owner": 17` | `"owner": {"id": 17, "name": "..."}` | REL-3 |
| `"owner": 1, "owner_name": "J"` | `"owner": {...}` | REL-4 |
| relation to an order as `{"id": 184, "name": "..."}` when orders define `uid` | `{"id": 184, "uid": "...", "name": "..."}` everywhere | REL-3 |
| `"type": {"id": 4, "uid": "...", "code": "workstation", "name": "..."}` | `"type": {"id": 4, "name": "Workstation"}` | REL-5 |
| lookup ids that differ between environments | fixed, seeded, never reused | REL-5 |
| list item with `category` and `type` | list item with `type` only | REL-7, STR-4 |
| write body `owner_uid` / `type_code` | `owner_id` / `type_id` | NAM-6 |
| `"city": ""` | `"city": null` | NUL-1 |
| `"items": null` | `"items": []` | NUL-2 |
| key omitted when value is unknown | key present with `null` | NUL-3 |
| PATCH replaces the whole object | PATCH merges, `null` clears | NUL-5 |
| `"price": 12.5` | `"price": {"amount": "12.50", "currency": "EUR"}` | FMT-2 |
| `"acquisition": {"amount": "1299.00", ...}` | `"acquisition_price": {...}` | FMT-7 |
| `"createdAt": "14/10/2026"` | `"created_at": "2026-10-14T09:30:00Z"` | FMT-1, NAM-1 |
| `"total_size": "5 MB"` | `"size_bytes": 5242880` | FMT-6 |
| `"current_status": "available"` | `"status": {"value": "available", "label": "Available"}` | ENU-1, NAM-4 |
| `"is_active": true, "is_closed": false, "is_archived": false` | one `status` enum | ENU-6 |
| `"disk_usage"` as `[]` in one place, `{}` in another | one type everywhere | FMT-5 |
| unknown filter silently ignored | `400` `invalid_query` | COL-4 |
| `page_size=10000` silently clamped | `400` | COL-1 |
| same endpoint accepts `page` and `cursor` | one style per endpoint | COL-2 |
| unknown or read-only write fields (`id`, `uid`) silently ignored | `422` `unknown_field` / `read_only_field` | RW-3 |
| `PUT` that keeps omitted fields | omitted optional fields reset | RW-4 |
| write response returns only changed fields | full detail shape | RW-4 |
| lost-update race, no `If-Match` | `ETag` + `If-Match`, `412` / `428` | RW-5 |
| `Idempotency-Key` returned as a response header only | accepted as a request header | RW-6 |
| verb in path: `/api/cancelOrder` | `POST /api/orders/{id}/actions/cancel` | TRN-6, ACT-1 |
| long export blocks the request | `202` plus a status resource | ASY-1 |
| failed job returns `500` on the poll | `200` with `status: failed` and `error` | ASY-7 |
| array body for bulk | `{"operations": [...]}` | BLK-1 |
| file bytes or base64 inside JSON | metadata plus `download_url` | FIL-1 |
| user HTML served inline from the API origin | attachment or sandbox origin | FIL-6 |
| webhook without signature or timestamp | signed, replay-protected delivery | EVT-3 |
| webhook payload assumes ordered, exactly-once | dedupe by event `id` | EVT-2 |
| token in query string | `Authorization` header | SEC-1 |
| `Access-Control-Allow-Origin: *` with credentials | explicit origin allowlist | SEC-7 |
| price key omitted for unauthorized callers | `null` plus `meta.restricted_fields` | NUL-3, SEC-3 |
| `403` for a record the caller must not know exists | `404` | ERR-5 |
| stack trace or SQL in an error | generic message, details in logs | ERR-5, ERR-9 |
| framework HTML error page on `404` or `500` | standard error envelope | ERR-8 |
| tenant id taken from the request body | tenant from credentials or route | SEC-15 |
| authenticated JSON with no cache headers | `Cache-Control: private, no-cache` plus `ETag` | CCH-1, CCH-2 |
| localized `value` or error `code` | localize `label` / `message` only | I18N-1 |
| `updated_at` used as the concurrency token | `ETag` from a version counter or hash | RW-5, STR-9 |
| `updated_at` changes on a read, or does not change on a write | changes on every successful write only | STR-2 |
| resource without `created_at` / `updated_at` | both always present on primary resources | STR-2 |
| `created_by` dropped or `null` after the user is deleted | `{"id": 5, "name": "Deleted user"}` | REL-12 |
| `updated_by` set to a fake user for system changes | `null` | STR-7 |
| `created_at` with mixed precision (`...:00Z` and `...:00.123Z`) | one documented precision per field | FMT-1, FMT-5 |
| offset pagination on a collection that grows past the documented size | cursor style | COL-9 |
| `403` with no hint when a scope is missing | `403` `insufficient_scope` plus `WWW-Authenticate` | SEC-16 |
| client echoes a `GET` body into `PUT` | build the body from writable fields only | RW-3, RW-7 |
