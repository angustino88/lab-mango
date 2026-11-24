# Backend & API Performance Architecture (Phases 1–4)

> Status: Implemented on branch `feat/concurrent-load-test-tool` (T2 — requires human review & approval before merge to `main`).
> Owner: Backend / Platform & Labs.

## 1. Problem Statement & Baseline Evidence

Load testing the `computing_table` weighted scenario (`GET /api/labs/equipment`, `?status=available`, `?q=pc`, `/reference-data`, `/facets`, `/options`) against 4 Uvicorn ASGI workers and PostgreSQL 16 (500 seeded computing units) exposed systemic cross-cutting bottlenecks affecting every API:

1. **PostgreSQL Connection Exhaustion (`FATAL: sorry, too many clients already`)**: `AppAPIView` dispatches synchronous handlers via `sync_to_async` without a concurrency cap. Under 100–1,000 concurrent requests, 4 workers spawn up to `4 × 40 = 160` threads exceeding PostgreSQL's default `max_connections = 100`. In addition, `CONN_MAX_AGE = 60` under ASGI pinned idle connections per threadpool thread, causing 100% HTTP 500 saturation under sustained load.
2. **Per-Request Auth & RBAC Query Overhead**: `EntraJWTAuthentication` and `effective_labs_roles` ran up to 3 SQL queries per request before any view query ran.
3. **Uncached Read APIs & Missing ETag/304**: `GET /api/labs/equipment/reference-data` executed 15 SQL queries per request; list, facet, and summary views emitted no `ETag` and re-queried PostgreSQL on every concurrent burst.
4. **Heavy Search & Correlated Subquery Overhead**: Multi-column `ILIKE '%q%'` searches lacked `gin_trgm_ops` indexes on `Equipment` (`sku`, `name`, `serial_number`, `log_label`) and `ComputingProfile.hostname`; correlated subqueries joined `django_content_type` repeatedly; list queries fetched unserialized `Equipment.details`.

## 2. Implemented Architecture (Phases 1–4)

### Phase 1 — Concurrency Stability, DB Connections & Compression
- **Per-Worker Async Concurrency Gate** (`core/common/api/api_views.py::AppAPIView.async_dispatch`): Bounds concurrent sync Django/ORM dispatches per ASGI worker via a per-event-loop `asyncio.Semaphore` (`API_MAX_CONCURRENT_SYNC_HANDLERS`, default `16`).
- **ASGI-Safe DB Connection Lifecycle** (`config/settings/base.py`, `config/settings/production.py`, `pyproject.toml`): Enabled `CONN_HEALTH_CHECKS = True`, defaulted `CONN_MAX_AGE = 0` under ASGI (required for external PgBouncer transaction pooling and to prevent Uvicorn threadpool connection leaks), and added `psycopg[binary,pool]` (`psycopg_pool`) so opt-in `DB_POOL_ENABLED=True` works cleanly for deployments without PgBouncer.
- **BREACH-Safe HTTP Compression** (`core/common/api/middleware.py::SafeGZipMiddleware`, `config/settings/base.py`): Subclasses `GZipMiddleware` right after `CorsMiddleware` and excludes auth/token endpoints (`/api/aad-login`, `/api/refresh-token`, `/api/logout`, `/api/csrf-token`, `/api/token`, `/api/auth/`) from compression.
- **Fail-Fast Redis Timeouts** (`config/settings/production.py`): Added 3s `SOCKET_CONNECT_TIMEOUT` / `SOCKET_TIMEOUT` defaults on `django_redis`.

### Phase 2 — Resilient Caching, Singleflight, Auth Cache & Post-Commit Invalidation
- **Technical Cache Primitives** (`core/common/cache.py` — zero business imports):
  - `safe_cache_*`: Fails open to PostgreSQL on Redis connection/timeout errors without failing read requests.
  - `get_namespace_version` / `bump_namespace_version_on_commit`: Versioned invalidation scheduled strictly inside `transaction.on_commit(...)` so rolled-back writes never invalidate caches.
  - `singleflight_get_or_set`: Distributed lock (`cache.add`, `lock_timeout=5`, `wait_timeout=5.0`, `poll_interval=0.05`) coalescing concurrent cache misses under thundering-herd traffic, with `skip_initial_get` to avoid duplicate Redis round-trips on cache miss.
  - `compute_strong_etag` / `etag_matches` / `canonical_request_hash`: Strong SHA-256 `ETag` and `304 Not Modified` support scoped by scheme, host, path, sorted query parameters, and `Accept-Language`.
