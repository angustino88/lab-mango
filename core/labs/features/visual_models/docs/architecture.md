# Shared 3D model library

T2 additive API and migration. The library owns VisualModel and has no writes to other asset features.
Targets use stable catalog/resource ids and a unique (scope, target_key) constraint. A wildcard bench
target supplies a shared default. Equipment precedence is individual device, manufacturer/product model, then equipment category.
Bench precedence is individual bench then shared default. Station models use the station type id.
Uploads use existing Django storage and media URL resolution. Storage I/O stays outside DB locks.
PUT creation requires If-None-Match: *. Updates and DELETE require If-Match with the quoted version.
Missing preconditions return 428 and stale versions return 412. The application version check and
unique target constraint guard concurrent writers. Failed writes clean up
their uploaded file. Replaced and removed files are deleted after commit. Mutations require the existing
lab_operations.manage permission both in HTTP and the application command. Reads use the same policy
as the existing room mapping endpoint.

GLB v2 files are limited to 15 MiB and must embed textures/buffers. Unsupported required extensions are rejected
so the renderer never downloads external decoders. The UI stores source and license attribution.
CAD conversion is performed before upload. No third-party assets are bundled.

Acceptance: upload and preview a GLB, assign it to a station type/category or individual resource,
persist across users, reload placements, resolve overrides, retain fallback on failed rendering,
and reject invalid uploads or stale updates. Additive migration must be applied before frontend use.


## API rules and evidence

All endpoints are additive. The new nullable product_model mapping relation is additive and optional
for older clients. No migration history or existing resource write behavior changes.

| Rule | Result | Evidence |
|---|---|---|
| WRT-9 | pass | If-Match/If-None-Match guards; missing/stale header API tests |
| UPL-1, UPL-3 | pass | multipart unknown/duplicate validation, GLB signature and embedded-resource validation |
| UPL-2 | pass | upload handler rejects file chunks beyond 15 MiB; oversize API test |
| COL-1 | pass | bounded page-number catalog; frontend follows every page |
| REL-5 | pass | product_model is a nullable id/name relation from the equipment-owned mapping query |
| PRF | pass | catalog serializer query-budget test remains one query for three models |

Frontend previews use a synthetic GLB in browser verification. No licensed third-party model is
included. Local conversion of CAD/STEP/IGES to optimized GLB remains an external preparation step.
The frontend mapping projection was regenerated from the schema and only its related type change
retained, to preserve unrelated existing generated API contracts.
