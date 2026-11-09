# ADR 003 — Reusable temporal query bounds without changing booking semantics

- Status: **Proposed — not owner approved**
- Date: 2026-11-03
- Decision owner: repository owner (approval pending)
- Risk: T2 (public query contract and shared API boundary)
- Scope of proposed implementation: neutral temporal parsing/validation and adoption by the bench-booking collection only. This ADR makes no runtime, schema, or API change.
- Authority: [request standard](../../ai-team/api/request-standard.md) QRY-1–QRY-5, QRY-12, CMP-1–CMP-4; [response standard](../../ai-team/api/response-standard.md) COL-3–COL-6, ERR-1–ERR-3, VER-1–VER-3, PRF-1–PRF-3; [ADR 001](001-common-foundation.md) for the common foundation. Those documents own the rules; this record specifies the endpoint mapping and staged adoption.

## Context (verified current state; not a certification of deployed behavior)

- The working-tree booking list accepts optional `starts_at_after` and `starts_at_before`. A strict date-only value becomes midnight in Django's **default** `TIME_ZONE`; an explicitly offset-aware RFC3339 value remains an instant. Blank, malformed, naive, reversed, equal, and repeated bounds are rejected. The current `TIME_ZONE` setting is `Asia/Ho_Chi_Minh`. Sources: [booking serializer](../../../core/labs/features/bench_bookings/api/serializers.py), [settings](../../../config/settings/base.py), [query validation](../../../core/common/api/api_views.py). The booking filter and tests are **uncommitted work** at the time of this proposal; released-client behavior is not verified.
- The owning selector applies `ends_at > lower` and `starts_at < upper`, including when only one bound is present, after actor visibility has been applied. It returns a paginated, deterministically ordered queryset and does not filter out statuses solely due to the calendar window. Sources: [booking selector](../../../core/labs/features/bench_bookings/queries/bench_bookings.py), [booking list view](../../../core/labs/features/bench_bookings/api/views.py), [booking tests](../../../core/labs/features/bench_bookings/tests/api/test_bench_booking_list.py).
- Other endpoints have different semantics: [analytics insights](../../../core/labs/features/analytics/api/insights/serializers.py) require `from_date_time`/`to_date_time`; [monitoring](../../../core/labs/features/monitoring/api/serializers.py) accepts `from_date`, `to_date`, and datetime aliases with an *inclusive* `occurred_at` upper bound in its [selector](../../../core/labs/features/monitoring/queries/selectors.py); [expense](../../../core/labs/features/expense/api/serializers.py) uses `DateField` `from_date`/`to_date` with an *inclusive* `valid_from` upper bound in its [selector](../../../core/labs/features/expense/queries/selectors.py). Their callers, exact runtime errors, and rollout readiness are not verified. Expense calendar/financial meaning must not be silently recast as timestamp instants.
- [Common query filtering](../../../core/common/api/filtering.py) already has `QueryDateTimeField` and `FilterSpec` with range validation; it also owns ORM filtering. Reuse or isolate the field's parsing behavior rather than creating a second divergent RFC3339 dialect. A shared *temporal primitive* must not grow into a generic queryset/visibility owner. The booking serializer currently owns a local parser; extracting it is justified by the booking adopter plus explicitly identified future consumers, not permission to migrate them now.

## Proposed decision and contract

### 1. Parameter grammar (QRY-5), separate from matching semantics

An endpoint **opts in** to a named temporal field. The public pair is `<field>_after` and `<field>_before`; each may be omitted independently unless the endpoint explicitly declares a required pair. `after` denotes the inclusive start and `before` the exclusive end of the *query window* $[L,U)$. No suffixes `from_date`, `to_date`, or `from_date_time` are automatically aliased, renamed, or rejected on existing endpoints. Do not add an `ordering`, `q`, or temporal bound to endpoints that do not declare one. One occurrence per key, no blank input; unknown/repeated/invalid query keys yield HTTP 400 at the existing query-validation boundary (QRY-1, QRY-2, QRY-4, ERR-3). Return `details[].field` equal to the offending public parameter (QRY-12). If both bounds exist, require $L < U$ **as instants**; equality and reversed bounds fail on `<field>_before` with `invalid_range`. A single bound is valid for bookings; missing bounds mean no temporal filter. No implicit end-of-day adjustment: to include November 2–8, clients send `starts_at_after=2026-11-02&starts_at_before=2026-11-09`.

