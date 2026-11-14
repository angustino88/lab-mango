---
applyTo: '**/api/**,**/serializers*.py,**/views*.py,**/urls*.py,**/permissions*.py,openapi/**'
---
# API contract rules

The rules are owned by `docs/api/response-standard.md` (responses) and
`docs/api/request-standard.md` (requests); shapes are in `response-golden-examples.md` and
`request-golden-examples.md` in the same folder. Runtime mechanics: `docs/api/contracts.md`.
Do not restate those rules elsewhere; cite them by rule ID.

## Required for every endpoint or schema change
1. Read the sections of both standards that apply (response standard section 25, step 1).
2. Produce the rule table `Rule ID | pass / violation | fix` (response standard section 25).
3. Classify each change as breaking or non-breaking with VER-2. Breaking → human approval (AGENTS.md rule 6).
4. Regenerate the schema; never hand-edit `openapi/`:
   `uv run python manage.py spectacular_modules --output-dir openapi` (preview: add `--dry-run`).
5. Lint the bundled schema and report the result per AGENTS.md rule 8:
   `npx --yes @redocly/cli@1.34.21 bundle openapi/openapi.yml -o build/openapi.bundled.yml`
   then `npx --yes @stoplight/spectral-cli@6.17.0 lint build/openapi.bundled.yml --ruleset .spectral.yaml --fail-severity=error`.

6. Run the contract gate and report it per AGENTS.md rule 8:
   `uv run python -m core.common.openapi.contract_rules openapi/openapi-full.json`. A new violation is fixed in
   the code, never added to `core/common/openapi/contract_baseline.json`. A fixed violation is removed from the
   baseline in the same change. If a rule cannot be followed, change the standard first (response standard GEN-8).

## Rules agents most often get wrong (check these explicitly)
- Error body is `{"error": {"code", "message", "details", "request_id"}}` (ERR-1). It is **not** RFC 9457
  `application/problem+json`, and the status code is not repeated in the body.
- Semantic validation and unknown/read-only write fields → `422` (ERR-3, RW-3); malformed request or unknown
  query parameter → `400` (COL-4).
- Paths have no trailing slash (TRN-4). Do not add slash aliases or a versioned prefix (VER-1).
- `id` is the URL identifier; `uid` exists only where the resource type defines it (REL-1, REL-2).
  Relations are exactly `{"id", "name"}` objects (users too: `name` is the display name), never `owner` +
  `owner_name` siblings (REL-3, REL-4). Choose per reference what the consumer needs: `owner_id` when it only
  joins or navigates by id, `owner: {id, name}` when a person reads the name (REL-16); one form per relation,
  never both (REL-6), never a bare id under the relation's name (`"owner": 5`). Do not reuse an older
  serializer that returns `{id, username, ...}`. An owned child or bundle item is an embedded resource marked
  `x-embedded-resource` (REL-15). Enums are `{value, label}` (ENU-1); booleans `is_`/`has_`/`can_` (NAM-2);
  date-times `_at`, dates `_date` (NAM-3).
- Status changes are actions `POST .../{id}/actions/<verb>`, never a writable `status` field (ACT-1, ACT-3).
- `/options` endpoints return only `id`, `sku`, `name`; `sku` is a stable string or `null`; search is `q`;
  one shared base in `core/common/api`; enums get no `/options` (OPT-1 to OPT-13). Route naming, lookup classes
  and the route ledger: `docs/architecture/decisions/002-catalog-and-selector-api.md`.
- Retry-prone creates and non-idempotent actions (bookings, assignments, purchases, ticket creation) accept
  `Idempotency-Key` with RW-6 semantics: replay → original status and body + `Idempotency-Replayed: true`;
  same key, different body → `422 idempotency_key_reuse`; still running → `409 request_in_progress`.
  Implementation: `write-safety.instructions.md` section 3. The existing body-field `idempotency_key` in
  `support_desk` tickets is drift (header required, no body hash, no scope).
- Records edited by more than one user use a strong `ETag` from a version counter and require `If-Match` on
  `PUT`/`PATCH`/`DELETE`: missing → `428`, stale → `412` (RW-5, request standard WRT-9). Never derive the ETag
  from `updated_at` (STR-9).
- Every list and detail endpoint has a query-count test (PRF-2; `query-performance.instructions.md`).
- Pagination style follows COL-2 and COL-9; choosing cursor style for an endpoint is an API Designer decision
  recorded in the design note.

## Status of the redesign
The standard describes the target; not every endpoint is migrated (`response-standard.md` banner). Do not
claim an endpoint or the whole API is compliant unless you produced the rule table for it.
