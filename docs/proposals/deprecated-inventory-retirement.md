# Deprecated inventory retirement

Remove deprecated inventory contracts after their callers and stored data have moved to supported paths. Treat each public removal as a coordinated backend and frontend change.

## Bench inspection dates

- The Bench API, workbook and frontend now use the inventory contract without the two inspection dates. Inspection history is stored in service records (`ResourceServiceRecord`, kind `inspection`). Workbooks with populated retired columns report those headers as ignored; export any workbook-only values before adopting the updated template.
- Because the project database is blank/fresh, the schema removal of `Bench.last_inspected_at` and `Bench.next_inspection_due_at` and the `ResourceServiceRecord.result = "unknown"` choice were consolidated directly into `labs.0001_initial` (see [ADR 005](../architecture/decisions/005-migration-reset.md)). No separate snapshot or backfill migrations remain.

## Space and slot status

- Dashboard, inventory, filters, summaries, and space workbook imports now use `lifecycle_status`, `condition`, `availability`, `activity_status`, and `access_policy` where supported.
- Slot reads expose `service_status` and `is_occupied`. Station-slot writes use `service_status`.
- Move room, station, and bench read and filter consumers from `status` to the applicable canonical fields. The space status-summary endpoints now count stored lifecycle values. Dashboard list and detail use choice objects for lifecycle and condition. Dashboard filters accept those values independently.
- Replace room and station `change-status` writes with `change-lifecycle` for lifecycle and access and the downtime API for condition. Upload space worksheets with separate `Lifecycle`, `Access`, and `Condition` columns where supported.
- Roll out the backend and generated frontend client together. Confirm external API, slot, and workbook consumers have moved before release. This stage uses the existing database schema.

## Remaining compatibility surfaces

- Audit remaining dashboard and booking aliases, equipment workbook status, equipment device migration suggestions, procurement fields, analytics exports, support ticket adapters, and old route redirects. Identify their callers and replacement workflows before removing them.
- Record the owner and cutover release for each public removal. Follow the request and response deprecation standards and coordinate deployed clients, agents, and workbook operators.
- Regenerate backend OpenAPI and the frontend client from the same contract for each release. Run migration and API contract checks, focused frontend tests and build, and representative browser workflows. Obtain owner approval before merging breaking changes.