For **bench bookings only**, retain the current accepted wire formats and conversion: exact real Gregorian `YYYY-MM-DD` becomes local midnight of that date in Django's configured **default** `TIME_ZONE`, not the active request timezone, client offset, or UTC midnight. A datetime must match `YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)` with a real clock time and explicit offset; parse it as an aware instant, compare normalized instants, and do not reinterpret it in the default timezone. Reject naive datetimes, whitespace, invalid dates/times/offsets, and empty values. Preserve current validation messages, detail codes (`invalid_format`, `invalid_range`) and 400 error envelope where observable; during extraction, pin exact baseline behavior with tests, including `Z`, positive/negative offsets, offset-equivalent endpoints, and date-only bounds across DST transitions (nonexistent/ambiguous midnight: characterize and retain existing Django behavior; any tightening requires separate approval). Do not introduce a numeric fractional-second precision policy or offset restriction that the current parser does not enforce without a separate contract review. For a future endpoint that accepts only datetimes, configure a datetime-only mode; for a date-valued column, configure a date-only mode rather than converting `DateField` values to timestamps. QRY-3 and TYP-7 apply to datetime inputs; booking's date-only allowance is the documented endpoint-specific QRY-5/TYP-8 variant.

The selected comparator belongs to the **endpoint's owning query**, not to the shared parser:

| Surface | Current / proposed temporal match | Contract action |
| --- | --- | --- |
| Bench bookings, `starts_at_after` / `starts_at_before` | **Preserve:** interval overlap `booking.ends_at > L` and `booking.starts_at < U`; single-sided equivalents; rows touching only the boundary do not overlap. | Adopt parser/mixin without changing the selector, scope, status inclusion, ordering, pagination, or public names. `starts_at` in the parameter is the calendar-window name, **not** an order-by comparison against `starts_at`. |
| Single timestamp field on a **new** endpoint | **Proposed default:** `field >= L` and `field < U`; omitted bounds do not add predicates. | Owner declares field and indexed query/operator mapping; no shared ORM lookup. |
| Date-valued field on a **new** endpoint | **Proposed default:** `field >= lower_date` and `field < upper_date`, comparing calendar dates, without timezone conversion. | Owner chooses date-only input contract and documents its boundary and data meaning. |
| Existing analytics, monitoring, expense | **No change in this rollout.** | Legacy migration needs per-endpoint consumer audit, owner decision, VER-2 classification and separate approval; inclusive historical upper bounds cannot be quietly flipped. |

### 2. Neutral API boundary and opt-in

Proposed target is a narrowly named temporal capability under `core/common/api/` (for example, `temporal_query.py`), **not implemented in this brief**. It contains (a) a reusable strict bound field/parser configurable for booking-compatible date-or-aware-datetime, datetime-only, or date-only inputs and (b) an opt-in DRF query-serializer mixin validating a *declared* pair with `after < before`. The field returns `datetime` (aware) for booking/datetime mode or `date` for date-only mode; validation preserves public key names and typed `validated_data`. Keep public parameter declaration and help text beside the owner's serializer for schema generation. Do not add a base view, global registry, auto-discovery, query serializer that accepts all temporal keys, or a feature-wide filter framework. The mixin must compose with the existing pagination serializer and `validate_query()` path without overriding its authentication, unknown/repeated-key, 400 status, error-envelope, or pagination behavior. Do not normalize dates to UTC before choosing local midnight; equivalent aware instants may be compared in UTC after parsing. Validate the mixin's behavior on the actual subclass and code path, not just unit tests of the parser.

