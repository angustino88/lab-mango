# API Request Golden Examples

> These examples define the target contract. Endpoint-by-endpoint migration is still in progress; see [API response design](../../api-response-design.md) for audit status.

Reference requests for the [REST API Request Standard](request-standard.md). Responses use the envelopes shown in [response-golden-examples.md](response-golden-examples.md).
When a request design differs from these, the agent MUST justify the difference or fix it.
Resources (`orders`, `attachments`) are illustrative. Rule IDs after each example point to the request standard.

Writable fields of `orders`, used throughout:

| Field | Type | Rule |
|---|---|---|
| `customer_id` | integer | required, relation |
| `channel_id` | integer | required, lookup |
| `shipping_address` | object | required. `line_1`, `postal_code`, `city`, `country` required; `line_2` nullable |
| `billing_address` | object or `null` | optional |
| `scheduled_at` | datetime or `null` | optional, RFC 3339 with offset |
| `tag_ids` | integer array | optional, default `[]`, unique, max 20 |
| `description` | string or `null` | optional, 1 to 500 characters |
| `discount` | money or `null` | optional |
| `metadata` | object | optional, default `{}` |

Read-only: `id`, `uid`, `number`, `status`, `total`, `item_count`, `items_url`, and the audit fields. `status` changes only through actions.

## A. Create: POST /api/orders

```http
POST /api/orders HTTP/1.1
Host: api.example.com
Authorization: Bearer <token>
Content-Type: application/json
Accept: application/json
Accept-Language: en
Idempotency-Key: 5d41402a-bc4b-4a2c-9f0e-1b7c0e6e9a11
X-Request-ID: b1f2c3d4e5f60718293a4b5c6d7e8f30
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```
```json
{
  "customer_id": 17,
  "channel_id": 2,
  "scheduled_at": "2026-10-20T08:00:00+02:00",
  "shipping_address": {
    "line_1": "Hauptstrasse 12",
    "line_2": null,
    "postal_code": "70173",
    "city": "Stuttgart",
    "country": "DE"
  },
  "tag_ids": [11, 14],
  "description": "Deliver before noon",
  "discount": {"amount": "10.00", "currency": "EUR"}
}
```
Response: `201 Created` with `Location: /api/orders/184`, `ETag` and the full detail shape. `scheduled_at` is stored in UTC and returned as `2026-10-20T06:00:00Z`.
Patterns: BDY-1, TYP-4, TYP-7, TYP-10, WRT-1, WRT-6, WRT-8, HDR-1, TRC-1, TRC-2.

## B. Replace: PUT /api/orders/{id}

```http
PUT /api/orders/184 HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json
If-Match: "a91f"
```
```json
{
  "customer_id": 17,
  "channel_id": 2,
  "shipping_address": {
    "line_1": "Hauptstrasse 12",
    "line_2": "Dock B",
    "postal_code": "70173",
    "city": "Stuttgart",
    "country": "DE"
  }
}
```
Result: every optional writable field that is omitted resets. `billing_address`, `scheduled_at`, `description` and `discount` become `null`, `tag_ids` becomes `[]` and `metadata` becomes `{}`. Response: `200` with the full detail shape and a new `ETag`.
A `PUT` to an id that does not exist returns `404`, it never creates (WRT-1). Patterns: WRT-2, WRT-9.

## C. Partial update: PATCH /api/orders/{id}

