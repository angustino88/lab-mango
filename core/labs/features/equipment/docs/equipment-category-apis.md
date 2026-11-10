# Equipment category APIs and feature-base boundaries

## Scope, status and authority

Status: current source-level category API compatibility reference with transitional
implementation details, not a reusable target feature template or runtime
certification. Scope: category routes, fields, response compatibility and existing
API-base hooks. The [Feature Template Specification](../../../../../docs/architecture/feature-template.md) owns
layout, layer boundaries, commands/queries, public interfaces and test ownership;
[API response contracts](../../../../../docs/api/contracts.md) specialize HTTP/schema behavior.

## Current layering (transitional, not guidance for new writes)

The existing [features/base implementation](../../base/list_create.py)
provides generic API machinery used by current features. Its generic hooks do not
assume resource semantics, but its placement inside Labs is not neutral kernel
ownership. It currently includes contracts, validation responses, transaction
wrappers, serializer persistence and lifecycle hooks. It does not assume SKU fields, soft deletion,
acquisition costs, user-stamped fields, or resource audit records.

- Generic create/update `get_save_kwargs()` returns an empty dictionary.
- Generic detail `get_old_values()` returns an empty context.
- Generic detail returns the service's updated instance without mandatory reloading.
- Write locking is opt-in through `lock_on_write`.
- `ResourceChangeLogMixin` is explicitly opt-in and provides independent snapshots.
- Equipment API adapters add canonical SKU checks, actor stamps, soft deletion,
  auditing, row locks, and response rehydration from equipment queries.
- These hook descriptions record compatibility behavior only; do not add new
   booking/monitoring business workflows to API-base hooks.

### Target migration boundaries

- Every business write enters an `application` command, including category CRUD,
   assignments, status, jobs and admin. Commands own authorization, atomic writes,
   constraints/locks and audit intent; views and serializers do not save business
   state or own transactions.
- Base equipment creation, assignment, unassignment, and status writes now live in
   `application/`; named reads live in `queries/`; HTTP mechanics and category
   metadata live in `api/`. Legacy `services/`, root selectors, `base/`, category
   URL modules, and their imports have been removed. Category CRUD still uses the
   generic equipment API adapter's serializer persistence hooks and remains a
   follow-up before every-write command ownership is complete.
- Internal API imports its own `application`/`queries`, not its own `public`
   facade. [Equipment views](../api/views.py) now
   call those layers directly. Other features use supported behavior through
   the equipment public facade.
- Commands require the `actor` keyword, but the neutral scoped actor context and
   policy enforcement foundation are not present in this codebase; compatibility
   callers can still supply `None`. This is a documented adoption gap, not a
   claim of authorization readiness.
- Pure queries are read-only and acquire no workflow locks. External dispatch
   occurs outside database locks; `on_commit` is best-effort, not a durable outbox.
   Required delivery persists outbox intent in the command transaction and uses
   retryable dispatch/idempotent consumers. Existing base audit hooks alone do not
   establish event-delivery guarantees.
- Model integrity tests live under `core/labs/tests/`; category command/query/API
   tests live with the owning feature. Top-level feature-only suites are transitional.

## Routes

For each category below (no trailing slash):

| Method | URL |
| --- | --- |
| GET / POST | `/api/labs/equipment/{category}` |
| GET / PUT / PATCH / DELETE | `/api/labs/equipment/{category}/{id}` |
| GET | `/api/labs/equipment/{category}/reference-data` |
| POST | `/api/labs/equipment/{category}/{id}/actions/change-status` |
| GET | `/api/labs/equipment/{category}/options` |

Categories: accessory, computing, debugging, display, furniture, instrument,
laboratory, mechanical, networking, other, power, sample.

Category equipment options `GET /api/labs/equipment/{category}/options`
returns compact choices (`id`, `uid`, `sku`, `name`, `category`, `kind`).
Passing `?assignable=true` filters for unassigned equipment in the category whose
lifecycle status is `available` (any equipment actively assigned to a bench is excluded).

Category equipment status action `POST /api/labs/equipment/{category}/{id}/actions/change-status`
operates on the category equipment record, validating category membership and status
details, invoking the equipment application command to record the status transition, and
returning the full updated category detail representation.

Existing generic equipment assignment endpoints operate on the canonical
equipment ID for every category. Do not create parallel category assignment tables.

