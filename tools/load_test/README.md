# Concurrent Load & Performance Testing (`tools/load_test`)

Measure API latency percentiles (`p50`, `p90`, `p95`, `p99`, `max`), throughput (RPS), error rates, `ETag` / `304 Not Modified` caching behavior, and per-request SQL query counts under configurable concurrent virtual users.

Everything runs from the repository root through one entry point:

```bash
uv run python -m tools.load_test --help
```

| File | Purpose |
|---|---|
| `__main__.py` | CLI entry point (`python -m tools.load_test`) |
| `runner.py` | Async HTTP load generator (`httpx` / `urllib`), in-process Django runner with SQL query counting, and percentile reporter |
| `scenarios.json` | Built-in multi-endpoint weighted scenarios (`computing_table`, `equipment_table`, `locations_and_benches`, `licenses`) |

## Built-in Scenarios (`scenarios.json`)

- **`computing_table`**: Simulates concurrent users browsing, filtering, and searching the computing / equipment table (`GET /api/labs/equipment?page=1&page_size=25`, `?status=available`, `?q=pc`, `/reference-data`, `/facets?dimension=kind`, `/facets?dimension=manufacturer`, `/options?q=a`).
- **`equipment_table`**: Equipment list, `/filters`, `/reference-data`, and `/facets?dimension=category`.
- **`locations_and_benches`**: Weighted mix of `/api/labs/benches`, `/api/labs/stations`, and `/api/labs/rooms`.
- **`licenses`**: `/api/labs/licenses` and `/api/labs/licenses/options`.

## Common Commands

```bash
# 1. Test 1,000 concurrent users for 30 seconds against the computing table scenario
uv run python -m tools.load_test \
  --base-url http://localhost:8000 \
  --concurrency 1000 \
  --duration 30 \
  --ramp-up 5 \
  --scenario computing_table \
  --mint-jwt stub.admin \
  --reuse-etag \
  --json-out computing_1000u_report.json

# 2. Test multiple custom endpoints with weights
uv run python -m tools.load_test \
  --base-url http://localhost:8000 \
  --concurrency 200 \
  --requests 2000 \
  --token "$LABMANGO_BEARER_TOKEN" \
  --endpoint "computing_list=GET /api/labs/equipment?page=1&page_size=25|5" \
  --endpoint "computing_search=GET /api/labs/equipment?q=win11&page_size=25|2" \
  --endpoint "benches_list=GET /api/labs/benches?page_size=25|1" \
  --reuse-etag

# 3. Run in-process with Django APIClient to measure SQL query counts per request
uv run python -m tools.load_test \
  --in-process \
  --seed-computing 500 \
  --concurrency 20 \
  --requests 100 \
  --scenario computing_table
```