`core.common.api` may import stdlib, Django timezone, and DRF, but **no** Labs/booking model, settings module, queryset, `Q` object, field lookup, permissions, actor, or feature package. Do not extend `FilterSpec.apply()` to determine interval semantics. Feature API imports neutral parsing; feature queries retain authorization and SQL. Future adopters opt in explicitly and supply their own selector semantics; no new cross-feature import is created.

```mermaid
flowchart LR
    Request["GET bench-bookings with optional starts_at bounds"] --> Validation["Existing query validation and allowlist"]
    Validation --> Temporal["Proposed neutral temporal field and pair mixin"]
    Temporal --> Selector["Booking-owned list selector"]
    Selector --> Scope["Actor visibility"]
    Scope --> Overlap["Booking interval overlap predicates"]
    Overlap --> Page["Existing bounded pagination and response"]
```

### 3. API rule check and VER-2 (proposed booking-only adoption)

| Rule ID | Status (pass / violation) | Fix or evidence required before approval |
| --- | --- | --- |
| QRY-1, QRY-2, QRY-4, COL-4, COL-6 | Pass by design; runtime regression possible | Preserve the existing booking allowlist and unknown/duplicate/blank 400 checks; assert emitted OpenAPI parameter list. |
| QRY-3, QRY-5, TYP-7, TYP-8, COL-3 | Pass by design for booking's documented date-or-aware-datetime variant | Verify strict grammar, two optional bounds, half-open window, default-timezone date-midnight and offset instants; do not impose date input on other endpoints. |
| QRY-12, ERR-1–ERR-3 | Pass by design; current invalid query uses `validation_failed` for serializer errors | Pin exact booking status, top-level code, detail fields/codes/messages before replacing parser; preserve via existing response path. Do not change status/code to 422 during extraction. |
| SEC-1, SEC-2, SEC-15, SAF-1, SAF-5 | Pass by design; require regression | Actor visibility stays in the selector; test role/object scope with bounds, anonymous and API-key-only callers; no client-supplied ORM path. |
| COL-1, COL-2, COL-5, PRF-1–PRF-3 | Pass by design; require regression | Preserve pagination, stable ordering and joins; assert 3-row fixed query budget and SQL-side filtering. |
| CMP-1–CMP-4, VER-1–VER-3, DOC-1 | **Conditional**, not certified | Parser extraction with identical accepted inputs, result sets, errors and OpenAPI is contract-neutral. The existing working-tree optional booking parameters are additive under VER-2/CMP-1 **relative to a release lacking them**, but released baseline is not verified; if already shipped, any tightening/rename/reinterpretation is breaking. Compare generated schema and observed behavior to deployed baseline before claiming non-breaking. |

No schema changes are intended: regenerate OpenAPI **only in the implementation change**, never edit generated pages manually. A schema-only description change is reviewed against actual parameter acceptances and error behavior. ADR 001's documented API-key risk remains unchanged; this decision does not grant new access.

## Options considered

| Alternative | Complexity / compatibility | Decision |
| --- | --- | --- |
| **Smallest change:** keep booking-local parser and tests; document QRY-5 only | Lowest risk/no shared primitive, but booking validation is copied when a second adopter arrives. | Viable if owner defers reuse; not the requested shared-convention outcome. |
| **Proposed:** neutral parser + opt-in pair mixin; booking-only adoption, feature-owned SQL | Small bounded API abstraction; can regression-test extracted behavior without migrating business filters. | Recommend after owner/API/security/QA review. |
| Replace all temporal filters with one `FilterSpec` or shared ORM adapter at once | Cross-feature contract break, changes inclusive ends, calendar/financial semantics and visibility risk; `FilterSpec` already owns ORM paths. | Reject for this rollout. |

## Migration, rollback and consequences (proposed, no code or migrations now)

