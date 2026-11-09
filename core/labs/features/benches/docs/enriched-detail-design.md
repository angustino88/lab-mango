# Historical task/design: enriched bench detail

**Tier:** T2 — public GET contract, booking read rules and cross-feature composition.
**Assigned role:** Backend Engineer. **Approval:** user explicitly approved this
design and the REL-8 bounded inline exception on 2026-10-20. On 2026-10-20,
the user subsequently approved a breaking contract change: remove the enrichment
from ordinary bench GET; dashboard clicked-bench detail is the operational surface.
The implementation remains available as an internal projection pending usage review.
Merge/release approval and independent security/QA review remain separate gates.

## Superseding contract decision (2026-10-20)

- `GET /api/labs/benches/{bench_id}` is lean and returns `BenchSerializer` only.
  The inline `equipment` and `booking_summary` fields and `equipment_page` /
  `equipment_page_size` parameters are no longer part of that endpoint. Unsupported
  query parameters return the standard 400 error envelope.
- The dashboard click endpoint `GET /api/labs/dashboard/benches/{bench_id}` is the
  operational detail view. It carries category-grouped equipment, per-equipment
  active license summaries, computing status/heartbeat freshness, and booking
  schedule summaries.
- The clicked-bench detail omits booking-user identity, host/remote IP, remote-user
  identity, OS, and RDP URL. The dashboard list contract is unchanged.
- Resource mappings remain graphic-only and separate; they already include flat
  placement collections and active license summaries through the license owner facade.
- This is an approved breaking API change. Coordinate frontend consumers before
  release; no deprecation/version route was added.

## Superseded original outcome and acceptance criteria (historical only)

- Existing `GET /api/labs/benches/{bench_id}` retains all bench fields and adds
  bounded `equipment` and `booking_summary`. No new endpoint or invented booking URL.
- Equipment is `{data: [assignment mappings], meta: {pagination: {count, page,
  page_size, next, previous}}}`. Default 20, maximum 100; deterministic position/ID
  order. Only active assignments to non-deleted equipment are included.
- Detail accepts only `equipment_page` and `equipment_page_size`, positive ASCII
  integers, without repeated keys. Unknown/invalid queries return 400 with the
  standard error envelope. Nonexistent pages return 404; empty first page is 200.
- Mapping fields remain `id`, `equipment` (id, uid, sku, name, kind), `role`,
  `position`, `is_monitored`, `assigned_at`; only detail mappings add
  nullable `computing_activity` (status enum, last_agent_report_at, is_stale).
- Non-computing equipment returns null. A real computer without activity returns
  offline with null heartbeat and null freshness, without persisting a default.
  Stale means heartbeat strictly older than ten minutes. Exact cutoff is fresh.
  Freshness is independent of stored status and never reconciles it on GET.
- One request timestamp drives freshness and booking selection. New timestamps
  are UTC ISO 8601. No remote identity, IP, inactivity or booking telemetry is
  fetched by these owner projections.
- Booking summary contains evaluated_at, current_reservations (maximum five),
  current_reservations_count, is_current_reservations_complete, next_reservation.
  Reserving requires both Booking.ACTIVE_STATUSES and
  Booking.RESERVING_APPROVAL_STATUSES (pending or approved); rejected and terminal
  bookings are excluded. Current uses starts_at <= now < ends_at; next uses
  starts_at > now. Both order by starts_at then ID. Each booking contains only id,
  booking_code, starts_at, ends_at, status, approval_status, project (id/name or null).
- Preserve IsAuthenticated and existing other-owner authenticated visibility.
  No migrations, dependencies, access-control changes, locks or writes on GET.
  List, create, replace, patch, action and equipment-subresource responses retain
  their existing shapes and serializers.

## Boundary and compatibility decisions

`queries/detail.py` is the deliberate bench read-composition boundary. It reuses
the existing centralized-model assignment selector and calls equipment and bench
booking **public read facades** for owned live-state and reservation semantics.
It imports no other feature's private implementation. Serializers only shape data;
the HTTP view validates, samples time once and calls the read projection.
No shared clock helper exists in this repository; the existing timezone.now
convention is sampled once at the HTTP boundary and injected into both reads.

The approved REL-8 exception applies exclusively to this bounded GET. Pagination
links revisit the same canonical slashless detail route, preserving the effective
equipment page size, so later pages have equivalent computing projections. The
equipment_url is a canonical same-API path on detail only. Legacy list/write
equipment_url behavior and the separate equipment-subresource shape are untouched.
This is also a deliberate GET-only exception to RW-4's identical write-detail shape.

No transactional snapshot is promised: under read committed, count, page and
booking projections can observe concurrent commits. This endpoint is descriptive,
not an availability or conflict guard; booking writes retain their own invariants.

## Non-goals and verification

No booking transitions/reconciliation, placement changes, unrelated dirty-tree
cleanup, telemetry expansion or migration changes. Preserve all prior work.
Focused tests: `../tests/test_enriched_detail.py` cover shapes, bounds, pagination,
freshness, approval/temporal boundaries, completeness, visibility, no writes and
constant query budget. Run existing bench/equipment/booking tests, lint, formatting,
types, architecture checks and scoped OpenAPI validation. Record actual outcomes
and pre-existing failures separately in the handoff; do not certify merge readiness
without independent review.