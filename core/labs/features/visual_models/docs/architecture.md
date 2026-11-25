# Shared 3D model library

T2 additive API and migration. The feature owns `VisualModelAsset` and `VisualModelAssignment` and writes to
no other feature.

## Model

- **Asset** (`VisualModelAsset`): one GLB file in the library, uploaded once. It stores the file, its
  `sha256` (unique), size, name, source URL and license, plus model-intrinsic placement: `rotation` (turns
  the export to face forward) and `surface` (working-surface height as a fraction of model height).
- **Assignment** (`VisualModelAssignment`): maps one target to an asset. Targets use stable catalog or
  resource ids and are unique per `(scope, target_key)`. Scopes: `station_type`, `equipment_category`,
  `equipment_model`, `equipment`, `bench`; `bench/*` is the shared bench default. The assignment stores
  per-target fitting: extra `rotation`, `scale` relative to the fitted box, and offsets as box fractions.
  The renderer applies `asset.rotation + assignment.rotation`.

Many targets reference one asset, so a model is stored and downloaded once however many resources use it.
`asset` is `PROTECT`; deleting an asset that is still assigned returns `409`.

Precedence: equipment uses device, then manufacturer/product model, then category. Benches use the bench,
then the shared default. Stations use the station type.

## API

| Endpoint | Behaviour |
|---|---|
| `GET /visual-model-assets` | Page-number list with `usage_count` |
| `POST /visual-model-assets` (multipart) | `201` new asset; `200` with the existing asset when the bytes are already in the library |
| `PUT /visual-model-assets/{id}` (JSON) | Replace name, attribution and placement defaults. `If-Match` required |
| `DELETE /visual-model-assets/{id}` | `If-Match` required; `409` while assigned; file deleted after commit |
| `GET /visual-model-assignments` | Page-number list |
| `PUT /visual-model-assignments/{scope}/{target}` (JSON) | `If-None-Match: *` creates, `If-Match` updates |
| `DELETE /visual-model-assignments/{scope}/{target}` | `If-Match` required; `404` when unassigned |

Missing preconditions return `428`, stale versions `412`. A `PUT` whose result equals the stored state
does not bump the version (WRT-5). Mutations require `lab_operations.manage` in HTTP and in the
application commands; reads use the same policy as the room mapping endpoint.

## Write safety

- Upload: the unique `sha256` constraint is the race guard. The loser of a concurrent identical upload
  deletes its stored file and returns the winner. Storage I/O stays outside database locks, and a failed
  insert deletes its file.
- Asset update/delete and assignment update/delete: `select_for_update` plus the version check.
- Assignment create: the unique target constraint; a concurrent create gets `412`.
- Assigning locks the asset row, and deleting counts assignments under the same lock, so an asset cannot
  be deleted while an assignment to it is being written.

## Uploads

GLB v2 only, at most 15 MiB (rejected while streaming), with embedded buffers and textures. Unsupported
required extensions are rejected so the renderer never downloads external decoders. CAD conversion
happens before upload. No third-party assets are bundled.

## Known limits

Assignments have no foreign key to their targets, because targets span several features and catalogs.
Deleting a station type, category, product model, device or bench leaves its assignment in place; it is
harmless (nothing renders it) and can be removed from the library dialog. A cleanup job is a follow-up.

## API rules and evidence

| Rule | Result | Evidence |
|---|---|---|
| WRT-5, WRT-9 | pass | no-op update keeps version; missing/stale header tests for assets and assignments |
| UPL-1, UPL-3 | pass | multipart duplicate-field validation, GLB signature and embedded-resource validation |
| UPL-2 | pass | upload handler rejects chunks beyond 15 MiB; oversize API test |
| COL-1 | pass | bounded page-number lists; the frontend follows every page |
| REL-5 | pass | `product_model` is a nullable id/name relation from the equipment-owned mapping query |
| PRF | pass | asset list (with usage count) and assignment list are one query each |