Stored state before (writable view):
```json
{
  "customer_id": 17,
  "channel_id": 2,
  "scheduled_at": "2026-10-20T06:00:00Z",
  "shipping_address": {"line_1": "Hauptstrasse 12", "line_2": null, "postal_code": "70173", "city": "Stuttgart", "country": "DE"},
  "tag_ids": [11, 14],
  "description": "Deliver before noon",
  "discount": {"amount": "10.00", "currency": "EUR"}
}
```
Request:
```http
PATCH /api/orders/184 HTTP/1.1
Content-Type: application/merge-patch+json
If-Match: "a91f"
```
```json
{
  "description": null,
  "shipping_address": {"line_2": "Dock B"},
  "discount": null,
  "tag_ids": [14, 15]
}
```
State after:
```json
{
  "customer_id": 17,
  "channel_id": 2,
  "scheduled_at": "2026-10-20T06:00:00Z",
  "shipping_address": {"line_1": "Hauptstrasse 12", "line_2": "Dock B", "postal_code": "70173", "city": "Stuttgart", "country": "DE"},
  "tag_ids": [14, 15],
  "description": null,
  "discount": null
}
```
What happened: `description` and `discount` were cleared (`null`), `shipping_address` merged (only `line_2` changed), `tag_ids` was replaced as a whole, and `scheduled_at` was untouched because the key was omitted.
Errors: `"channel_id": null` returns `422` `null_not_allowed`. `{}` is valid and is a no-op. `application/json-patch+json` returns `415`. Patterns: WRT-3, WRT-4, WRT-5, TYP-15, TYP-16.

No-op: a `PATCH` that sets `"description": null` on an order whose description is already `null` returns `200` with the same `ETag` and an unchanged `updated_at` (WRT-5).

## D. Delete: DELETE /api/orders/{id}

```http
DELETE /api/orders/184 HTTP/1.1
Authorization: Bearer <token>
If-Match: "a91f"
```
No body. Response: `204 No Content`. Sending a body returns `400` (`unexpected_body`). Patterns: MTH-1, WRT-9.

## E. Actions

Action with parameters, `POST /api/orders/184/actions/cancel`:
```http
Content-Type: application/json
If-Match: "a91f"
Idempotency-Key: 6e2b7c1a-1f4d-4a3e-9d5c-2a8b9c0d1e22
```
```json
{"reason": "Customer changed their mind"}
```
Action without parameters, `POST /api/orders/184/actions/confirm` with an empty body:
```http
POST /api/orders/184/actions/confirm HTTP/1.1
Content-Length: 0
```
`{}` is equally valid. Any other body is checked against the action's schema, and an unknown field returns `422` `unknown_field`. Writing `status` directly through `PATCH` returns `422` `read_only_field`. Patterns: ACB-1, ACB-2, MTH-3, WRT-11.

## F. Query parameters

Valid:
```http
GET /api/orders?status=confirmed,shipped&customer_id=17&created_at_after=2026-10-01T00:00:00Z&created_at_before=2026-11-01T00:00:00Z&total_min=100.00&ordering=-created_at,number&q=acme&page=1&page_size=25 HTTP/1.1
```
Invalid, `400`:
```http
GET /api/orders?status=&colour=red&page_size=1000&page=0&created_at_after=2026-10-01&ordering=-colour&ordering=number HTTP/1.1
```
```json
{
  "error": {
    "code": "invalid_query",
    "message": "One or more query parameters are invalid.",
    "details": [
      {"field": "status", "code": "invalid_format", "message": "Value must not be empty."},
      {"field": "colour", "code": "unknown_field", "message": "Unknown query parameter."},
      {"field": "page_size", "code": "max_value", "message": "Maximum page size is 100."},
      {"field": "page", "code": "min_value", "message": "Must be at least 1."},
      {"field": "created_at_after", "code": "invalid_format", "message": "A datetime with a timezone is required."},
      {"field": "ordering", "code": "invalid_choice", "message": "'colour' is not sortable."},
      {"field": "ordering", "code": "invalid_format", "message": "Parameter must not be repeated."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f31"
  }
}
```
Other query rules: an expired or tampered `cursor` returns `400` `invalid_cursor`, and a token in the query string is never read (section P). Patterns: QRY-1..8, QRY-12.

## G. Path parameters

