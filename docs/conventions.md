# Naming and Text Conventions

These conventions apply to new code and to code touched during planned refactors.
The [feature template](feature-template.md) is authoritative for feature structure,
dependency boundaries and test ownership. The [core architecture](core-architecture-redesign.md)
owns app/kernel placement and rebuild sequencing. The isolated
rebuild may intentionally replace contracts; deployed database columns, API
routes, payload keys, registry identifiers, and message codes remain compatibility
surfaces until an explicit cutover decision. Do not rename them only for style.

## Python and Django

- Use `snake_case` for module names, functions, local variables, constants' descriptive components, and Python model fields.
- Use `PascalCase` for classes. Name serializers by entity and purpose: `ComputerCreateSerializer`, `ComputerListSerializer`, `ComputerReferenceSerializer`.
- Use `UPPER_SNAKE_CASE` for constants and stable public error-code identifiers.
- Use descriptive, plural `related_name` values for common reverse relations (for example, `bookings`). Where abstract model inheritance requires collision-safe names, use Django's `%(app_label)s`/`%(class)s` templates consistently.
- Avoid introducing new generic abbreviations, mixed-case identifiers, or spelling variants. Prefer `power_supply` in new internal Python identifiers, but preserve legacy identifiers such as `powersupply` where they are part of database or API behavior.

## Database identifiers

- Prefer normal Django-generated columns from `snake_case` model fields for new schema.
- Keep `db_column` only when integrating with an existing database schema or when a documented compatibility requirement calls for it.
- A Python field rename can change ORM call sites and migration state even if `db_column` is preserved. Treat it as a migration, search/update all Python references, and verify `makemigrations --check` plus database migrations.
- Never rename a production column as a formatting-only change. Use an explicit migration plan and preserve rollback compatibility.

## HTTP routes and JSON contracts

- For API resource and action endpoints, use plural collection names and lowercase kebab-case path segments; paths MUST NOT end with a trailing slash.
- Represent resource identity in path parameters; use query parameters for filtering, sorting, and pagination. Use nested routes only when the parent-child relationship is meaningful.
- Keep public JSON keys in the existing API's established format. Do not assume Python field names, database columns, URL segments, and JSON keys must be identical.
- Existing routes (including singular names, older spelling, or slash variants) remain supported until clients have a versioned migration/deprecation path. Add aliases where practical rather than silently changing the contract.
- Document request and response changes in OpenAPI and test the runtime payload against the generated schema.

## Equipment identifiers and registries

- Use `snake_case` for new internal capability and equipment identifiers.
- Use plural snake_case capability package names, such as `benches` and `locations`; mass nouns such as `equipment` are valid. Model classes remain singular. Do not rename established public routes or payload keys solely to match an internal package name.
- Treat values emitted in URLs, status logs, audit records, or client payloads as public/stored identifiers; changing them requires explicit aliases and compatibility tests.
- Set an explicit public key in registry metadata whenever it differs from the canonical internal key. Test registry metadata against assignment definitions and the relevant model fields.
- Keep equipment-specific rules in the equipment feature package. A shared registry should describe common capabilities, not conceal type-specific business behavior.

## Serializer and feature layout

- Give serializers distinct names when their shapes or purposes differ; do not rely on identical short class names in separate modules to create distinct OpenAPI components.
- Keep input serializers separate from read/list/detail serializers when the allowed fields differ.
- Every active Labs feature exposes a stable `core.labs.features.<feature>.urls` facade. The Labs router must include this facade rather than an internal API module.
- Put HTTP transport code under `api/`: `api/urls.py`, `api/views.py`, and `api/serializers.py`. Do not place new views or serializers directly in the feature root.
- Put command workflows and policies under `application/`, and read queries under `queries/`. A small feature need not create empty packages, but must use these names when the responsibilities exist.
- Use `contracts.py` for DTOs, events and public protocols only; business errors live in `exceptions.py` and typed command inputs beside the use case. Export supported external commands/queries and needed exception types explicitly through `public.py`. Internal API/tasks/handlers import their own application/queries, never their leaf public facade.
- Shared, domain-neutral API templates belong in `core.common.api`. Labs resource behavior belongs in a named Labs-owned module or its owning feature, not in a universal API base.
- Organize rooms/stations or equipment variants as capability modules within the canonical API/application/query layers, not a parallel nested feature tree.
- Keep reusable cross-domain primitives in `core/common`; put domain policy in its owning feature.

Use the [canonical feature shape](feature-template.md#2-final-structure) and
[optional-layer rules](feature-template.md#5-layout-sizing-and-naming). Do not
copy a second template here. Optional tasks/handlers live at feature root;
feature-specific port translation lives in application adapters with injected
neutral clients. Do not create empty layers, parallel `_shared`/`utils`, root
`integrations`/`extensions`, or one feature directory for every HTTP operation.
Cross-app callers use published commands/queries and receive DTOs or identifiers,
not foreign ORM instances or QuerySets. Application commands enforce resource
authorization even when called without HTTP.

## User-visible text and errors

- Write complete, concise sentences in sentence case, with consistent punctuation and terminology.
- Keep machine-readable error codes stable and distinct from display text. Define an explicit default user-facing message for every public code rather than relying on a mechanical code-to-text fallback.
- Avoid exposing raw exception text or internal details in client responses. Preserve structured validation fields instead of converting errors to a string.
- When translating text, use Django's translation utilities consistently and keep identifiers independent from translated labels.

## Tests and documentation

- Name pytest modules `test_<behavior_or_feature>.py`; name tests `test_<expected_behavior>`.
- Use markers to indicate a test's execution needs (database, live service, smoke environment). Directory names alone should not be treated as proof that a test is isolated or requires external services.
- Use lowercase kebab-case Markdown file names. Link to the canonical document rather than copying the same policy into multiple files.
- Record API, schema, and data-model decisions that constrain future changes, including deprecated aliases and planned removal conditions.

## Review checklist

Before merging new or renamed identifiers, verify:

1. Is the identifier internal, database-facing, persisted, or public to API clients?
2. Are model relations, filters, tasks, admin, migrations, OpenAPI, and clients affected?
3. Is a compatibility alias or deprecation period required?
4. Are behavior and schema covered by regression tests?
5. Do docs describe the canonical name and any retained legacy spelling?
