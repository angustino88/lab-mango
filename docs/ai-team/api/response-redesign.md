# Repository-wide API response audit and redesign

**Date:** 2026-10-16 · **Role:** API Designer · **Tier:** T2
**Status:** design delivered; notification POST envelope migration implemented in the working tree; repository-wide runtime migration remains incomplete and is not merge/release approved.

## Approved client migration: notification creation

The notification endpoint's `POST /api/notifications` success body changes from the
bare notification object to `{"data": <notification>}`. HTTP `201 Created`, the
notification fields within `data`, request body, and error responses remain unchanged.
This is a breaking response-shape change approved by the API owner for implementation.

Clients consuming the created notification must unwrap `data` before reading resource
fields (for example, read the created identifier from `response.data.data.id` when the
HTTP client exposes the response body as `response.data`). Do not change the request
payload or treat `data` as an HTTP-client-specific wrapper beyond the API response body.
The generated OpenAPI contract is the source for the exact response fields. Update and
release all notification API consumers in coordination with the backend contract change.

## Task brief

### Outcome

Replace inconsistent application API responses with the shapes in
[response-standard.md](response-standard.md) and [response-golden-examples.md](response-golden-examples.md).
The user's request explicitly permits breaking response changes. It does not authorize
deployment, changing permissions, or applying migrations to an existing database.

### Acceptance criteria


### Non-goals

No production access, payload collection, migrations, deployment, permission changes,
new dependencies, booking workflow changes, or rewriting unrelated in-progress work.
This document does not claim full runtime compliance or independent review.

## 1. Evidence and coverage

The committed/generated OpenAPI modules describe **95 paths, 181 operations, and 353
component schemas**. Counting component properties found **73 schemas with `id`**,
**19 with `created` or `modified`**, and **15 with a relation plus its sibling
`*_name`**. These include request/lookup schemas; they are structural audit signals,
not 73 independently confirmed primary-resource leaks.

| Published module | Paths | Operations | Audit/redesign scope |
| --- | ---: | ---: | --- |
| features-schema | 1 | 1 | Protocol document; explicit envelope exception |
| jira-issues | 1 | 1 | Upstream projection, bounded pagination, typed issue output |
| jira-requests | 6 | 8 | CRUD and every generated-URL/status action |
| jira-service-info | 1 | 1 | Single service descriptor |
| labs-bench-bookings | 2 | 3 | Create, detail, partial update |
| labs-benches | 10 | 21 | Benches, placement, favorites, selections, groups/types/lookups |
| labs-equipment | 41 | 91 | Generic and generated category endpoints, assignments/status/lookups |
| labs-licenses | 5 | 7 | Inventory, assignments, status records, agreements |
| labs-locations | 17 | 33 | Rooms/stations/types, placement, slots, generation, histories/observations |
| users-auth-aad-login | 1 | 1 | AAD login protocol |
| users-auth-login | 1 | 1 | Login protocol |
| users-auth-logout | 1 | 1 | Logout protocol |
| users-auth-refresh-token | 1 | 1 | Refresh protocol |
| users-auth-send-otp | 1 | 1 | OTP acknowledgement |
| users-groups-list-groups | 1 | 1 | Replace unbounded group/member map |
| users-profile-avatar | 1 | 3 | Avatar read/update/delete |
| users-profile-get-me | 1 | 1 | Current user's profile and permission projection |
| users-profile-list-users | 2 | 3 | User list/detail/update |
| websocket-list-notifications | 1 | 2 | REST list/create only; websocket protocol remains separate |

Source inspection also found:

- Booking-by-code and equipment-by-SKU/by-UUID routes added in the working tree that
  are absent from the published path index. Regeneration must inventory actual routes.
- Procurement HTTP adapters exist, but `core/labs/api_urls.py` does not include them.
  Treat them as dormant contracts; do not publish them as an incidental response change.
- `core/labs/features_old_do_not_edit_only_ref/` is reference-only, not migration scope.
- A substantial dirty working tree includes booking/equipment/model/documentation edits.
  No existing file was overwritten for this audit.

### Confirmed high-priority findings