| Request | Result | Rule |
|---|---|---|
| `GET /api/orders/184` | `200` | PTH-1, PTH-5 |
| `GET /api/orders/abc` | `404` | PTH-2 |
| `GET /api/orders/0184` (leading zero) | `404` | PTH-1 |
| `GET /api/orders/-5` | `404` | PTH-1 |
| `GET /api/orders/99999999999999999999` (out of range) | `404` | PTH-2 |
| `GET /api/orders/184%2F..%2Fusers` (encoded traversal) | `404` | PTH-4 |
| `GET /api/orders/9000` (does not exist) | `404` | PTH-2 |
| `GET /api/orders/183` (exists, caller may not see it) | `404`, same body as above | PTH-2, response REL-11 |
| `GET /api/orders/184/items/9` (item 9 belongs to another order) | `404` | PTH-7 |
| `GET /api/orders/184/` | Not a canonical route; no slash-terminated alias or redirect | PTH-5 |
| UUID `7C9E6679-7425-40DE-944B-E07FC1F90AE7` for a `uid` lookup | matched as lowercase | PTH-3 |

## H. Type, format and field strictness

Request: `POST /api/orders`
```json
{
  "customer_id": "17",
  "channel_id": null,
  "id": 99,
  "uid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "confirmed",
  "colour": "red",
  "metadata": "not-an-object",
  "scheduled_at": "2026-10-20T08:00:00",
  "description": "",
  "discount": {"amount": "10.005", "currency": "eur"},
  "tag_ids": [11, 11],
  "shipping_address": {"line_1": "Hauptstrasse 12", "postal_code": "70173", "country": "de"}
}
```
Response: `422`. All failures come back at once, in the order of VAL-3 (structure, types, nulls and required, formats, choices and precision, duplicates, lengths). Nothing is saved.
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "id", "code": "read_only_field", "message": "This field cannot be set."},
      {"field": "uid", "code": "read_only_field", "message": "This field cannot be set."},
      {"field": "status", "code": "read_only_field", "message": "Use an action to change the status."},
      {"field": "colour", "code": "unknown_field", "message": "Unknown field."},
      {"field": "customer_id", "code": "invalid_type", "message": "Expected an integer."},
      {"field": "metadata", "code": "invalid_type", "message": "Expected an object."},
      {"field": "channel_id", "code": "null_not_allowed", "message": "This field cannot be null."},
      {"field": "shipping_address.city", "code": "required", "message": "This field is required."},
      {"field": "scheduled_at", "code": "invalid_format", "message": "A timezone offset is required."},
      {"field": "discount.amount", "code": "invalid_precision", "message": "At most 2 decimal places are allowed."},
      {"field": "discount.currency", "code": "invalid_choice", "message": "Use an uppercase ISO 4217 code."},
      {"field": "shipping_address.country", "code": "invalid_choice", "message": "Use an uppercase ISO 3166-1 alpha-2 code."},
      {"field": "tag_ids", "code": "duplicate_values", "message": "Values must be unique."},
      {"field": "description", "code": "min_length", "message": "Must be at least 1 character."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f32"
  }
}
```
Patterns: BDY-6, BDY-7, TYP-1, TYP-3..4, TYP-7, TYP-9, TYP-11, TYP-15, TYP-16, VAL-2..4.

Other codes:
- Too long: `"description"` with 501 characters returns `max_length`. Too many tags (21) returns `max_items`. A negative `discount.amount` where only positive is allowed returns `min_value`.
- A relation the caller cannot access returns `does_not_exist` on `customer_id` (section P). A unique violation such as a duplicate `sku` returns `409` `already_exists` (section Q).

## I. Format reference (accepted and rejected input)

| Type | Accepted | Rejected (code) |
|---|---|---|
| Integer | `17` | `"17"`, `17.0`, `1e1` (`invalid_type`) |
| Large integer | `"9007199254740993"` as string | number above 2^53 (`invalid_type`) |
| Boolean | `true`, `false` | `"true"`, `1`, `"yes"` (`invalid_type`) |
| Decimal / amount | `"1299.00"`, `"-5"` where allowed | `1299.00` (number), `"1,299.00"`, `"1e3"`, `"+5"`, `" 5 "` (`invalid_type` / `invalid_format`) |
| Amount scale | `"10.00"` for EUR | `"10.005"` (`invalid_precision`) |
| Currency | `"EUR"` | `"eur"`, `"EURO"`, `"XXY"` (`invalid_choice`) |
| Enum | `"confirmed"` | `"Confirmed"`, `{"value": "confirmed", "label": "Confirmed"}` (`invalid_choice` / `invalid_type`) |
| Datetime | `"2026-10-20T08:00:00Z"`, `"2026-10-20T08:00:00+02:00"`, `"2026-10-20T08:00:00.250Z"` where fractions are documented | `"2026-10-20T08:00:00"`, `"2026-10-20 08:00:00Z"`, `"20/10/2026"`, `"2026-10-20T23:59:60Z"` (`invalid_format`) |
| Date | `"2026-10-20"` | `"2026-02-30"`, `"2026-10-20T00:00:00Z"` (`invalid_format`) |
| Duration | `"PT15M"` | `"15 minutes"`, `900` (`invalid_format` / `invalid_type`) |
| Country | `"DE"` | `"de"`, `"DEU"`, `"Germany"` (`invalid_choice`) |
| Language | `"de-CH"` | `"de_CH"`, `"german"` (`invalid_format`) |
| Timezone | `"Europe/Berlin"` | `"CET"`, `"+02:00"` (`invalid_choice`) |
| Phone | `"+4971112345678"` | `"0711 12345678"`, `"+49 (711) 123"` (`invalid_format`) |
| Email | `"a.scientist@example.com"` | `"A Scientist <a@example.com>"`, `"a@b@c"` (`invalid_format`) |
| URL | `"https://example.com/hook"` | `"http://user:pw@example.com"`, `"ftp://example.com"`, `"example.com"` (`invalid_format`) |
| UUID | `"7c9e6679-7425-40de-944b-e07fc1f90ae7"` (any case) | `"7c9e6679742540de944be07fc1f90ae7"` (`invalid_format`) |
| Coordinates | `{"latitude": 48.78, "longitude": 9.18}` | latitude `91`, longitude `-181`, strings (`max_value` / `min_value` / `invalid_type`) |
| String | `"Café"` (stored as NFC) | `"line1\u0007"` control character (`invalid_format`), `"   "` (`min_length`) |
| Relation | `"customer_id": 17` | `"customer_id": {"id": 17, "name": "Acme"}` (`invalid_type`) |
| Set array | `[11, 14]` | `[11, 11]` (`duplicate_values`) |

Patterns: TYP-1..16.

## J. Transport and body failures

| Request | Status and code | Rule |
|---|---|---|
| `GET` with a body | `400` `unexpected_body` | MTH-1 |
| `POST` with no body where one is required | `400` `malformed_request` | MTH-4 |
| `POST` with `Content-Length` but fewer bytes sent | `400` `malformed_request` | HDR-1 |
| Body `[{"customer_id": 17}]` (array) | `400` `malformed_request` | BDY-2 |
| Body `{"customer_id": 17,}` (trailing comma) | `400` `malformed_request` | BDY-3 |
| Body `{"channel_id": 1, "channel_id": 2}` (duplicate keys) | `400` `malformed_request` | BDY-4 |
| Body starting with a UTF-8 byte order mark | `400` `malformed_request` | BDY-4 |
| Body with nesting deeper than 32 levels | `400` `malformed_request`, `details[].field` `$`, code `max_depth` | BDY-5 |
| Body over 1 MiB | `413` `payload_too_large` | LIM-1 |
| `Content-Type: text/plain` or form-urlencoded | `415` `unsupported_media_type` | SAF-3 |
| `Content-Type: application/xml` | `415` `unsupported_media_type` | SAF-4 |
| `Content-Type: application/json; charset=latin1` | `415` `unsupported_media_type` | HDR-1 |
| `Content-Encoding: br` where not documented | `415` `unsupported_media_type` | HDR-1 |
| `Accept: text/html` | `406` `not_acceptable` | HDR-1 |
| Two `Content-Type` headers | `400` `malformed_request` | HDR-3 |
| Headers over 8 KiB | `431` `request_header_fields_too_large` | HDR-6 |
| URL over 2,048 characters | `414` `uri_too_long` | QRY-11 |
| Body not finished within 30 seconds | `408` `request_timeout` | LIM-3 |
| Body with neither `Content-Length` nor chunked encoding | `411` `length_required` | LIM-5 |
| `X-HTTP-Method-Override: DELETE` on a `POST` | header ignored, `POST` semantics apply | MTH-6 |
| `PUT /api/orders` (collection) | `405` with `Allow: GET, POST, HEAD, OPTIONS` | MTH-6 |

Example, `415`:
```json
{
  "error": {
    "code": "unsupported_media_type",
    "message": "Content-Type must be application/json.",
    "details": [],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f33"
  }
}
```
Example, malformed JSON, `400`:
```json
{
  "error": {
    "code": "malformed_request",
    "message": "Request body is not valid JSON.",
    "details": [{"field": "$", "code": "invalid_json", "message": "Unexpected character at line 3, column 21."}],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f34"
  }
}
```

## K. Idempotency

First request: `POST /api/orders` with `Idempotency-Key: 5d41402a-bc4b-4a2c-9f0e-1b7c0e6e9a11`. Response: `201`, `Location: /api/orders/184`.

Network failure, the client retries with the same key and body:
```http
HTTP/1.1 201 Created
Location: /api/orders/184
Idempotency-Replayed: true
```
The body is the original one. No second order is created, and preconditions are not re-checked (CHK-3).

Same key, different body or path, `422`:
```json
{"error": {"code": "idempotency_key_reuse", "message": "This Idempotency-Key was used with a different request.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f35"}}
```
Same key while the first request is still running, `409`:
```json
{"error": {"code": "request_in_progress", "message": "A request with this Idempotency-Key is still being processed.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f36"}}
```
Key required by the endpoint but missing, `400`:
```json
{"error": {"code": "idempotency_key_required", "message": "This endpoint requires an Idempotency-Key header.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f37"}}
```
Key not a UUID (`Idempotency-Key: abc`), `400`:
```json
{"error": {"code": "invalid_idempotency_key", "message": "Idempotency-Key must be a UUID.", "details": [], "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f38"}}
```
A `5xx` outcome is not stored, so retrying with the same key runs the request again (WRT-8). Patterns: WRT-7, WRT-8, TRC-3.

## L. Preconditions

| Request | Result | Rule |
|---|---|---|
| `PATCH` with `If-Match: "a91f"`, current ETag `"a91f"` | `200`, new `ETag: "b02e"` | WRT-9 |
| `PATCH` with `If-Match: "9999"` (stale) | `412` `precondition_failed` | WRT-9 |
| `PATCH` with no `If-Match` on a controlled resource | `428` `precondition_required` | WRT-9 |
| `PATCH` with `If-Match: W/"a91f"` (weak) | `412` | WRT-9 |
| `PATCH` with `If-Match: "9999", "a91f"` | `200`, one ETag matches | WRT-9 |
| `DELETE` with `If-Match: *` on an existing resource | `204` | WRT-9 |
| `PATCH` with `If-Match: a91f` (not quoted) | `400` `malformed_request` | WRT-9 |
| `GET` with `If-None-Match: "a91f"`, unchanged | `304`, no body | WRT-9 |
| `PATCH` with a valid `If-Match` whose values equal the stored state | `200`, no-op, same `ETag` and `updated_at` | WRT-5 |

A `412` returns the standard error envelope. The client refetches (`GET` returns the current `ETag`), reapplies its change and retries.

## M. Bulk

Atomic request:
```json
{
  "mode": "atomic",
  "operations": [
    {"action": "create", "data": {"customer_id": 17, "channel_id": 2, "shipping_address": {"line_1": "Hauptstrasse 12", "line_2": null, "postal_code": "70173", "city": "Stuttgart", "country": "DE"}}},
    {"action": "update", "id": 184, "if_match": "\"a91f\"", "data": {"description": "Dock B"}},
    {"action": "delete", "id": 183, "if_match": "\"77c2\""}
  ]
}
```
Response `200`, one result per operation, in order:
```json
{
  "data": [
    {"index": 0, "id": 190, "status_code": 201},
    {"index": 1, "id": 184, "status_code": 200},
    {"index": 2, "id": 183, "status_code": 204}
  ]
}
```
Invalid atomic request, `422`, nothing applied:
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more operations are invalid.",
    "details": [
      {"field": "operations[0].data.customer_id", "code": "required", "message": "This field is required."},
      {"field": "operations[1].id", "code": "duplicate_operation", "message": "Target 184 appears more than once."},
      {"field": "operations[2].if_match", "code": "invalid_format", "message": "Expected a quoted ETag."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f39"
  }
}
```
More than 100 operations, `422` on `operations` with `max_items`. An empty `operations` list returns `min_items`. `"mode": "partial"` applies each operation independently and returns per-operation results (response standard BLK-2). Patterns: ACB-3..9.