All category URLs, including computing, use explicit definitions in
`api/category_definitions.py`; the shared builder creates named serializer/view
classes, exposed from the aggregate `api.urls` module for introspection. Every definition declares named `model`, `fields`, and
`lookups` arguments and uses the same validation, query annotations, and CRUD lifecycle.

`fields` is the default category field set for list, create, update, and detail.
Optional operation overrides are declared only when their field set differs;
`None` inherits the default, while an empty tuple explicitly exposes no category
fields. Computing list exposes `ip_address`, `os_name`, and `mac_address`;
create permits only `mac_address` beyond shared fields; update permits only
`monitored_devices` and `technical_user` beyond shared fields. Computing detail
retains the configured agent and server-managed fields as read-only response data.
Every category explicitly lists its searchable model
paths: the shared SKU/name/serial/log-label fields plus category fields and searchable
related labels where appropriate. Numeric values and opaque file/JSON data are not
included. Reverse names consistently follow `{category}-list-create`,
`{category}-reference-data`, and `{category}-retrieve-update`. `route_names` remains
available in the category definition for possible future customization, but is not
currently applied by the route builder.

## Field contracts

Shared write fields: kind, type, manufacturer, product_model, sku, name,
serial_number, log_label, details, metadata, replacement_date, owner, department,
group, storage_room, firmware_version, power_draw_w, weight_kg, warranty_until,
calibration_required.

Additional writable category fields:

| Category | Create fields | Update fields |
| --- | --- | --- |
| accessory, debugging, laboratory, other | No additional fields | No additional fields |
| computing | mac_address | monitored_devices, technical_user |
| display | size, resolution, interfaces | size, resolution, interfaces |
| furniture, mechanical | dimensions, material | dimensions, material |
| instrument | interfaces | interfaces |
| networking | protocol, mac_address | protocol, mac_address |
| power | channels, interface, power_rating | channels, interface, power_rating |
| sample | customer, interfaces, characteristics | customer, interfaces, characteristics |

Foreign keys and many-to-many relations accept IDs and ID lists respectively.
Many-to-many fields support replacement and clearing with an empty list.
Reference data returns the category-associated active kinds and types, manufacturers
explicitly associated with that category, and active product models that connect
through those types and manufacturers. It also returns owners, groups and
category-specific lookup lists. Department and
group are writable references; a group can determine its department when department
is omitted, while mismatched department/group pairs are rejected.

Responses include category and reference labels, metadata, current_status,
acquisition_price, and acquisition_currency. Detail responses add details and all
category fields. Acquisition price is read-only from PurchaseItemResource, currency
from its Purchase. Missing allocations return null, not zero/EUR. Allocate using
the canonical Equipment content type/ID for all equipment categories.

Writes reject unknown fields, incorrect category kinds, mismatched kind/type and
manufacturer/product_model combinations, and inactive common references. The
canonical active-SKU unique constraint protects concurrent duplicate creation.

Computing `ip_address`, `os_name`, `hostname`, `disk_usage`, and `system_info` are
not writable through category CRUD. These are agent-reported or agent-owned values;
the proposed agent snapshot endpoint is not yet implemented. `hostname` is omitted
from list responses but retained in detail responses. `rdp_file` is generated
by the server and is likewise not writable through category CRUD. Audit result and
remarks are managed through the resource-audit API, not category payloads. Lifecycle
status changes use the separate change-status action.

## Compatibility and validation

Authentication preserves the existing API-key-or-authenticated-user policy. User
stamps and resource audit/change logs are applied when an authenticated actor exists.
API-key-only operations retain the existing actorless behavior.

That actorless compatibility is not the target authorization contract: new/rebuilt
commands accept an explicit scoped actor/context, including API-key/system actors;
`None` must not become an implicit authorization bypass.

POST and DELETE retain existing 200 response envelopes. PUT retains the existing
partial-update behavior; PATCH is recommended for partial changes. List APIs retain
search and optional `page` / `page_size` pagination with stable ordering.

Before deployment:

1. Review/generate migrations for newly registered category/lookup models, removing
   Equipment.currency and adding equipment_active_sku_unique; inspect existing SKU
   duplicates first. Preserve any historical monetary data before dropping fields.
2. Recheck model/URL imports, retired relations and index names. Earlier reported
   Computing/Computer and long-index failures are historical observations, not
   fresh system-check results from this documentation update.
3. Run database-backed CRUD, FK/M2M, audit rollback and concurrent SKU tests on a
   staging PostgreSQL database. Contract/query-compilation tests are not a substitute.
4. Generate the complete deployed OpenAPI schema after those project blockers are resolved.
