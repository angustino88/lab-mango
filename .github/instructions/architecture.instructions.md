---
applyTo: 'core/**/*.py,config/**/*.py'
---
# Import boundaries

Owner: `docs/architecture/feature-template.md` section 3. This file turns it into checks for every import you write.

## Before adding an import, check the target
| You are in | You may import | You may not import |
|---|---|---|
| Feature A (any layer) | Feature B's `public.py`, `contracts.py` | Feature B's `application`, `queries`, `api`, `exceptions.py`, `tasks.py` |
| Feature A `api/`, `tasks.py`, `handlers.py` | A's own `application`, `queries`, models | A's `public.py` (root facades are for other features) |
| `contracts.py` | stdlib, `core.common` contracts | ORM, settings, DRF, any feature layer |
| Models (`core/<domain>/models/`) | other models, `core.common` | features, DRF, Celery, Channels |
| `core.common`, `core.infrastructure` | stdlib, third-party | any business app (`core.labs`, `core.users`, `core.support_desk`, `core.agents`, `core.routing`, `core.websocket`) or `config` |

Example. Bad, in `core/labs/features/benches/application/services.py`:
`from core.labs.features.bench_bookings.queries import active_bookings_for_bench`.
Good: export a query from `bench_bookings/public.py` and import that.

- Cross-domain results are DTOs from `contracts.py`, never ORM instances.
- A new cross-feature edge is T2 (`AGENTS.md`). State the edge (`A → B.public.<name>`) in the handoff.
- If the needed function is not exported by B's `public.py`, adding the export is part of the change and
  updates B's `tests/test_public_boundary.py`.
- Reading another feature's model through the ORM (`from core.labs.models import BenchBooking` inside `benches`)
  is a cross-feature edge too: use the owner's query from `public.py` (`docs/architecture/feature-template.md` section 3, rule 3).
  Writes to another feature's model always go through the owner's command.
- Two features that need each other: one side publishes an event (outbox) or a higher workflow owner calls both.
  Never import in both directions, not even inside a function body to dodge the import cycle.

## Extending without editing (open for extension)
Adding a new variant (equipment category, resource type, notification channel) must not mean editing `if/elif`
chains across layers.
- Variants register in one declarative registry owned by the feature and are looked up by key
  (pattern: `EQUIPMENT_REGISTRY` / `get_equipment_definition` in `core/labs/features/equipment/api/registry.py`).
  A new variant = one registry entry + its model/serializer, plus a test that the registry resolves it.
- Behavior that differs per variant is a field or a small callable on the registry entry, not an
  `isinstance` / `type ==` branch in a command or view.
- Variants stay inside the feature's canonical layers, not in a parallel `extensions/` tree
  (`docs/architecture/feature-template.md` section 5).
- An external dependency (email, Teams, Jira, storage) is a `Protocol` port in `contracts.py` with an adapter in
  `application/adapters.py` or `core.infrastructure`, injected by `config` (`docs/architecture/feature-template.md` section 3,
  rule 6). Commands never import an SDK.

## Keeping modules small and replaceable
- Split `application.py` / `queries.py` into packages around 150 lines or four use cases
  (`docs/architecture/feature-template.md` section 5); one command per `<verb>_<entity>.py`.
- No generic base class, repository, or "manager of managers" until two real callers need it.
  Use the existing bases (`django-conventions.instructions.md` "HTTP base classes").
- Shared code moves to `core.common` only when it imports no business app and two features use it.

## Enforcement that exists today
- `tests/architecture/test_import_boundaries.py` (common/infrastructure isolation) and
  `tests/architecture/test_users_feature_boundaries.py`. Run `uv run pytest tests/architecture -q`.
- Per-feature `tests/test_public_boundary.py` pins each `public.py` export list.
- `lint-imports` is **not configured** in this repository; report it as "not run (not configured)".
  A new boundary rule is proposed together with an architecture test (template:
  `docs/ai-team/templates/importlinter.example.ini`).