- **Declarative View Read Caching** (`core/common/api/api_views.py::AppAPIView`):
  - Authorization always runs first inside DRF `initial()`.
  - Fast lock-free cache hits execute off the `thread_sensitive` DB thread (`thread_sensitive=False`); misses pass the precomputed `cache_key` directly to singleflight to avoid redundant Redis lookups.
  - Emits `ETag`, `Cache-Control: private, no-cache`, `Vary: Accept-Language, Accept-Encoding`, `X-Cache: HIT|MISS|BYPASS`, and optional `Server-Timing: app;dur=<ms>` (`API_SERVER_TIMING_ENABLED`, defaults to `DEBUG`).
- **Cache Contract Table** (per `.github/instructions/query-performance.instructions.md` §6):

| Surface | Key Format | TTL | Invalidation Trigger (Post-Commit) | Outage Fallback |
|---|---|---:|---|---|
| User Labs Roles (`core/users/access.py`) | `users:labs_roles:v{ver}:{user_id}` | `120s` | `post_save`/`post_delete` on `User`, `URSGroup`, `EntraIdentity`, `m2m_changed` on `User.groups` (`core/users/signals.py`), stub `URSGroup.update()` + `clear_labs_roles_cache` | Query `URSGroup` directly |
| Entra JWT Binding Flag (`core/users/features/auth/authentication.py`) | `users:entra_binding:v{ver}:{user_id}:{tid}:{oid}` | `120s` | Same `users:access` namespace signals (`core/users/signals.py`). Stores boolean `True` only (no pickled `User` object or password hash in Redis); `User` is loaded fresh by PK. | Query `EntraIdentity` directly |
| Equipment Reference Data & Filters | `api:read:labs:equipment:refdata:v{ver}:global:{hash}` | `600s` | Catalog/reference model signals (`core/labs/cache_invalidation.py`) | Execute queryset (`X-Cache: BYPASS`) |
| Equipment Facets & Options | `api:read:labs:equipment:inventory:v{ver}:global:{hash}` | `30s` | Equipment/assignment/loan/booking/downtime/service/catalog signals + explicit bumps on `change_state` / `reservations` `.update()` | Execute queryset (`X-Cache: BYPASS`) |
| Equipment List | `api:read:labs:equipment:inventory:v{ver}:global:{hash}` | `15s` | Same `labs:equipment:inventory` signals + explicit `.update()` bumps | Execute queryset (`X-Cache: BYPASS`) |
| Benches List (user-scoped), Summary & Filters | `api:read:labs:benches:v{ver}:{user_id\|global}:{hash}` | `15s` / `600s` | `Bench`, `BenchFavorite`, `BenchType`, `BenchGroup`, `EquipmentAssignment`, `ResourceDowntime` signals | Execute queryset (`X-Cache: BYPASS`) |
| Rooms & Stations Lists/Summaries | `api:read:labs:locations:v{ver}:global:{hash}` | `15s` | `Room`, `Station`, slots, geo, `EquipmentAssignment`, `ResourceDowntime` signals + explicit bump on `RoomSlot.bulk_create()` | Execute queryset (`X-Cache: BYPASS`) |
| Licenses List & Filters | `api:read:labs:licenses:v{ver}:global:{hash}` | `15s` / `600s` | `License`, `LicenseAssignment`, `LicenseAgreement`, `PurchaseItemResource` signals | Execute queryset (`X-Cache: BYPASS`) |
| Generic Reference Collections (`core/common/api/reference_views.py`) | `api:read:ref:{key}:v{ver}:global:{hash}` | `300s` | `post_save`/`post_delete`/`m2m_changed` signals on `resource.model` + post-commit bump on `POST` | Execute queryset (`X-Cache: BYPASS`) |
| Pagination `COUNT(*)` (`core/common/api/pagination.py`) | `api:count:{namespace}:v{ver}:{sql_hash}` | `15s` | Same namespace version as owning view | Run `SELECT COUNT(*)` directly |

### Phase 3 — Query & PostgreSQL Index Optimizations
- **Shared Public `ContentType` PK Filter**: `core/labs/models/resource/base/generic_links.py::resource_content_type_filter` uses Django's public `ContentType.objects.get_for_models(...)` (in-process cached by Django, no private `_cache` access) so `ResourceDowntime` and `ResourceServiceRecord` correlated subqueries filter by integer FK PKs consistently instead of joining `django_content_type`.
- **Deferred Unserialized Blobs**: `EquipmentCollectionAPIView.get_queryset` defers `Equipment.details` (only serialized on detail endpoints).
- **Partial Performance Indexes (originally `labs.0002_performance_indexes`, consolidated into `labs.0001_initial` per ADR 005)**:
  - Partial composite index `equipment_active_kind_name_idx` on `Equipment (kind, name, id) WHERE deleted_at IS NULL`.
  - Partial covering index `equipment_loan_active_due_idx` on `EquipmentLoan (equipment, due_at) WHERE returned_at IS NULL`.
  - **Why GIN trigram indexes on `Equipment` / `ComputingProfile` were intentionally omitted**: `EXPLAIN ANALYZE` on PostgreSQL 16 confirmed that Django's `__icontains` compiles to `UPPER(col::text) LIKE UPPER('%q%')`, which ignores plain `gin_trgm_ops` indexes (`Seq Scan`), and even with `UPPER(col)` expression GIN indexes, the multi-table `OR` across `labs_equipment`, `labs_equipmentkind`, `labs_equipmentmanufacturer`, `labs_equipmentproductmodel`, and `labs_computingprofile` still selects `Seq Scan` + `Join Filter`. Keeping 5 unused GIN indexes would add write overhead to workbook imports (PR #42) with zero read benefit.

