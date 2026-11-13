# Resource images

Design note and API guide for images on Labs resources: benches, equipment, licenses, rooms and stations.
Risk tier: T2 (public API contract change). Needs human approval before merge.

## Problem

Every resource model inherits `image` from `ResourceModel` (`core/labs/models/resource/base/resource.py`),
but the API exposed it unevenly:

| Resource | Read | Write |
|---|---|---|
| Bench | `image` | create/update accept `image` |
| Room, Station | `image` | none |
| Equipment, License | none | none |

The OpenAPI schema followed the serializers, so equipment and license schemas had no image at all. URLs were
also built two different ways: DRF's default `ImageField` output in resource reads, and `get_media_url` (a
presigned URL when MinIO is enabled) for avatars.

## Decision

1. **One URL rule.** `ResourceImageURLField` (`base/resource_images.py`) renders `image_url` through
   `core.infrastructure.storage.urls.get_media_url`: a presigned URL when `MINIO_ENABLED`, otherwise an
   absolute media URL, and `null` when there is no image. All five resource read serializers declare it.
2. **One upload endpoint shape.** `/api/labs/{benches|equipment|licenses|rooms|stations}/{id}/image`, served by
   one base view, `ResourceImageAPIView`. A sub-resource is used because licenses have no create/update
   endpoint, and JSON bodies cannot carry files (UPL-7).
3. **No legacy field.** The old `image` read field (bench, room, station) and bench create/update's `image`
   input are removed; uploads go only through the `/image` endpoint. Owner decision: the API is still in
   development, so breaking clients is accepted. The dashboard's bench `image_url` uses `get_media_url` too.
4. **Lists carry the URL.** `image_url` is part of each resource's row serializer, so every paginated list
   (`/api/labs/benches`, `/equipment`, `/licenses`, `/rooms`, `/stations`) returns it with the data. No extra
   request per row.
5. **Layering.** The write lives in `base/resource_image_commands.py`. Each feature's application package
   binds it to its model (`bench_images = ResourceImageCommands(Bench)`, and so on), and its API view references
   that binding. API views therefore never import `core.labs.models` (each feature's boundary tests enforce this).
   Licenses export `license_images` through `public.py`, because license views use only the public facade.

## Contract

| Method | Body | Success | Errors |
|---|---|---|---|
| `GET` | none | `200 {"data": {"image_url": "<url>" \| null}}` | `404` missing or soft-deleted resource |
| `PUT` | `multipart/form-data`, exactly one `file` part | `200` with the new `image_url` | `404`; `413 payload_too_large` (over 5 MB); `415 unsupported_media_type` (detected type not JPEG/PNG/GIF/WebP, or a non-multipart body); `422 validation_failed` (missing part, unknown part, two `file` parts, content is not an image) |
| `DELETE` | none | `204`, also when there was no image | `404` |

Access: the Labs default (`LABS_STAFF_ACCESS`): coordinators, admins and API keys. Plain Labs users get `403`.

## Write safety

- **Race guard:** the resource row is locked (`select_for_update`) before the current image name is read and
  replaced, so two concurrent uploads serialize and each records exactly one change.
- **No storage I/O under the lock:** the new file is stored before the transaction opens. The old file is
  deleted with `transaction.on_commit` (best effort, logged on failure). If the transaction fails, the newly
  stored file is deleted.
- **Idempotency:** `DELETE` without an image is a no-op returning `204`. A repeated `PUT` stores a new object
  under a fresh server-generated name and deletes the previous one, so the state is the same: one image, no orphan.
- **Audit:** each change writes a `ResourceChangeLog` row (`field_name="image"`, old and new storage names, actor)
  in the same transaction. Key-only (API key) callers are not logged, matching `ResourceChangeLogMixin`.

## Standards check

| Rule | Result |
|---|---|
| UPL-1 one `file` part; unknown or duplicate part → 422 | pass |
| UPL-3 / FIL-3 type sniffed by Pillow, allowlist enforced (415), size enforced (413) | pass |
| FIL-7 client filename never used as storage path (`ResourceImageUploadPath`) | pass |
| NAM-3 URLs end in `_url` | pass |
| NUL-3 field always present, `null` when unset | pass |
| VER-2 classification | breaking: `image` removed from bench/room/station responses and from bench create/update input (owner-approved, API in development) |
| UPL-2 size enforced while streaming | gap: checked after Django has buffered the upload, as for avatars |
| FIL-4 downloads through a permission-checked endpoint | gap: `image_url` is a direct media URL or a 7-day presigned MinIO URL, the existing project-wide behavior of `get_media_url` |
| FIL-6 active content | pass: SVG is not on the allowlist |

## Follow-ups (not in this change; owner decision)

- The avatar upload schema documents its file part as `format: uri` instead of `binary` (no
  `COMPONENT_SPLIT_REQUEST`). The resource upload field overrides this locally.
