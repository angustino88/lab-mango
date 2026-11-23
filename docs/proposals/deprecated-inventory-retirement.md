# Deprecated inventory retirement

Remove deprecated inventory contracts after their callers and stored data have moved to supported paths. Treat each public removal as a coordinated backend and frontend change.

## Bench inspection dates

- Inventory and workbook import/export still read or write `last_inspected_at` and `next_inspection_due_at`. Replace those paths with inspection service records and remove the obsolete fields from the bench API, workbook format, generated client, and UI.
- Before dropping the columns, classify existing values as empty, performed-only, ordered pairs, due-only, or unordered pairs. Match existing service records before creating any new records. A legacy timestamp does not establish an inspection result.
- Preserve the exact timestamps and bench IDs in a restricted export before the schema change. Validate counts and retain the export for rollback. Resolve due-only, unordered, and unknown-result records with the data owner before backfill. A service record requires a performed date and any due date must follow it.
- Use a new migration for the schema change and retain applied migration history. Test backfill, duplicate detection, export reconciliation, and rollback on a representative copy.

## Space and slot status

- Move dashboard, inventory, filters, summaries, and import callers to `lifecycle_status`, `condition`, `availability`, `activity_status`, and `access_policy` where supported.
- Use `service_status` and `is_occupied` for slots. Remove deprecated status fields, filters, summaries, and write actions after clients have moved. Verify that lifecycle, downtime, access, and booking states retain their distinct behavior.

## Remaining compatibility surfaces

- Inventory dashboard and booking aliases, equipment device migration suggestions, procurement fields, analytics exports, support ticket adapters, and old route redirects separately. Identify their callers and replacement workflows before removing them.
- Record the owner and cutover release for each public removal. Follow the request and response deprecation standards and coordinate deployed clients, agents, and workbook operators.
- Regenerate backend OpenAPI and the frontend client from the same contract for each release. Run migration and API contract checks, focused frontend tests and build, and representative browser workflows. Obtain owner approval before merging breaking changes.