1. Before implementation, capture the **released** booking OpenAPI and representative query/error responses (not merely the uncommitted test state); confirm consumer usage, default timezone, DST behavior, current error codes and precision. API Designer and QA sign off on a no-diff compatibility matrix. If uncommitted booking behavior is not yet deployed, classify its optional filter addition separately and secure owner approval for its release plan.
2. Add the neutral parser/pair validator and isolated tests; keep the booking parameter definitions/schema owned by its serializer. Adopt only in the booking list query serializer. Characterization tests must pass unchanged; verify actual route, response and generated OpenAPI against baseline. Do **not** modify selector comparisons, model/index/constraint, permissions, routes, or other feature serializers. No database migration/backfill, state-machine or write-path change.
3. Release coordinated with clients only if the baseline schema/behavior are preserved (or an explicit owner-approved redesign covers any difference). Monitor 400 query rejection rate and list latency/query count, without logging raw query strings or personal data. Roll back the *implementation* by restoring the booking-local parser and previous schema artifact together; no data rollback is needed. If released filter parameters were already consumed, **do not remove them on rollback**; restore their old parser/semantics instead.
4. Any later analytics/monitoring/expense migration is a separate T2 brief: inventory consumers and sensitive data; decide date-only/instant, required/optional bounds, name aliases and comparison meaning per endpoint. Classify each proposed rename, inclusive-to-exclusive change, tighter datetime validation, error/status/default change as **breaking** (CMP-2/VER-2); provide client migration, approved schedule/deprecation or coordinated cutover under VER-1; generate schema and get explicit human approval. No assumption that this ADR approves those migrations.

Trade-off: retaining date-only booking semantics ties calendar windows to the configured default timezone; a future default-timezone change itself changes results and requires contract review. Reuse is deliberately transport-only and does not eliminate endpoint-specific query tests.

## Enforcement and test plan (future implementation)

- Parser/mixin unit table: invalid date/leap day, malformed RFC3339/naive timestamp/invalid offsets, empty and repeated bounds at HTTP boundary, strict whitespace, date-to-midnight in `Asia/Bangkok` and configured default zone under a different active zone, offset-equivalent instants, lower-only, upper-only, equality and reversed instants attributed to `starts_at_before`; characterize fractional seconds and DST local midnight with existing Django behavior before final rules are signed off.
- Booking HTTP/query table: create bookings wholly inside, spanning, ending exactly at lower, starting exactly at upper, ending exactly at upper, and starting exactly at lower; assert overlap rather than `starts_at >= L`, inclusive/exclusive boundaries, all statuses as before, date-only and aware-offset equivalence, both pagination pages and unchanged output/envelope. Maintain tests for coordinator vs member/own vs other, `view_side=booking_calendar`, anonymous/API-key-only, and filters that must not expand visibility.
- Query budget on 3+ rows with related bench/project/creator: assert fixed queries with and without bounds, SQL-side filtering, existing indices/order; examine `EXPLAIN (ANALYZE, BUFFERS)` on representative PostgreSQL data before making any index performance claim. No new index is proposed.
- Architecture check under `tests/architecture/`: assert the new `core.common.api` temporal module has no business/ORM/config imports and that feature ownership of selectors remains; extend existing boundary tests rather than relying on an unconfigured import-linter. Compare booking schema to baseline; run focused booking tests, architecture tests, OpenAPI regeneration and Spectral on the future implementation. Security, QA and independent reviewers assess the diff; human owner decides acceptance.

## Open questions for the owner / follow-up

1. Verify whether the current working-tree booking filters are already a *released* contract, and obtain the released schema/consumer inventory before asserting VER-2 non-breaking status (API Designer).
2. Characterize timezone behavior around nonexistent/ambiguous local midnight and accepted fractional precision before committing to byte-for-byte equivalent parsing (Backend Engineer + QA). If exact behavior is unsafe or impossible to preserve, stop and seek explicit API-owner approval for a separately documented breaking change.
3. Decide separately whether and when legacy analytics required pairs and monitoring/expense inclusive `to_date` filters should migrate; do not conflate financial calendar dates with UTC instants (API Designer + domain owners).
