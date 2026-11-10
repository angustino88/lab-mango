# Feature Template Specification

Canonical **target standard** for new and rebuilt business features under `core/`.
Existing features remain transitional until acceptance; documentation is not runtime certification.

## Authority and compatibility

This document owns feature structure, boundaries, public interfaces, transport wiring and test ownership.
Other documents reference it rather than define alternative templates:
[core architecture](core-architecture.md) owns placement/rollout,
[model conventions](../conventions/django-models.md) persistence, and
[API contracts](../api/contracts.md) HTTP runtime/schema rules. Historical proposals do not override it.
`MUST` is mandatory; optional modules need justification. Deviations record scope, rationale, tests and migration/removal conditions.
Preserve deployed routes, payloads, task names, model imports and migration history until an approved migration.
Path alignment never justifies database resets; migration baselines require a separately approved isolated rebuild/cutover.

## 1. Where a feature sits

`core/<domain>/models/<feature>/` owns persistent truth and intrinsic invariants;
`core/<domain>/features/<feature>/` owns use cases. Matching names identify ownership.
Models stay centralized per Django app for discovery/migrations: each concrete model has one feature owner;
shared abstract/reference concepts have an app owner. Document transitional singular/nested paths.
The domain URL aggregator includes feature facades (current Labs: `api_urls.py`).

## 2. Final structure

```text
core/<domain>/features/<feature>/
├── __init__.py                       # empty, import-safe
├── public.py                         # explicit external exports; leaf facade
├── urls.py                           # re-exports urlpatterns from api/urls.py; leaf facade
├── contracts.py                      # frozen DTOs, Protocol ports, event types
├── exceptions.py                     # stable business errors, no HTTP concepts
├── tasks.py                          # optional thin background entry point
├── handlers.py                       # optional thin event entry point
├── api                               # HTTP package
│   ├── urls.py                       # routes
│   ├── views.py                      # thin HTTP adapters
│   ├── serializers.py                # payload shape and output
│   ├── filters.py                    # list filtering
│   ├── permissions.py                # optional policy wrappers
│   └── schema.py                     # optional HTTP contracts
├── application.py                    # small layout: commands, inputs, boundary
├── application                       # split layout (use instead of application.py)
│   ├── __init__.py                   # exports commands and their inputs
│   ├── <verb>_<entity>.py            # one command, frozen input, atomic boundary
│   ├── policies.py                   # optional, justified
│   ├── repositories.py               # optional, justified
│   └── adapters.py                   # optional, justified
├── queries.py                        # small layout: selectors
├── queries                           # split layout (use instead of queries.py)
│   ├── __init__.py                   # exports selectors
│   └── <verb>_<entity>.py            # read-only selectors and projections
├── tests                           # split layout (use instead of queries.py)
│   ├── conftest.py                   # fixtures
│   ├── factories.py                  # data factories
│   ├── test_public.py                # public export tests
│   ├── api                           # HTTP tests (split layout)
│   ├── application                   # command tests (split layout)
│   ├── queries                       # selector tests (split layout)
│   ├── test_application.py           # small layout command tests
│   ├── test_queries.py               # small layout selector tests
└── docs                              # documents
    └── architecture.md               # feature-specific design
```

## 3. Dependency rules

1. **Downward only:** mutually independent `api` / `tasks` / `handlers` call `application` or `queries`;
   application calls queries/models; queries read models. No upward imports or internal imports of root facades.
2. **Public surface:** logic-free `public.py` explicitly exports commands, inputs, queries and necessary exception types
   via `__all__`; no API/URL imports. Cross-feature behavior uses only `public.py`, shared types only `contracts.py`.
   Other private layers and exception modules are forbidden. Cross-domain results are named DTO projections, never ORM models.
3. **Persistence edges:** same-app cross-owner reads need documented dependencies; writes use the owner's public command.
   Cross-app ORM imports are forbidden except configured actor relations and approved string FKs, not command APIs.
