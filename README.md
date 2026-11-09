# LabMango Backend

Django 5.2 REST and WebSocket backend for LabMango. The codebase is a modular Django monolith with business features, domain-neutral common primitives, technical infrastructure adapters, and project configuration. Existing feature layouts are transitional; new and rebuilt features follow the [canonical feature template](docs/architecture/feature-template.md).

## Repository guide

- `core/labs/features/` — Labs feature behavior; persistence includes capabilities not yet exposed by active endpoints.
- `core/users/features/` — authentication, groups, and user profile workflows.
- `core/common/` — domain-neutral kernel, persistence primitives and shared API contracts.
- `core/infrastructure/` — technical/provider adapters; business workflows remain with features.
- `config/settings/` — local, test, and production settings.
- `tests/` — architecture, cross-feature integration and deployment suites in the target; existing feature-only suites move with their owning slice. Feature behavior tests live with features, model/wiring tests with apps.
- `docs/` — architecture, naming conventions, API response contracts, and feature guidance.

Start with the [feature standard](docs/architecture/feature-template.md), then the
[documentation index](docs/README.md) and [naming conventions](docs/conventions/naming.md).

## Development environment

The project requires Python 3.12 or newer and uses `uv` with the committed lockfile. On Windows, `setup_venv.py` bootstraps/synchronizes the local `.venv`; review that script's proxy settings for your network before running it. The Django test settings use a PostgreSQL test database; configure `DATABASE_URL` or use the documented local development environment before running tests.

After activating the environment, run the automated suite with:

```text
pytest
```

For API response envelopes and OpenAPI contracts, see [the API response contract guide](docs/api/contracts.md).

## Configuration and sensitive files

Use the environment examples and the approved local/production secret-management process. Do not commit credentials, private keys, production environment files, or runtime uploads. TLS certificates are deployment-managed assets; coordinate rotation and deployment before changing certificates used by production Nginx.

The root `test_email.py` is an explicit operational smoke script, not an automated test. It requires a recipient argument and reads the production Django environment file only when directly invoked. Use it only when authorized to send through the configured mail service.