## N. Uploads

Small upload, `POST /api/orders/184/attachments`:
```http
POST /api/orders/184/attachments HTTP/1.1
Authorization: Bearer <token>
Content-Type: multipart/form-data; boundary=----b1f2c3d4
Content-Length: 482611
```
```text
------b1f2c3d4
Content-Disposition: form-data; name="file"; filename="invoice.pdf"
Content-Type: application/pdf

<binary bytes>
------b1f2c3d4
Content-Disposition: form-data; name="description"

Signed invoice
------b1f2c3d4--
```
Response: `201` with the file metadata resource. A client may add `Content-Digest: sha-256=:X48E9qOokqqrvdts8nOJRJN3OWDUoyWxBf7kbu9DBPE=:`, which covers the whole body. A difference returns `422` `checksum_mismatch`.

Large upload, step 1: `POST /api/orders/184/attachments/uploads`
```json
{
  "name": "scan.tiff",
  "content_type": "image/tiff",
  "size_bytes": 734003200,
  "checksum": {"algorithm": "sha256", "value": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"}
}
```
Step 2: the client sends the bytes to the returned upload URL. Step 3: `POST /api/attachments/{id}/actions/complete` with an empty body.

Failures:

| Request | Result | Rule |
|---|---|---|
| Declared `Content-Length` above the limit | `413` before the body is read (or at the first excess byte when chunked) | UPL-2, LIM-2 |
| No `file` part | `422` `required` on `file` | UPL-1 |
| Two `file` parts | `422` `duplicate_values` on `file` | UPL-1 |
| Unknown part `colour` | `422` `unknown_field` on `colour` | UPL-1 |
| Part says `application/pdf`, bytes are an executable | `422` `invalid_file` | UPL-3 |
| Content type not on the allowlist | `415` `unsupported_media_type` | UPL-3 |
| Step 1 with a checksum algorithm `md5` | `422` `invalid_choice` on `checksum.algorithm` | UPL-5 |
| Step 3 and the bytes do not match the declared checksum | `422` `checksum_mismatch` | UPL-4 |
| JSON body with a base64 `content` field | `422` `unknown_field` on `content` | UPL-7 |
| `Range` header on an upload | `400` | UPL-8 |
| `filename="../../etc/passwd"` | accepted as metadata only and stored sanitized, never used as a path | UPL-3, SAF-10 |

