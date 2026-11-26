# Shared 3D model library

T2 additive API and migration. The dashboard only displays: which model a resource shows is stored on the
resource itself and edited from the resource's own screens.

## Model

- **Asset** (`VisualModelAsset`): one GLB file in the library, uploaded once. It stores the file, its
  `sha256` (unique), size, name, source URL and license, plus its placement: `rotation` (turns the export
  to face forward) and `surface` (work-surface height as a fraction of model height).
- **`visual_model` column** (nullable, `PROTECT`) on six resource tables. Catalog rows hold defaults:
  `StationType`, `EquipmentCategory`, `EquipmentProductModel`. Items hold their own choice: `Station`,
  `Bench`, `Equipment`.

This feature owns the `visual_model` column: every read and write of it goes through
`visual_models.public` (`targets.py` lists the tables). The owning features' write paths are unchanged.

Resolution (server side, `targets.py`):

| Resource | Shows |
|---|---|
| Equipment | its own model, else its product model's, else its category's |
| Station | its own model, else its station type's |
| Bench | its own model (the dashboard falls back to the station's model) |
| Catalog rows | their own model |

Many resources reference one asset, so a model is stored and downloaded once. An asset still in use
cannot be deleted (`409`).

## API

| Endpoint | Behaviour |
|---|---|
| `GET /visual-model-assets` | Page-number list with `usage_count` across all six tables |
| `POST /visual-model-assets` (multipart) | `201` new asset; `200` with the existing asset when the bytes are already in the library |
| `PUT /visual-model-assets/{id}` (JSON) | Replace name, attribution and placement. `If-Match` required |
| `DELETE /visual-model-assets/{id}` | `If-Match` required; `409` while used; file deleted after commit |
| `GET /{resource}/{id}/visual-model` | Stored model, shown model and where it comes from (`origin`) |
| `PUT /{resource}/{id}/visual-model` (JSON) | `{"visual_model_id": id or null}`. Last write wins (row lock) |
| `GET /visual-model-selections/{resource}` | Page-number list of one kind with stored and shown models (catalog defaults screen) |

`{resource}` is `station-types`, `equipment-categories`, `equipment-product-models`, `stations`, `benches`
or `equipment`. The room/station/bench mapping rows carry `visual_model_id`, the resolved model, so the
dashboard needs no resolution logic.

Missing asset preconditions return `428`, stale versions `412`. A `PUT` whose result equals the stored
state does not bump the asset version (WRT-5). Mutations require `lab_operations.manage` in HTTP and in
the application commands; reads use the same policy as the room mapping endpoint.

## Write safety

- Upload: the unique `sha256` constraint is the race guard. The loser of a concurrent identical upload
  deletes its stored file and returns the winner. Storage I/O stays outside database locks.
- Asset update/delete: `select_for_update` plus the version check.
- Selecting a model: locks the resource row and the asset row, so an asset cannot be deleted while it is
  being selected; the `PROTECT` foreign key is the database guard. Concurrent selections on one resource:
  the last write wins (documented, WRT-12). The row is saved with `update_fields` and the acting user.

## Uploads

GLB v2 only, at most 15 MiB (rejected while streaming), with embedded buffers and textures. Compressed
geometry (Draco, Meshopt, mesh quantization) and KTX2/Basis or WebP textures are accepted: the dashboard
bundles their decoders, so the browser never downloads decoder code from a CDN. Other required extensions
are rejected. CAD conversion happens before upload. No third-party assets are bundled.

## Reference models

`reference_models.py` builds seven original GLB models in code (no third-party content, no binary files in
the repository): server rack 42U, lab workbench, storage cabinet, storage shelving, benchtop instrument,
desktop computer and monitor. The bytes are deterministic, so the sha256 identifies them.

`python manage.py seed_reference_models` adds them to the library and sets them as the default of station
types and equipment categories that have no model yet, matched by name words (rack, workbench/table/bench,
cabinet, shelving; computing, display, instrument/debugging/laboratory/power). It never replaces a model
someone chose and is safe to rerun. `--library-only` skips the defaults. Anyone can replace a default from
Spaces → 3D models.

The dashboard draws mounted rack units over any rack model, and bench contents on any work-table model.

## Deployment

Browsers download GLB files from the media URL. When media is served from another origin (MinIO, or
Django's `/media/` in local development), that origin must allow the dashboard origin (CORS).

## API rules and evidence

| Rule | Result | Evidence |
|---|---|---|
| WRT-5, WRT-9 | pass | no-op asset update keeps version; missing/stale header tests |
| WRT-12 | pass | selection writes lock the row; last write wins is documented on the operation |
| UPL-1, UPL-3 | pass | multipart duplicate-field validation, GLB signature and embedded-resource validation |
| UPL-2 | pass | upload handler rejects chunks beyond 15 MiB; oversize API test |
| COL-1 | pass | bounded page-number lists; the frontend follows every page |
| PRF | pass | asset list with usage count and a selection page are one query each; mapping adds one query per collection |