### Phase 4 — Observability & Pagination Count Caching
- Added `_CachedCountPaginator` in `core/common/api/pagination.py` to cache exact `COUNT(*)` across page flips under the view's versioned namespace.
- Added `X-Cache` (`HIT`/`MISS`/`BYPASS`) and non-prod-default `Server-Timing: app;dur=<ms>` (`API_SERVER_TIMING_ENABLED`) headers on `AppAPIView`.

## 3. Measured Before / After Benchmark Results (`tools/load_test`)

Environment: 4 Uvicorn workers, PostgreSQL 16 (500 computing units), Redis 7 (`redis://localhost:6379/1`), `computing_table` 7-endpoint weighted scenario, `--reuse-etag`.

### 100 Concurrent Users (300 requests)

| Metric | Baseline (Before) | After (Phases 1–4 + Redis) | Delta |
|---|---:|---:|---:|
| Error Rate | 39.3% (`46` × 500, `72` timeouts) | **0.0%** (`216` × 200, `84` × 304) | **-39.3 pp (0 errors)** |
| Throughput | 5.42 req/s | **63.04 req/s** | **11.6×** |
| p50 Latency | 13,884 ms | **882 ms** | **15.7× faster** |
| p95 Latency | 30,584 ms | **4,290 ms** | **7.1× faster** |
| Total Duration | 55.32 s | **4.76 s** | **11.6× faster** |

### 1,000 Concurrent Users (1,000 requests)

| Metric | Baseline (Before) | After (Phases 1–4 + Redis) | Delta |
|---|---:|---:|---:|
| Error Rate | 87.8% (`47` × 500, `831` timeouts) | **0.0%** (`1,000` × 200) | **-87.8 pp (0 errors)** |
| Throughput | 12.94 req/s | **92.62 req/s** | **7.2×** |
| p50 Latency | 43,702 ms | **5,729 ms** | **7.6× faster** |
| p95 Latency | 75,251 ms | **9,924 ms** | **7.6× faster** |
| Total Duration | 77.27 s | **10.80 s** | **7.2× faster** |

## 4. Deployment Notes & Residual Risks

- **`CONN_MAX_AGE` production default changed (`60` → `0`)**: Under Uvicorn ASGI + PgBouncer transaction pooling, `CONN_MAX_AGE = 0` prevents threadpool connection pinning (`too many clients already`) and matches PgBouncer best practice. If deploying **without** PgBouncer, either enable Django's built-in psycopg pool (`DB_POOL_ENABLED=True`, now supported via `psycopg[binary,pool]`) or explicitly set `CONN_MAX_AGE=60` in the environment.
- **Performance indexes (`equipment_active_kind_name_idx`, `equipment_loan_active_due_idx`)**: Originally authored with `AddIndexConcurrently` (`atomic = False`) and later folded into `labs.0001_initial` for the fresh database (ADR 005).
- **Global `User.save()` invalidation scope**: Any `User.save()` bumps the global `users:access` namespace and `labs:equipment:refdata` (because user options are included in equipment reference data). Routine Entra logins in `aad_login` update `last_login` via `QuerySet.update()` and therefore do **not** trigger `User.post_save` or thrash these caches.
- **Time-dependent statuses** (`display_status`, `loan_overdue`, `is_calibration_overdue`) can reflect at most `15s` staleness on cached equipment list reads.
- **Dependency addition (`psycopg[binary,pool]`)**: Adds the official `psycopg-pool` extra (maintained by the `psycopg` project, required by Django 5.2's `OPTIONS["pool"]`); alternative considered was relying solely on external PgBouncer without an in-app pool option.
- **Test settings default**: `API_READ_CACHE_ENABLED`, `API_AUTH_CACHE_ENABLED`, and `API_SERVER_TIMING_ENABLED` default to `False` in `config/settings/test.py` so N+1 query-budget tests continue testing real SQL execution; `API_READ_CACHE_ENABLED` and `API_AUTH_CACHE_ENABLED` default to `True` in `config/settings/base.py`, while `API_SERVER_TIMING_ENABLED` defaults to `DEBUG`.