## O. Search body: POST /api/orders/search

```json
{
  "filter": {
    "all": [
      {"field": "status", "op": "in", "value": ["confirmed", "shipped"]},
      {"field": "created_at", "op": "gte", "value": "2026-10-01T00:00:00Z"},
      {"field": "customer_id", "op": "eq", "value": 17}
    ]
  },
  "ordering": ["-created_at"],
  "page": 1,
  "page_size": 25
}
```
Response: `200` with the standard list envelope and `meta.pagination`. It creates nothing and needs no `Idempotency-Key`.

Invalid operator, `422`:
```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "filter.all[0].op", "code": "invalid_choice", "message": "Operator 'like' is not supported for 'status'."},
      {"field": "ordering[0]", "code": "invalid_choice", "message": "'colour' is not sortable."}
    ],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f3a"
  }
}
```
Filters never contain raw SQL, regex or free expressions (SAF-5). Patterns: SRC-1..4.

## P. Authentication and request safety

| Request | Result | Rule |
|---|---|---|
| `GET /api/orders?access_token=<token>` | `401`, the query token is never read | QRY-10, AUT-1 |
| Two `Authorization` headers | `400` `malformed_request` | AUT-2, HDR-3 |
| `Authorization` header plus a session cookie | `400` `malformed_request` | AUT-2 |
| Expired or malformed Bearer token | `401` with `WWW-Authenticate: Bearer error="invalid_token"` | AUT-5 |
| Valid token, missing scope | `403` `insufficient_scope` with `WWW-Authenticate: Bearer error="insufficient_scope", scope="orders:write"` | AUT-5 |
| Writing `sales_rep_id` without the manager role | `403` `permission_denied`, `details[].field` `sales_rep_id` | SAF-2 |
| `customer_id` of a customer the caller cannot see | `422` `does_not_exist` on `customer_id`, identical to a missing customer | VAL-6, SAF-1 |
| Body carrying `"tenant_id": 3` | `422` `unknown_field`, tenant comes from the credential | AUT-6 |
| Cookie-authenticated `POST` with no CSRF token | `403` `csrf_failed` | SAF-8 |
| Webhook target `https://10.0.0.5/hook` | `422` `invalid_format`, "URL must resolve to a public address." | SAF-6 |
| Webhook target that redirects to a private address | delivery fails, redirects are not followed | SAF-6 |
| XML or YAML body | `415` | SAF-4 |
| Form post `text/plain` containing JSON | `415` | SAF-3 |

