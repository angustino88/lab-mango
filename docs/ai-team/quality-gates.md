# Quality Gates

Owner of verification commands. Run every gate whose "When" matches the change and report each as
**passed / failed / not run** with the exact command (AGENTS.md rule 8). Commands run from the repository
root with the project virtualenv (`uv run ...`, or `.venv/Scripts/python.exe` on Windows).

## Configured gates
| Gate | Command | When | In CI |
|---|---|---|---|
| Lint, changed files | `uv run ruff check <changed paths>` | every Python change | only `core/users`, `config/settings/base.py`, `config/urls.py`, `tests/architecture` |
| Format, changed files | `uv run ruff format --check <changed paths>` | every Python change | no |
| Types, changed files | `uv run mypy <changed paths>` | every Python change | no |
| Focused tests | `uv run pytest <feature>/tests -q` | every behavior change, first | full suite in `.github/workflows/ci.yml` |
| Architecture tests | `uv run pytest tests/architecture -q` | any import or new module | yes |
| Missing migrations | `uv run python manage.py makemigrations --check --dry-run` | models touched | yes |
| Deploy check | `uv run python manage.py check --deploy` with `DJANGO_SETTINGS_MODULE=config.settings.production` | settings, auth, middleware touched | yes |
| OpenAPI regenerate | `uv run python manage.py spectacular_modules --output-dir openapi` | API, serializer, or schema touched | no |
| OpenAPI tests | `uv run pytest tests/unit/test_openapi*.py core/common/openapi/tests -q --ds=config.settings.test` | API/schema sources, generator, contracts package, or OpenAPI tooling changed | `.github/workflows/api-lint.yml` |
| OpenAPI parity + validation | `uv run python manage.py spectacular_modules --output-dir openapi --check --settings=config.settings.test` | API/schema sources, generator, contracts package, dependencies, or generated files changed | `.github/workflows/api-lint.yml` |
| API contract gate | `uv run python -m core.common.openapi.contract_rules openapi/openapi-full.json` (CI runs it as `core/common/openapi/tests/test_contract_rules.py`) | API, serializer, or schema touched | `.github/workflows/api-lint.yml` (OpenAPI tests step) |
| API response contract (DOC-4) | runs inside every test via `conftest.py` (`openapi_response_contract`); report instead of failing with `RESPONSE_CONTRACT_REPORT=<file> uv run pytest -q` | API, serializer, view or schema touched | `.github/workflows/ci.yml` (Tests step, full suite) |
| Spectral | see `.github/instructions/api-design.instructions.md` step 5 | `openapi/` or API/schema sources changed | `.github/workflows/api-lint.yml` |

The API workflow runs from `.github/workflows/` and retains bundling and Spectral's error threshold.
Its Python job uses test settings, disables dotenv loading, and supplies synthetic `DJANGO_SECRET_KEY`,
`DATABASE_URL`, and `CELERY_BROKER_URL` configuration. Schema/tooling tests need no database or broker
service; any accidental database access fails under pytest-django.

`--check` generates in memory, validates schemas and offline references, then reports sorted missing,
extra, and changed top-level YAML/JSON files. It never writes or cleans the output directory, ignores
non-YAML/JSON files, and excludes only the catalog's root `generated_at` value from comparison. YAML
and full JSON use exact text comparison (with universal newline handling); catalog JSON compares parsed
content. `--check` cannot be combined with `--dry-run` or `--no-clean`.

Use `--validate` with normal generation or `--dry-run` for validation without parity checking. Validation
uses the installed `drf_spectacular.validation.validate_schema` and verifies JSON pointers offline;
remote/external references are rejected rather than fetched. Standalone modules and the full schema
are validated, while the split master is validated after resolving its path and root component links
in memory. The components fragment is checked through those schemas, not as a standalone OpenAPI
document. This does not replace Spectral, certify endpoint behavior, or validate example payloads.
If validation fails in existing feature schemas, report the constraint and fix it in a separate feature
change; do not weaken this gate. Regenerate and commit artifacts separately when parity fails.

## Not configured (report as "not run (not configured)"; do not add tooling inside a feature task)
`lint-imports` · `pip-audit` · `bandit` / `semgrep` · `gitleaks` · OpenAPI breaking-change diff against the base branch.

## Rules
- Lint and type-check only the paths you changed; the repository has a known Ruff backlog outside the CI scope.
  A pre-existing failure in an untouched line is reported as "pre-existing", not fixed.
- Run focused tests first, then the wider suite for the touched app.
- Report skipped and flaky tests with counts.
- Weakening a gate (new `# noqa`, `# type: ignore`, `pytest.skip`, `xfail`, lowered threshold, narrowed CI
  path) needs a stated reason in the handoff and owner approval.
