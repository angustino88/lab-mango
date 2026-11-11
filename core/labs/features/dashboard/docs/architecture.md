# Laboratory Dashboard Feature Architecture

> **Status:** Active feature specification under `core/labs/features/dashboard/`.
> **Owner:** Labs Engineering
> **Standard:** Aligns strictly with [Feature Template Specification](../../../../../docs/architecture/feature-template.md) and [Super-App Core Architecture](../../../../../docs/architecture/core-architecture.md).

---

## 1. Purpose and Scope

The **Dashboard** feature provides an operational observability and monitoring view of test workspaces (benches) across physical and virtual laboratory environments.

### Core Responsibilities
- **Operational Bench Overview:** Real-time projection of laboratory benches with attached equipment count, computing host state, active remote user, ongoing reservation/booking, physical placement, and user bookmark status.
- **Operational Summary Metrics:** High-level metrics aggregating total active benches, active booking load, utilization rate, lifecycle breakdown, and real-time computing activity distribution.
- **Detailed Bench View:** The clicked-bench endpoint returns attached equipment grouped by category, each item's active license summaries, computing status and heartbeat freshness, plus current/upcoming booking schedule fields.
- **Data minimization:** Clicked-bench detail excludes booking-user identity, host/remote IP addresses, remote-user identity and RDP URLs. The dashboard list response is unchanged by this detail-only projection.
- **Multi-Dimensional Query Filtering:** Efficient server-side filtering by bench group, lifecycle status, computing activity status, booking state, favorite status, physical location, assigned computing host presence (`has_computing`), physical placement mapping (`is_mapped`), and full-text keyword search.

### Non-Responsibilities
- **Mutations & Booking Scheduling:** Handled by `bench_bookings` and `benches` features.
- **Equipment Lifecycle State Transitions:** Handled by `equipment` feature.
- **User Engagement Gamification:** Handled by `leaderboard` and `analytics` features.

---

## 2. Layering and Module Boundaries

```
core/labs/features/dashboard/
├── __init__.py               # Empty, import-safe docstring
├── contracts.py              # Pure, immutable DTOs (DashboardBenchItemDTO, DashboardSummaryDTO, etc.)
├── exceptions.py             # Stable domain errors (DashboardResourceNotFound, DashboardFilterError)
├── public.py                 # Leaf public facade exporting DTOs, queries, and domain errors
├── urls.py                   # Re-exports urlpatterns from api/urls.py
├── api/                      # Thin HTTP transport adapters
│   ├── __init__.py
│   ├── urls.py               # Route definitions (/api/labs/dashboard, /summary, /benches/<id>)
│   ├── serializers.py        # Request filter and response serializers (drf-api-contracts)
│   └── views.py              # OperationContract-driven FeatureAPIView adapters
├── queries/                  # Read-only database selectors
│   ├── __init__.py
│   └── selectors.py          # Highly-optimized, zero-N+1 querysets with select_related & prefetch_related
├── docs/                     # Feature architectural specifications
│   └── architecture.md
└── tests/                    # Verification suite
    ├── __init__.py
    ├── test_public_boundary.py
    ├── api/
    │   ├── __init__.py
    │   └── test_views.py
    └── queries/
        ├── __init__.py
        └── test_selectors.py
```

---

## 3. Query Optimization & Zero-N+1 Guarantees

To ensure low latency and prevent N+1 query patterns:
1. **Active Bookings:** Prefetched using `Prefetch("bookings", queryset=BenchBooking.objects.filter(starts_at__lte=now, ends_at__gte=now, status__in=[...]).select_related("creator"), to_attr="_active_bookings")`.
2. **Computing Equipment & Real-Time Activity:** Prefetched using `Prefetch("equipment_assignments", queryset=EquipmentAssignment.objects.filter(unassigned_at__isnull=True).select_related("equipment", "equipment__computing_profile", "equipment__activity"), to_attr="_active_equipment_assignments")`.
3. **Location Hierarchy:** Single query join through `select_related("type", "bench_group", "owner", "station_slot", "setup_location__room__building", "setup_location__room__city", "setup_location__room__country")`.
4. **Favorite Bookmarks:** Subquery evaluation using `Exists(BenchFavorite.objects.filter(user=actor, bench_id=OuterRef("pk")))`.
5. **Equipment Counts:** Single database annotation using `Count("equipment_assignments", filter=Q(...), distinct=True)`.

Total database roundtrips per page of benches remain constant ($O(1)$) regardless of page size.

---

## 4. API Operation Contracts

| Endpoint | Method | Operation Contract | Success Shape | Error Codes |
|---|---|---|---|---|
| `/api/labs/dashboard` | `GET` | `DashboardOverviewAPIView` | Paginated `DashboardBenchList` | `invalid_query` (400) |
| `/api/labs/dashboard/summary` | `GET` | `DashboardSummaryAPIView` | Object `DashboardSummaryData` | (400) |
| `/api/labs/dashboard/benches/{id}` | `GET` | `DashboardBenchDetailAPIView` | Object `DashboardBenchDetailData` | `not_found` (404), (400) |

---

## 5. Security & Multi-Tenancy

- Endpoints enforce `[HasAPIKey | IsAuthenticated]`.
- User-specific bookmark state (`is_favorite`) and count are scoped to `request.user`. Anonymous or API-key requests safely default bookmarks to `False` and favorite counts to `0`.