4. **Acyclic ownership:** record feature/model owners and reviewed edges; ports do not remove runtime cycles.
   Events or a higher workflow owner resolve bidirectional behavior. Labs reporting → operations → assets → foundation
   remains a design guide until assignments and edges are reviewed.
5. **Neutral boundaries:** contracts contain types only and import only stdlib/neutral `core.common` contracts;
   no ORM, settings, frameworks, SDKs, adapters or feature layers. Any layer may import contracts/business exceptions.
6. **Infrastructure:** application/queries/models import no concrete infrastructure or SDKs. Neutral technical adapters
   live in `core.infrastructure` and depend only on neutral contracts; common imports no domain/infrastructure.
   Feature translation belongs in `application/adapters.py`; `config` resolves implementations and injects typed ports/clients.
   No domain dotted-path resolution or global service locator; infrastructure imports no business app.
7. **Models:** no feature, API, task, settings-adapter, DRF, Celery or Channels imports.

## 4. Responsibilities and boundaries

- **HTTP:** serializers validate payload shape/map output; views call one command/query, with no ad hoc queries,
  transactions, rules or catches of feature errors. API may import its own API modules, lower layers and models for serializers.
  Filters only filter list querysets; permission wrappers delegate to application policies. HTTP schema contracts must not duplicate runtime definitions.
- **Commands:** every write, including admin/jobs/scripts, MUST enter an application command with a frozen input and
  keyword-only `actor`. The command gathers facts, enforces policy and owns atomic persistence; no HTTP/DRF dependencies.
  Record external workflow intent first; network calls run outside the transaction, never while holding database locks.
- **Policies:** pure authorization/eligibility functions return `can_*` booleans or raise through `ensure_*`;
  no queries or sibling-command imports. Commands gather facts; policies decide. Visibility belongs in queries, invariants in models.
- **Persistence:** plain CRUD uses managers; repositories require real aggregate invariants/substitution needs, not generic wrappers.
  Back races with constraints/locking; earlier visibility reads are not race guards. Explicitly test validation:
  `save()` does not invoke `clean()`/`full_clean()`. Normalize classified constraint failures after rollback; preserve unrelated failures.
- **Actors:** neutral `core.common.contracts` context carries stable ID, principal kind and capabilities/scope;
  identity adapters construct it. Commands depend on neither requests nor User models. System/API-key actors are scoped,
  never a `None` bypass. Preserve legacy model stamping through explicit persistence translation until migrated.
- **Queries:** read-only, side-effect-free selectors compose reusable manager/QuerySet filters and apply actor visibility.
  Return models/querysets or bounded projections; required singles raise `<Entity>NotFound`. No application/policy imports,
  workflow locks or provider calls; remote reconciliation is a command. Test optimized lists against query budgets.
- **Errors:** stable codes subclass target `core.common.domain.errors`; target `core.common.api` maps them to HTTP.
  This hierarchy/mapping still requires foundation implementation and tests, not an assumption of existing support.
- **Events:** handlers call commands, never implicit `post_save` workflows. Best-effort dispatch uses `transaction.on_commit`;
  required delivery persists an outbox in the command transaction with retryable dispatch and idempotent consumers.
  `on_commit` alone is not durable. Tasks accept IDs/DTOs, not requests/models, and have idempotent retries.

## 5. Layout sizing and naming

- Default to small `application.py` / `queries.py`; consider splitting around 150 lines or four use cases, by cohesion rather than automatic counts.
  Optional policies/repositories/adapters live inside split application. Both forms preserve application/query import surfaces.
- `<verb>_<entity>.py` contains the matching callable; closely related commands sharing a policy may use a capability module.
  Inputs are frozen dataclasses beside commands, not serializers/contracts. Single-use code stays with its caller.
- Use plural snake_case capabilities; mass nouns and established integration keys are valid. List selectors use plural names;
  HTTP segments may be kebab-case. Ban `helpers`, `misc`, `shared`, `utils`; name the capability instead.
