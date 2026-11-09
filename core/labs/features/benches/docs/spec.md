# Feature Specification: Benches & Workspaces (`core/labs/features/benches`)

## 1. Domain Overview & Purpose
The Benches feature governs test bench entities, logical workbench groupings, user bookmarks, physical station docking, and power/load capacity enforcement.

---

## 2. Data Models & Database Invariants

### 2.1 `core.labs.models.Bench`
- **Inheritance:** `ResourceModel`.
- **Fields:**
  - `bench_group` (FK `BenchGroup`, PROTECT, optional).
  - `type` (FK `BenchType`, PROTECT, optional).
  - `setup_location` (FK `Station`, PROTECT, optional).
  - `station_slot` (OneToOneField `StationSlot`, PROTECT, optional).
  - `lifecycle_status`: Enum (`planned`, `available`, `reserved`, `active`, `maintenance`, `out_of_service`, `retired`). Default: `planned`.
  - `criticality` (CharField(32), default="").
  - `requested_power_w`, `requested_load_kg`, `requested_cooling_w` (PositiveIntegerField, optional).
  - `required_utilities` (JSONField, default=dict).
  - `commissioning_date`, `last_inspected_at`, `next_inspection_due_at`.
- **Invariants:**
  - Physical Alignment: `bench.setup_location` must match `bench.station_slot.station`.
  - Station Slot 1:1: A `StationSlot` can accommodate at most one docked bench.
  - Placement Capacity: Total requested power, weight load, and cooling of benches docked at a station must not exceed station rated limits.

### 2.2 `core.labs.models.BenchFavorite`
- **Fields:** `user` (FK `AUTH_USER_MODEL`), `bench` (FK `Bench`), `is_delete` (BooleanField).
- **Invariant:** `UniqueConstraint(fields=("user", "bench"), name="unique_user_bench_favorite")`.

---

## 3. Options Standard Compliance (`GEMINI.md`)
`GET /api/labs/benches/options` strictly returns flat:
```json
{
  "data": [
    { "id": 1, "sku": "BNCH-001", "name": "ECU HIL Test Bench" }
  ]
}
```
- Filtering parity with list view (supports `group`, `type`, `station`, `status`, `is_favorite`, `search`).
- Stable ordering by `(name, id)` projected with `.only("id", "sku", "name")`.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Purpose & Contract |
|---|---|---|
| `GET /api/labs/benches` | `BenchListCreateAPIView` | Filtered list of benches. |
| `POST /api/labs/benches` | `BenchListCreateAPIView` | Create bench with reference checks. |
| `GET /api/labs/benches/{id}` | `BenchDetailAPIView` | Enriched detail view with location, slot, and hardware. |
| `PATCH /api/labs/benches/{id}` | `BenchDetailAPIView` | Update bench parameters. |
| `DELETE /api/labs/benches/{id}` | `BenchDetailAPIView` | Soft delete bench. |
| `GET /api/labs/benches/options` | `BenchSelectAPIView` | Dropdown selector `{id, sku, name}`. |
| `GET /api/labs/benches/status-summary` | `BenchStatusSummaryAPIView` | Lifecycle status distribution counts. |
| `GET /api/labs/benches/{bench_id}/equipment` | `BenchEquipmentListAPIView` | Devices assigned to bench. |
| `POST /api/labs/benches/{bench_id}/actions/place` | `BenchPlaceAPIView` | Dock/move bench to station slot with capacity validation. |
| `POST /api/labs/benches/{bench_id}/actions/favorite` | `BenchFavoriteAPIView` | Add bench to caller's favorites. |
| `DELETE /api/labs/benches/{bench_id}/actions/favorite` | `BenchFavoriteAPIView` | Remove bench from favorites. |
| `GET /api/labs/benches/{id}/profile` | `LabProfileAPIView` | Historical performance and usage stats. |
| `GET /api/labs/benches/{id}/weekly-usage` | `LabWeeklyUsageHeatmapAPIView` | 168-hour utilization heatmap. |
| `GET/POST /api/labs/bench-groups` | `BenchGroupListCreateAPIView` | Manage bench taxonomies. |
| `GET/POST /api/labs/bench-types` | `BenchTypeListCreateAPIView` | Manage bench type definitions. |
