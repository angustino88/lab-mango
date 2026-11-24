# Deprecated inventory retirement

Remove deprecated inventory contracts after their callers and stored data have moved to supported paths. Treat each public removal as a coordinated backend and frontend change.

## Bench inspection dates

- The Bench API, workbook and frontend now use the inventory contract without the two inspection dates. Inspection history is stored in service records. Workbooks with populated retired columns report those headers as ignored; export any workbook-only values before adopting the updated template.
- Apply database migration `0003` to prepare the restricted snapshot. Disable writers of the old dates, then apply `0004` to snapshot exact values and backfill service records in batches. Backfill inserts an unknown result for performed dates with no existing record and sets a due date when it follows the performed date. Source pairs that do not fit the service-record constraint remain available in the snapshot.
- Verify snapshot row counts and backfill results on a database copy. Back up the database, coordinate the removal with all clients and workbook operators, and switch application processes during the contract release. Apply `0005` with the old writers stopped. It holds a bench write lock during the final consistency check and aborts if the source dates changed during backfill.
- If `0005` detects drift, stop the old writers, migrate Labs back to `0003`, and reapply `0004` before attempting the contract again. Investigate any source records corrected after backfill before rollout. Rolling back `0005` restores the source fields from the snapshot. Rolling back `0004` keeps canonical service history; reapplying it skips inspections with a matching performed timestamp. Keep `0003` and the snapshot for the agreed retention period.

## Space and slot status

- Move dashboard, inventory, filters, summaries, and import callers to `lifecycle_status`, `condition`, `availability`, `activity_status`, and `access_policy` where supported.
- Slot reads now expose `service_status` and `is_occupied`. Station-slot writes use `service_status`. Coordinate the API cutover, including any external slot clients. The remaining space-level status fields, filters, summaries, and write actions require moving their callers to the separate state fields first.

## Remaining compatibility surfaces

- Inventory dashboard and booking aliases, equipment device migration suggestions, procurement fields, analytics exports, support ticket adapters, and old route redirects separately. Identify their callers and replacement workflows before removing them.
- Record the owner and cutover release for each public removal. Follow the request and response deprecation standards and coordinate deployed clients, agents, and workbook operators.
- Regenerate backend OpenAPI and the frontend client from the same contract for each release. Run migration and API contract checks, focused frontend tests and build, and representative browser workflows. Obtain owner approval before merging breaking changes.