Example, missing scope, `403`:
```json
{
  "error": {
    "code": "insufficient_scope",
    "message": "This action requires the 'orders:write' scope.",
    "details": [],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f3b"
  }
}
```
Logs record `Authorization`, cookies, passwords and personal data as redacted (SAF-9).

## Q. Order of checks: which error wins

| Situation | Status | Step |
|---|---|---|
| Header block over 8 KiB, no token | `431` | 1 |
| `GET /api/ordres` (typo) | `404` | 2 |
| `PUT /api/orders` | `405` | 2 |
| `GET /api/orders/abc`, no token | `404` | 3 |
| No token, invalid JSON body | `401` | 4 |
| Valid token, rate limit hit, invalid body | `429` | 5 |
| Valid token, `Content-Type: text/plain`, invalid body | `415` | 6 |
| Valid token, malformed JSON | `400` | 7 |
| Order 183 not visible to the caller, body with errors | `404` | 8 |
| Scope missing, body with errors | `403` | 8 |
| Visible order, replayed `Idempotency-Key` with a now-stale `If-Match` | original response replayed | 9 |
| Stale `If-Match`, body with errors | `412` | 10 |
| Missing `If-Match` on a controlled resource, body with errors | `428` | 10 |
| Valid `If-Match`, body with errors | `422` | 11 |
| Valid body, duplicate `sku` | `409` `already_exists` | 12 |
| Valid body, disallowed state transition | `409` `invalid_state_transition` | 12 |
| Everything valid | `2xx` | 13 |