| Severity | Finding and evidence | Required redesign |
| --- | --- | --- |
| High | Conflicting error guidance: standard requires `error`, 422, request ID; package emits top-level RFC 9457, optional code/errors and no request ID. [Package response construction](../../../packages/drf-api-contracts/src/drf_api_contracts/responses.py#L326) | Shared error contract and schema; central exception mapping |
| High | Three incompatible collection shapes; optional pagination and no explicit maximum in the shared paginator. [Shared paginator](../../../core/common/api/pagination.py#L7), [list boundary](../../../core/common/api/api_views.py#L187) | One mandatory bounded page-number contract |
| High | Jira CRUD/actions return raw serializer bodies and ad hoc validation errors. [Jira actions](../../../core/jira_integration/features/requests/manage_requests/api.py#L73) | Operation contracts for every action, identical envelope/error handling |
| High | Primary-resource IDs and bare relations are exposed across feature serializers. [Booking fields](../../../core/labs/features/bench_bookings/api/serializers.py#L41), [bench fields](../../../core/labs/features/benches/api/serializers.py#L97) | UUID-only public addressing and nested relation projections |
| High | Dynamic equipment category generation adds relation-name siblings and unconditional `deleted_at`. [Category generation](../../../core/labs/features/equipment/api/categories.py#L78) | Explicit nested category projections; no default deletion marker |
| High | License output splits relations and acquisition fields; agreement uses one read/write serializer. [License serializers](../../../core/labs/features/licenses/api/serializers.py#L6) | Separate read/write projections, relation objects and money object |
| Medium | Equipment expand phase retains old and grouped fields simultaneously; acquisition uses `price` rather than `amount`. [Equipment projection](../../../core/labs/features/equipment/api/serializers.py#L36) | Clean redesigned projection without compatibility aliases |
| Medium | Rooms/stations use raw statuses, legacy audit names, and shared list/detail fields; stations inline all slots. [Room projection](../../../core/labs/features/locations/rooms/api/serializers.py#L100), [station projection](../../../core/labs/features/locations/stations/api/serializers.py#L135) | Grouped summaries, enum objects, audited detail, bounded slot sub-resources |
| Medium | User read serializer has a write-only upload field; avatar representation reintroduces a second alias. [Profile serializers](../../../core/users/features/profile/serializers.py#L26) | Dedicated upload requests; read output has one `avatar_url` |
| Medium | Group output is an unbounded dynamic name-to-usernames map. [Group endpoint](../../../core/users/features/groups/list_groups/api.py#L15) | Paginated groups, member count and bounded membership sub-resource |
| Medium | Notifications use default DRF create output and a distinct list envelope. [Notification boundary](../../../core/websocket/features/list_notifications/api.py#L13) | Explicit REST operation contracts and pagination; retain caller scope |
| Medium | Jira search exposes `startAt`/`maxResults` and untyped upstream issue dictionaries. [Jira projection](../../../core/jira_integration/features/issues/list_issues/api.py#L27) | Local allowlisted snake_case projection; do not pass arbitrary upstream fields |
| Medium | Generated equipment category POST advertises/returns 200 and the list projection. [Category list/create base](../../../core/labs/features/equipment/api/list_create.py#L78) | 201, Location and full detail projection |

Security findings are exposure/design risks, not proof of unauthorized access. Object
authorization, hidden-resource behavior, field visibility, rate limits, request
correlation, and query counts need dedicated tests; they cannot be certified from schema.

## 2. Resolve standards before implementation

The user-selected response standard and golden examples are the target for the redesigned API:

- JSON success: `data`, optionally `meta` for single objects.
- JSON errors: `error` with mandatory `code`, `message`, `details`, `request_id`.
- Semantic request validation: 422. Malformed bodies and invalid query controls: 400.
- Page-number collections: `data` array plus `meta.pagination`.

The older API instructions, runtime guide, earlier additive design, and Spectral rules
still describe RFC 9457/400/legacy pagination. Amend them together during implementation.
Do not label the nested golden error body RFC 9457 or serve it as
`application/problem+json`. Use `application/json` for application errors.

**Explicit decisions required:**

1. SEC-1 cannot literally apply to login/refresh endpoints: retain their existing public
   authentication/bootstrap behavior and document `security: []` exceptions.
2. SEC-4's token prohibition needs an explicit authentication-protocol exception. Do not
   remove required authentication outputs or expose them in ordinary resource responses.
   Use only synthetic values in examples; never log token/request credential values.
3. OpenAPI documents, downloads, HEAD, streaming and 204 are protocol exceptions to the
   JSON-body rules. Do not wrap a schema document or file in `data`.
4. Retain 405/406/415 for HTTP/protocol failures and 412 for failed preconditions;
   502/503 for upstream/service failure. The standard's status list is not exhaustive.
5. NUL-3 applies within each documented projection. List and detail may have different
   required fields; permission-restricted fields follow SEC-2, not unconditional presence.
6. Unset scalar text is null; a meaningful empty text value is not automatically unknown.
   Arbitrary metadata is not recursively rewritten.

No cursor pagination or new expansion syntax is introduced. Page-number pagination
matches the golden example and avoids competing collection formats.

## 3. Shared API schemas

### Success and collection

Single-resource body: `{"data": <Detail>}`. List body:

```json
{
  "data": [],
  "meta": {
    "pagination": {
      "count": 0,
      "page": 1,
      "page_size": 25,
      "next": null,
      "previous": null
    }
  }
}
```

Proposed default page size **25**, maximum **100**. Every list/sub-resource is bounded,
even without `page`. Reject page sizes outside 1..100 with 400 `invalid_filter`;
do not silently ignore or silently clamp query controls. Page 1 of an empty collection
returns the example above. A nonexistent requested page returns documented 404.
`next`/`previous` are relative URLs under `/api/` preserving validated filters.

Query controls: `page`, `page_size`, `q`, `ordering`, plus endpoint-specific allowlists.
Unknown query keys/ordering fields return 400 `invalid_filter`. Explicitly separate
pagination controls from domain-filter serializer fields. Add UUID as final ordering
tiebreaker where applicable. Document each permitted ordering field; do not let generic
filter backends silently discard invalid ordering.

### Errors

```json
{
  "error": {
    "code": "validation_failed",
    "message": "One or more fields are invalid.",
    "details": [
      {"field": "bench_uid", "code": "required", "message": "This field is required."}
    ],
    "request_id": "synthetic-request-id"
  }
}
```

All fields above are required. `details` is always an array; empty is `[]`.
Flatten nested DRF validation paths, including list indices, deterministically; retain
individual error codes rather than stringify a nested error dictionary. Non-field
errors use `field: null` in their documented detail schema.
Generate a correlation identifier for every request; include it on every error and in
an `X-Request-ID` response header. Only accept a bounded, validated incoming identifier,
otherwise generate one. Never put request credentials or arbitrary input in identifiers.
Use safe fixed messages for unexpected errors and hidden resources.

| Status | Public code | Usage |
| --- | --- | --- |
| 400 | malformed_request | Invalid JSON/body syntax |
| 400 | invalid_filter | Unknown/invalid pagination, filter, ordering or search control |
| 401 | unauthenticated | Authentication required or failed; retain required challenge headers |
| 403 | permission_denied | Visible action is forbidden |
| 404 | not_found | Missing or hidden resource |
| 409 | conflict / existing verified domain code | Uniqueness, overlapping booking or assignment conflict |
| 409 | invalid_state_transition | Verified domain transition cannot be performed |
| 412 | precondition_failed | Stale `If-Match` |
| 422 | validation_failed | Syntactically valid body fails semantic/field validation |
| 429 | rate_limited | Include `Retry-After` |
| 500 | internal_error | Unexpected safe failure |
| 502 | upstream_failure | Upstream operation failed |
| 503 | service_unavailable | Temporarily unavailable service |

These generic codes are proposed; first inventory released domain codes and map them
explicitly. Never lowercase/change existing codes heuristically. Document protocol
errors separately using the same envelope.

### Reusable resource fields

- Public `uid`: stored random UUID, not derived from PK or generated during serialization.
- Named relation: `{uid, name}` or null; taxonomy relation also carries a stored stable
  `code`. UUID remains its identity, code is its machine-branching value.
- Enum: `{value, label}` with verified model choices, never fabricated labels/values.
- Money: `{amount: <decimal string>, currency: <ISO 4217>}` or null. Reject/write-validate
  incomplete pairs; do not invent a currency for historical records.
- Audit: `created_at`, `updated_at`, `created_by`, `updated_by`; map existing
  `created`/`modified`/`creator`/`last_modified_by` where present.
- Output timestamps normalize to UTC `Z`, even if storage/input has another offset.
- Structured groups are null when wholly absent. Metadata is an object and collections
  are arrays; scalar unknown values are null. Preserve genuine zero and false.
- Required/readOnly lists in OpenAPI must reflect actual serialized output, not merely
  `required=False` on fields that serializers might omit.

Do not add dummy audit times/actors to models that lack them. UUID/code/audit gaps
require explicitly designed schema/backfill work or a documented approved exception.

## 4. Endpoint replacement table

All paths below are proposed redesigned contracts, not existing routes. A category path
means each verified category in the runtime registry, not invented category values.
Every secured row retains existing credential mechanisms and object scope; this design
does not broaden access. All bodies use section 3 and all errors carry correlation.

| Method(s) | Proposed path | Request / response | Permissions and special behavior |
| --- | --- | --- | --- |
| GET, POST | `/api/labs/equipment/` | Bounded EquipmentSummary / EquipmentCreate → EquipmentDetail | Existing equipment scope; POST 201 + Location |
| GET | `/api/labs/equipment/{uid}/` | EquipmentDetail | Existing object scope; missing/hidden 404 |
| GET, POST | `/api/labs/equipment/{category}/` | Bounded category summary / distinct create → category detail | Same registry capabilities; POST 201 |
| GET, PUT, PATCH, DELETE | `/api/labs/equipment/{category}/{uid}/` | Distinct replace/patch → full category detail; DELETE 204 | Retain only methods actually exposed by each category; no automatic method expansion |
| POST, DELETE | `/api/labs/equipment/{uid}/assignment/` | `bench_uid`, existing role/position → assignment detail; release 204 | Idempotency-Key on retry-prone create; preserve existing assignment rules |
| POST | `/api/labs/equipment/{uid}/status/` | Verified status value + typed metadata → status-record detail | Preserve transition semantics; no arbitrary status writes elsewhere |
| GET | `/api/labs/equipment/reference-data/`, category equivalent | Bounded taxonomy references, counts and links for large lookups | Replace unbounded owner/reference lists with bounded sub-resources |
| GET, POST | `/api/labs/benches/` | BenchSummary / BenchCreate → BenchDetail | Existing authenticated/scoped bench rules |
| GET, PUT, PATCH, DELETE | `/api/labs/benches/{uid}/` | BenchDetail / distinct writes → full detail; delete 204 | ETag/If-Match for contested updates |
| PATCH | `/api/labs/benches/{uid}/place/` | `setup_location_uid`, `station_slot_uid` → full BenchDetail | Existing locked placement checks; stale precondition 412 |
| POST, DELETE | `/api/labs/benches/{uid}/favorite/` | No client-selected actor → favorite detail; delete 204 | Caller-owned favorite; document repeat semantics |
| GET | `/api/labs/benches/options` | Bounded `CatalogOptionList` (OPT-1 to OPT-13) | Same filters/scope as bench list; see ADR 002 |
| GET, POST; GET, PATCH, DELETE | `/api/labs/bench-groups/`, `/bench-types/`, detail `{uid}/` | Taxonomy list/detail / separate write → detail; retirement 204 | Existing administrative checks; stable stored code |
| GET | `/api/labs/benches/reference-data/` | Small typed descriptor + links to bounded lookups | No unbounded embedded station/group lists |
| POST | `/api/labs/bench-bookings/` | `bench_uid`, `project_uid`, starts/ends/reason → BookingDetail | 201 + Location; Idempotency-Key; preserve booking constraints |
| GET, PATCH | `/api/labs/bench-bookings/{uid}/` | BookingDetail / editable fields → full detail | Preserve actual state machine; contested write precondition |
| GET | Booking/equipment business-key lookup routes, only if retained | Resolve code/SKU to UUID-addressed detail | Preserve currently added routes; no code-to-PK substitution |
| GET; GET | `/api/labs/licenses/`, `/{uid}/` | LicenseSummary / LicenseDetail | Existing field/object visibility; bounded list |
| POST, DELETE | `/api/labs/licenses/{uid}/equipment/{equipment_uid}/assignment/` | AssignmentDetail; release 204 | Idempotency-Key; existing assignment constraints |
| POST | `/api/labs/licenses/{uid}/status/` | Verified status + typed metadata → status record | Existing lifecycle; 201 and record Location when addressable |
| GET, POST | `/api/labs/licenses/{uid}/agreements/` | Bounded AgreementSummary / AgreementCreate → AgreementDetail | Distinct serializers; money visibility; 201 + Location |
| GET, POST; GET, PUT, PATCH, DELETE | `/api/labs/rooms/`, `/{uid}/` | RoomSummary/Detail with distinct create/replace/patch | Existing scope; 201/200/204; preserve layout checks |
| GET; POST | `/api/labs/rooms/{uid}/slots/`, `/slots/generate/` | Bounded RoomSlot / bounded generation result or accepted job | Keep synchronous 200 if bounded; 202 only with implemented job/status resource |
| POST; GET | `/api/labs/rooms/{uid}/status/`, `/history/` | Typed status write → record / bounded status history | Audit is work-item history, not associate activity reporting |
| GET, POST | `/api/labs/rooms/{uid}/observations/` | Bounded Observation / separate observation write → detail | Existing source/measurement rules |
| GET, POST; GET, PUT, PATCH, DELETE | `/api/labs/stations/`, `/{uid}/` | StationSummary/Detail with separate writes | Same scope and locked capacity rules |
| PATCH | `/api/labs/stations/{uid}/place/` | `room_uid`, `slot_uid`, existing position/orientation → detail | Coordinate units explicit; If-Match |
| GET, POST; GET, PUT, PATCH, DELETE | `/api/labs/stations/{uid}/slots/`, `/{slot_uid}/` | Bounded slot list/detail; distinct writes | Parent-scoped lookup; no cross-station slot addressing |
| POST; GET | `/api/labs/stations/{uid}/status/`, `/history/` | Status record / bounded history | Existing status transitions |
| GET; GET, POST; GET, PATCH, DELETE | Station reference-data and `/api/labs/station-types/`, `/{uid}/` | Typed descriptor; bounded taxonomy CRUD | No arbitrary taxonomy name-derived codes |
| GET, POST; GET, PATCH | `/api/jira/requests/`, `/{uid}/` | RequestSummary/Detail / create and editable-field patch | Retain reporter/admin/coordinator scope; separate writes |
| GET | `/api/jira/requests/{uid}/generate-url/` | `{request: {uid, name}, jira_url, summary}` | Verify URL generation is read-only; otherwise change to POST |
| POST | `/api/jira/requests/{uid}/mark-created/`, `/mark-failed/` | Explicit bounded action fields → full request detail | Retain admin/coordinator checks; no upstream internals in errors |
| PATCH | `/api/jira/requests/{uid}/update-status/` | Verified transition request → full detail | Replace arbitrary status values only after domain transition review |
| GET | `/api/jira/jira-issues/` | Bounded typed IssueSummary; metadata for create/base links | Existing authentication; local page mapping to bounded upstream offsets |
| GET | `/api/jira/service/` | Verified service descriptor | Existing authentication |
| POST | `/api/login/`, `/aad-login/`, `/refresh-token/` | Existing protocol input/output semantics with standard envelope | Explicit bootstrap exceptions; no credential logging |
| POST | `/api/logout/`, `/send-otp/` | Typed acknowledgement / existing bounded OTP request | Retain existing permissions and cookie/token lifecycle |
| GET; GET, PATCH | `/api/users/`, `/{uid}/` | Bounded UserSummary / UserDetail; distinct profile patch | Existing scope; no extra personal fields |
| GET | `/api/users/me/` | CurrentUserDetail with typed group/permission projection | Existing caller identity; no permissions writes |
| GET, POST, DELETE | `/api/users/avatar/` | `{avatar_url}` / dedicated upload → same output; delete 204 | Preserve existing POST upload and size/type checks |
| GET | `/api/user-groups/` | Bounded group summaries; member counts and sub-resource links | Preserve existing audience; paginate membership separately |
| GET, POST | `/api/notifications/` | Bounded NotificationSummary / distinct create → NotificationDetail | Preserve target-user scope; review existing create permission without broadening it |
| GET | Existing schema download route or explicit redesigned schema route | Raw OpenAPI document, not success envelope | Preserve schema protocol; separate API-document auth decision |

CRUD defaults: create 201 + Location, read/update 200 with the documented projection,
delete 204 without body. No client-supplied audit/UID/computed values. Read-only and
unknown write fields are explicitly rejected with 422.
Actions retain their actual domain result rather than pretending every action creates
a primary resource. All action response/status choices must match executed behavior.

## 5. Resource-specific projection map

| Resource | Summary/detail redesign and verified source mapping |
| --- | --- |
| Equipment | Keep uid/sku/name and verified category fields; `classification` holds category/kind/type; manufacturer/product_model/owner are references; `description ← details`; status object uses latest status projection; `acquisition` is money or null; audit names mapped. Remove id, flat classification duplicates, current_status aliases, flat acquisition aliases and unconditional deleted_at. |
| Category equipment | Explicit subtype fields from category declarations; FK/M2M values become typed references, not raw IDs plus `_name`. Heavy category properties belong only in detail or bounded sub-resources. Review each type, unit and empty representation individually. |
| Bench | Named group/owner/type/bench_group references; placement groups setup_location/station_slot references; lifecycle_status is enum; explicit capacity/unit fields retained; equipment_count + equipment URL replace inline assignments; dedicated list/detail/read/write classes. Resolve remark versus description meaning rather than concatenate/discard content. |
| Booking | Add stored UUID; retain booking_code as human/business key. Bench/project are references. Status and approval_status remain separate enum objects. Preserve starts_at/ends_at/reason; add mapped audit fields. Do not invent resource-lifecycle or live-activity statuses. |
| License | Nested product/vendor/type/category/restriction/owner; lifecycle enum; money acquisition or null; expiry_date retained; audit fields mapped. Remove sibling `_name`, raw IDs and flat acquisition duplicates. |
| Agreement / assignment / status record | Own UUID where independently addressable; parent/assigned resources are references; verified billing/status enums; price+currency become money; audit timestamps mapped. Null valid-until/unassigned-at remains null. |
| Room | Address groups country/city/building/floor; existing dimensions/capacities have explicit units. Operational status and latest recorded status stay distinct. Summary excludes large utility/history/observation payloads; slot count/link rather than full collections; no default deleted_at. |
| Station | Placement groups room/slot/position/orientation. Type is reference; operational and recorded statuses stay distinct; capacity values preserve zero/unknown; count+URL replace bench_slots; audit and nullable groups explicit. |
| Room/station slot | Parent is reference; stored UUID for independently addressed slot; verified slot-type/status enums; utilities object; boolean names use is_/has_; dimensions retain explicit units. |
| User/profile | Stored user UUID required; retain only existing necessary username/display_name/avatar_url. User relation display maps to verified display_name/name fallback, never fabricated from PK. Separate upload/write serializers. Permission/group references need stable identity/code strategy. |
| Jira request | Stored UUID; configuration/reporter/creator nested; status object replaces status_display; created_at/updated_at/audit mapped; unset issue links/error text null. Summary omits heavy description and technical upstream failures. |
| Jira issue | Do not invent a UUID for a third-party issue. Use verified upstream stable identity/key and explicitly approve REL-1 exception, or persist a local UUID mapping. Inspect actual upstream DTO before enumerating issue fields. |
| Notification | Stored UUID; message_type enum; timestamp expiry must use `_at` if actual model field is datetime; target_user is scoped reference or omitted when unnecessary; audit mapped; extension details require an explicitly typed group or metadata mapping. |
| Taxonomies | Persist stable UUID/code; keep name; use is_active; bound lookup lists. Do not slugify mutable names at serialization time. |
| Dormant procurement | Separate purchase/item/resource-allocation/transaction read/write serializers; UUIDs, reference objects, amount+currency objects, independent transaction enums and audit. Publish only in a separate authorized routing change. |

Relation expansion must be backed by feature-owned projections with eager loading.
No universal serializer rewrites every model/metadata field heuristically. Technical
`core.common` transport code must not import Labs/Users/Jira feature rules.

## 6. Breaking-change implementation plan

**Classification: breaking.** Envelopes, pagination, error status/media/code changes,
UUID addressing, relation types, enum types, renamed fields, nullability changes,
read/write separation, strict filtering and removed aliases all affect clients.

1. Approve the redesigned contract and explicit exceptions above; expose it at
  `/api/` as the single API route prefix.
2. Inventory actual registered methods, response serializers and every released code.
  Refresh the published inventory to include working-tree routes before computing the diff.
3. Data Architect designs stored UUID/code additions and historical money/audit policies.
   Use expand → independently generated per-row UUID backfill → uniqueness/not-null
   validation. Preserve DB PKs/FKs; never rewrite historical PKs or run destructive reset.
4. Implement the shared transport and schema contracts, replacing the legacy envelope,
  error, and pagination behavior across the API.
5. Migrate feature-owned projections and route UUIDs through existing scoped commands.
   Keep authorization and locked concurrency checks at the actual mutation boundary.
6. Add idempotency persistence/replay and preconditions only with explicit design/tests:
   actor+operation scope, payload fingerprint, expiry, mismatch 409, race-safe replay,
   atomic precondition check within the command. Missing header policy needs approval.
7. Generate OpenAPI from code; validate/diff, run contract/security/query-count tests;
   frontend owner adopts exact schemas, not examples alone.
8. Remove legacy route and contract assumptions from code, tests, documentation, and
  schema generation. Human approves merge/release.

Changing only the route prefix is not implementation: response projections and shared
transport must meet the contract. Do not rewrite JSON in global middleware; preserve
204, files, schemas, streams, authentication protocol behavior and response headers.

## 7. OpenAPI diff expectations

**Published schema has not been modified in this design-only change.** Implementation
must regenerate module schemas and components from code, not hand-edit generated YAML.

Expected redesign diff:

- All published API paths move under `/api/...` with UUID parameter format.
- Named Success/Collection/ErrorEnvelope/FieldError/NamedReference/TaxonomyReference/
  EnumValue/Money/Pagination components, with required fields and explicit nullable types.
- One collection schema per operation, no plain-list/paginated `oneOf`.
- Separate Summary/Detail/Create/Replace/Patch/ActionRequest schemas for each feature.
- Errors use application/json and required nested error fields; semantic failures 422;
  malformed/filter failures 400; auth/conflict/throttle/protocol/upstream failures explicit.
- All operation summaries, auth, examples, filter/ordering allowlists, headers, paging
  bounds, idempotency and precondition behavior documented.
- Read-only audit/UID/computed fields; no response-only fields in request schemas.
- 201 Location, 204 without content, 429 Retry-After, request-ID headers documented.
- Large inline relations removed; counts and real routable links replace them.
- Examples validated against schema; synthetic data only.

Spectral rules need golden envelope/error checks, 422 support and correct rule IDs.
Current rules mention nonexistent ERR-6 and assign status rules to ERR-4 (actually
correlation). Do not weaken current gates or claim RFC output passes golden rules.

## 8. Rule-ID review

Status is current implementation evidence, not intended redesigned-contract compliance.
`violation (unverified)` means no proof of compliance was established, not a confirmed
runtime failure. Inapplicable rules/exceptions are explicitly marked in the Fix column.

| Rule ID | Status (pass/violation) | Fix / evidence limit |
| --- | --- | --- |
| ENV-1 | violation | Raw application bodies and protocol exceptions need separation |
| ENV-2 | violation | Standardize all action/list/create success envelopes |
| ENV-3 | violation | Replace top-level RFC/ad hoc error bodies |
| ENV-4 | violation (unverified) | Test every empty list and missing/hidden detail |
| ENV-5 | violation | Avatar/category legacy deletes need no-body 204; several explicit command deletes already comply |
| ERR-1 | violation | Golden nested error schema and field-detail array |
| ERR-2 | violation | Generic/system codes not consistently stable snake_case; explicit versioned registry |
| ERR-3 | violation | Separate semantic 422 from malformed/query 400; document protocol exceptions |
| ERR-4 | violation | Required request correlation at every failure path |
| ERR-5 | violation (unverified) | Negative/security tests, safe unexpected errors and hidden-resource 404 |
| REL-1 | violation | Many models lack UUID; third-party identity exception needs approval |
| REL-2 | violation | Remove primary DB IDs from schemas/paths |
| REL-3 | violation | Replace bare relations with typed references |
| REL-4 | violation | Remove generated and handwritten relation-name siblings |
| REL-5 | violation | Persist stable taxonomy codes; no mutable-name derivation |
| REL-6 | violation | Slots/equipment/group membership to bounded sub-resources |
| FMT-1 | violation (unverified) | Verify UTC Z, dates and duration conventions on actual fields |
| FMT-2 | violation | Several money values are split; use amount/currency group |
| FMT-3 | pass | Inspected BooleanFields serialize booleans; metadata excluded from blanket transformation |
| FMT-4 | violation (unverified) | Test large counters/byte values; serialize above safe integer as string |
| FMT-5 | violation (unverified) | Schema and runtime tests for every populated/absent state |
| FMT-6 | violation (unverified) | Existing physical unit fields are explicit; review all category/position/duration fields |
| NUL-1 | violation | Blank/unset text and relation semantics require explicit field mapping |
| NUL-2 | violation (unverified) | Assert collections never null, metadata always object |
| NUL-3 | violation | Serializer read_only/source fields can disappear; explicit required projection fields |
| NUL-4 | violation | Incomplete money/group source data requires backfill or approved null policy |
| NAM-1 | violation | Jira camelCase and inconsistent naming |
| NAM-2 | violation | monitor/active/favorite output names need contextual boolean prefixes |
| NAM-3 | violation | Legacy created/modified and timestamp-expiry names |
| NAM-4 | violation | details/remark/notes/description semantics need domain mapping, not blind rename |
| NAM-5 | violation (unverified) | Review category abbreviations; retain verified industry terms |
| ENU-1 | violation | Most statuses/types still serialize raw choice values |
| ENU-2 | violation (unverified) | Document extensibility and frontend unknown-value handling |
| ENU-3 | violation | Dict/JSON status metadata needs verified per-status schema |
| STR-1 | violation | Group classification/acquisition/address/placement by domain |
| STR-2 | violation | Map audit fields; missing model audit is schema work or approved exception |
| STR-3 | violation | Remove unconditional deletion marker from ordinary projections |
| STR-4 | violation | Split list/detail and exclude heavy category/slot/member data |
| STR-5 | violation (unverified) | Define typed groups versus single extension metadata object |
| COL-1 | violation | Mandatory paging with explicit 25/100 proposal |
| COL-2 | violation | One data-array/meta.pagination shape |
| COL-3 | violation | Normalize q/ordering and explicit domain query allowlists |
| COL-4 | violation | Reject unknown query/ordering fields rather than silently ignore |
| COL-5 | violation | Add stored UUID deterministic tiebreakers |
| RW-1 | violation | Separate agreement/profile/Jira/dormant procurement writes from reads |
| RW-2 | violation | Public relation_uid input mapped through scoped feature adapters |
| RW-3 | violation | Explicitly reject read-only/unknown input; readOnly schema flags |
| RW-4 | violation | Category creates 201+Location+detail; verify GET actions and replacement semantics |
| RW-5 | violation (unverified) | No idempotency guarantee established; design race-safe scoped replay |
| RW-6 | violation (unverified) | Measure long-running actions; 202 only with actual status resource |
| SEC-1 | violation (unverified) | Preserve/test every object scope; document bootstrap exceptions |
| SEC-2 | violation (unverified) | Role-sensitive projection tests without changing permissions |
| SEC-3 | violation (unverified) | Verify media URL/download authorization, not just URL formatting |
| SEC-4 | violation (exception decision) | Ordinary responses omit secrets; auth protocol exception required |
| SEC-5 | violation (unverified) | Bound all input/paging/nesting; verify existing throttles |
| SEC-6 | violation (unverified) | Several serializers are explicit, but test every write/action allowlist |
| VER-1 | violation | Redesigned contract is not yet implemented consistently at `/api/` |
| VER-2 | pass | Prior equipment grouped fields are additive aliases, not completed redesign |
| VER-3 | violation (unverified) | Owner-approved release window, deprecated schema and retirement headers |
| PRF-1 | violation (unverified) | Add eager-loading to feature-owned nested projections |
| PRF-2 | violation (unverified) | Assert list/detail query budgets after projection migration |
| PRF-3 | violation (unverified) | Define caching validators for safe/cacheable scoped reads |
| PRF-4 | pass | Optional: do not introduce fields/expand partially |
| DOC-1 | violation | Published inventory lags working-tree routes; redesigned schema not generated yet |
| DOC-2 | violation | Missing summaries/error/auth examples; full per-operation schema required |
| DOC-3 | violation (unverified) | Validate golden/feature examples against actual generated schemas |

## 9. Required contract tests and implementation work packages

| Package / proposed owner | Acceptance evidence |
| --- | --- |
| Standards reconciliation / API Designer | Golden envelope/error/media/status agreement; documented protocol exceptions; version plan approved |
| Shared HTTP contracts / Backend Engineer + QA | Exact error and page schemas; raw DRF/parser/auth/404/405/415/429/500 paths; headers preserved; no double wrap; 204/HEAD/files/schema unaffected |
| Stored identities and reference codes / Data Architect | Every existing row gets a unique stable UUID; code stability; expand/backfill constraints; old PK/FK behavior unchanged |
| Feature batches / Backend Engineer | Equipment → benches/locations → bookings/licenses → Jira/users/notifications; each batch has populated/null/list/detail/write/action tests and schema diff |
| Concurrency/idempotency / domain specialist + QA | Same key same payload replay; different payload 409; actor isolation; simultaneous requests; preconditions checked atomically; PostgreSQL domain invariants preserved |
| Security review / Security Engineer | Hidden/missing 404 equivalence; cross-object access denied; restricted fields/files; caller-owned groups/favorites/notifications; synthetic examples; no credentials in logs/errors |
| OpenAPI and examples / API Designer + QA | Every registered operation inventoried; runtime response validates against schema; golden examples validate; Spectral passes updated rules |
| Independent review / Independent Code Reviewer | Review brief+diff without author's claims; run its own checks; human owner approves T2 merge/release |

Minimum per operation: success/body/status/header, semantic invalid write, malformed
body, read-only/unknown field, unauthenticated, forbidden/hidden, missing object,
empty collection, page bounds/invalid filters, deterministic ordering, populated and
absent relations, enum unknown-value client handling, audit/UTC/money types, query
budget and declared OpenAPI examples. Only applicable cases should be claimed.

## 10. Handoff and verification

### Commands executed

- `git status --short`: observed substantial pre-existing changes; preserved them.
- Read-only Python/PyYAML module inventory: passed; 95 indexed paths, 181 module
  operations, 353 schemas; structural counts recorded above.
- `npx --no-install @stoplight/spectral-cli lint openapi/openapi.yml --ruleset .spectral.yaml --format stylish`:
  **failed to start linting**, exit 1; Spectral CLI is not locally available. No lint
  findings or passing result exist. No package was installed.

### Not run

Runtime API tests, migrations, schema generation/diff, Ruff, static types, query-count
tests, deployment checks and independent/security/QA review: not run for this design-only
change. Spectral lint itself was not run because its executable was unavailable.
OpenAPI was not updated. No runtime endpoint has been migrated by this document.

### Evidence ledger

| Acceptance criterion | Artifact/evidence | Result |
| --- | --- | --- |
| Published module inventory | Section 1; read-only YAML inventory | Passed for published schema; runtime route refresh remains required |
| Rule-ID review | Sections 1 and 8 with source evidence and unverified markers | Delivered; not runtime-certified |
| Replacement schemas/endpoints | Sections 3–5 | Proposed design; exact feature field schemas remain implementation work |
| Breaking implementation plan | Section 6 | Delivered; owner approval for detailed decisions pending |
| OpenAPI/tests requirements | Sections 7–9 | Delivered; schema/tests not changed/run |
| Preserve existing work | New document only; no existing-file modifications | Passed for this design change |

### Owner decisions / remaining questions

- Approve error-policy reconciliation, authentication/schema/protocol exceptions and
  25/100 paging bounds; set deprecation release/date only when known.
- Approve stored UUID/code migrations and policy for historical incomplete money/audit.
- Define concurrency missing-header policy and idempotency scope/expiry per operation.
- Resolve ambiguous description/remark/notes meanings, third-party issue identity,
  notification expiry type and exact upstream issue fields with domain owners.
- Authorize implementation batches and arrange independent/security/QA review; no
  separate-agent delegation facility was available in this session.