- Rooms/stations/equipment variants stay within canonical layers, not secondary `extensions`/`integrations` feature trees.
  Category metadata stays beside its consuming layer; neutral business metadata has a named app owner. Roots contain only documented entries.

## 6. Tests

Feature-only tests/fixtures/factories live in feature `tests/` and mirror source; small layouts use root application/query test files.
Test public exports/signatures/DTOs, HTTP status/serialization/permissions, real-database commands, pure policies and selector query counts.
Top-level suites own cross-feature/app integration, architecture, configuration and deployment; domain tests own model integrity/registration.
Neutral fixtures live in `core/common/testing`; migrate feature-only suites with their slice and configure both collection locations.
Architecture checks may inspect private layers; import checks cannot replace authorization, concurrency, rollback or durability tests.

## 7. Routes and registration

Target: project URLconf → domain URL aggregator → feature `urls.py` → `api/urls.py`.
Features own resource paths (explicit paths or tested contract-aware routers); domain/project own prefixes.
Explicit includes are valid; `feature_urls()` is only a proposed convenience. No new version prefix/router is required.
Current Labs: `config/urls.py` → `config/api_router.py` → `core/labs/api_urls.py` → feature facades.
Preserve slashless `/api/labs/...` routes; do not add trailing-slash aliases. Test reverse names, shadowing, auth, slashes and OpenAPI ownership.
Re-export models from domain `models/__init__.py`; import handlers in `AppConfig.ready()` without startup database/provider calls.
App `tasks.py` explicitly imports enabled feature tasks for autodiscovery; test worker task names. Config owns queues/retries/limits/schedules and adapter composition.

## 8. Running the scaffolding script

Run from the repository root in PowerShell using the project's virtual environment.
Preview first:

```powershell
.\.venv\Scripts\python.exe .\scripts\scaffolding\scaffold_feature.py labs benches --entity bench --dry-run
```

After reviewing the preview, create the missing files:

```powershell
.\.venv\Scripts\python.exe .\scripts\scaffolding\scaffold_feature.py
```

Options:

- `<domain> <feature>`: bounded context and plural snake_case feature name.
- `--entity <name>` (required): singular snake_case name of the main aggregate.
- `--small`: single `application.py` and `queries.py` instead of packages.
- `--with <modules>`: `policies`, `repositories`, `adapters` (split layout only), `permissions`, `schema`, `tasks`, `handlers`.
- `--models`: also create `core/<domain>/models/<feature>/` and export the model.
- `--dry-run`: print the plan without writing files.

Existing files are never overwritten. The only files it edits are `core/<domain>/urls.py`
(adds the feature) and `core/<domain>/models/__init__.py` (with `--models`). It prints the remaining manual steps,
such as model export, task and handler registration, and import-linter rules.

## 9. Acceptance and adoption

- [ ] Canonical layout, justified optional modules, explicit model ownership/transitional mapping and Django discovery.
- [ ] Downward/public/neutral boundaries, reviewed acyclic dependencies, approved read/FK edges and exact supported exports/DTOs.
- [ ] Every write has a command owner, scoped actor/policy, atomic persistence and constrained/locked race-sensitive invariants.
- [ ] Named reusable reads; thin HTTP adapters; tests for visibility, denied writes, DTOs, rollback, races and query budgets.
- [ ] URL/task/handler registration and idempotency/durability tests; runtime routes and regenerated OpenAPI agree.
- [ ] Available architecture checks, migration drift checks, tests and lint pass; missing enforcement is explicitly tracked.
- [ ] Compatibility decisions, deviations and current-to-target mappings recorded under the [phased rollout](core-architecture.md#12-rebuild-sequence).

Existing architecture checks cover selected boundaries, not full compliance. Full layer/DAG enforcement,
actor/error foundations, composition and required durable delivery remain implementation work where absent.
Adoption migrates internal facade callers/tests and legacy service/selector/nested/API workflows together, preserving behavior.
This document does not refactor runtime code, enable routes, reset migrations or certify production readiness; placeholders do not pass acceptance.