Duplicate value, `409`:
```json
{
  "error": {
    "code": "already_exists",
    "message": "A record with this value already exists.",
    "details": [{"field": "sku", "code": "already_exists", "message": "SKU-1042 is already in use."}],
    "request_id": "b1f2c3d4e5f60718293a4b5c6d7e8f3c"
  }
}
```
Patterns: CHK-1..4, VAL-7.

## R. Anti-patterns (the agent MUST flag these)

| Bad | Good | Rule |
|---|---|---|
| `{"data": {"customer_id": 17}}` request body | `{"customer_id": 17}` | BDY-1 |
| `GET` or `DELETE` with a body | no body, parameters in path, query or headers | MTH-1 |
| tunnelling a delete through `POST` with `_method` | `DELETE` | MTH-6, MTH-7 |
| JSON sent as `text/plain` or form-urlencoded | `application/json` | SAF-3 |
| unknown fields silently ignored | `422` `unknown_field` | BDY-6 |
| `id`, `uid`, audit fields or `status` accepted on write | `422` `read_only_field` | BDY-7 |
| echoing a `GET` response straight into `PUT` | build the body from writable fields | BDY-8 |
| `{"customer": {"id": 17, "name": "Acme"}}` on write | `{"customer_id": 17}` | TYP-10 |
| `"status": {"value": "confirmed", "label": "Confirmed"}` on write | `"status": "confirmed"` (where writable) | TYP-6 |
| `"customer_id": "17"` coerced to `17` | `422` `invalid_type` | TYP-1 |
| `"amount": 12.5` or `"1,299.00"` | `"amount": "12.50"` | TYP-3 |
| 3 decimals on a 2-decimal currency, rounded silently | `422` `invalid_precision` | TYP-3 |
| datetime without a timezone stored as server local time | `422` `invalid_format` | TYP-7 |
| lowercase `eur` or `de` corrected silently | `422` `invalid_choice` | TYP-11 |
| over-length string truncated silently | `422` `max_length` | TYP-9 |
| `null` coerced to `""` or `0` | `422` `null_not_allowed` or stored as `null` where nullable | TYP-16 |
| only the first validation error returned | all errors in one response | VAL-2 |
| error `code` changes with the language | codes fixed, messages localized | VAL-4, VAL-9 |
| `403` for an inaccessible relation id | `422` `does_not_exist`, same as a missing id | VAL-6 |
| uniqueness violation as `422` | `409` `already_exists` | VAL-7 |
| `PATCH` that replaces nested objects wholesale | merge patch (arrays replace) | WRT-3 |
| `PUT` that keeps omitted optional fields | omitted optional fields reset | WRT-2 |
| `PUT` creating a record at a client-chosen id | `POST` creates, `PUT` returns `404` | WRT-1 |
| client-supplied `id` on create | server assigns `id` and `uid` | WRT-1 |
| partial write after a `4xx` | all-or-nothing | WRT-7 |
| no-op write that bumps `updated_at` and the `ETag` | unchanged | WRT-5 |
| `Idempotency-Key` missing on a payment `POST` | required, `400` otherwise | WRT-8 |
| replayed key returns a fresh result | original response plus `Idempotency-Replayed: true` | WRT-8 |
| writes on a shared resource without `If-Match` | `ETag` plus `If-Match`, `428` / `412` | WRT-9 |
| `status` changed with a direct `PATCH` | an action such as `.../actions/cancel/` | WRT-11 |
| array body for bulk | `{"mode", "operations": [...]}` | ACB-3 |
| the same target twice in one bulk request | `422` `duplicate_operation` | ACB-6 |
| base64 file inside JSON | `multipart/form-data` or the two-step upload | UPL-7 |
| client filename used as the storage path | generated key, filename kept as metadata | UPL-3, SAF-10 |
| declared file type trusted | sniff and check against the allowlist | UPL-3 |
| complex search through `GET` with a stringified filter | `POST .../search` | SRC-1 |
| token in query string, body or path | `Authorization` header | AUT-1 |
| `tenant_id` or `user_id` in the body overriding the credential | taken from the credential | AUT-6 |
| authorization only on the main object, not on body ids | authorize every id | SAF-1 |
| raw column names accepted in `ordering` or `fields` | allowlist | SAF-5 |
| server fetches any client URL | validated, allowlisted, no redirects | SAF-6 |
| body logged with tokens and personal data | redacted, bodies off by default | SAF-9 |
| limits only on paper, not enforced while streaming | enforced during read | LIM-2 |
| rejecting a request because `X-Request-ID` has a bad format | replace it and continue | TRC-1 |
| tighter validation shipped without notice | breaking change, needs a migration plan | CMP-2 |
