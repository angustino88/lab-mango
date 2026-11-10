import copy
import json
from io import StringIO
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from drf_spectacular.generators import SchemaGenerator

from core.common.management.commands.spectacular_modules import Command


@pytest.fixture
def generated_schema(monkeypatch):
    schema = {
        "openapi": "3.0.3",
        "info": {"title": "Synthetic test API", "version": "1.0.0"},
        "paths": {
            "/items/a~b": {
                "get": {
                    "operationId": "items_retrieve",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item~1Name~0"}}},
                        }
                    },
                    "security": [{"bearerAuth": []}],
                }
            }
        },
        "components": {
            "schemas": {
                "Item/Name~": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/components/schemas/Item~1Name~0"}},
                }
            },
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        },
    }
    monkeypatch.setattr(SchemaGenerator, "get_schema", lambda self, request, public: copy.deepcopy(schema))
    monkeypatch.setattr(Command, "_registered_module_prefixes", lambda self: [("/items", "items.yml")])
    return schema


def _snapshot(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir() if path.is_file()}


def test_check_passes_repeatedly_without_writes_and_ignores_only_catalog_timestamp(tmp_path, generated_schema):
    call_command("spectacular_modules", output_dir=tmp_path, full_file="merged.yaml")
    catalog_path = tmp_path / "api-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["generated_at"] = "synthetic-old-timestamp"
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    (tmp_path / "README.md").write_text("keep", encoding="utf-8")
    before = _snapshot(tmp_path)
    for _ in range(2):
        stdout = StringIO()
        call_command("spectacular_modules", output_dir=tmp_path, full_file="merged.yaml", check=True, stdout=stdout)
        assert "Verified 6 generated OpenAPI files; no files were written." in stdout.getvalue()
    assert _snapshot(tmp_path) == before


def test_check_reports_missing_extra_and_changed_files_without_writes(tmp_path, generated_schema):
    call_command("spectacular_modules", output_dir=tmp_path)
    (tmp_path / "items.yml").unlink()
    (tmp_path / "old.yaml").write_text("stale", encoding="utf-8")
    (tmp_path / "old.json").write_text("{}", encoding="utf-8")
    (tmp_path / "openapi-full.json").write_text("{}", encoding="utf-8")
    (tmp_path / "components.yml").write_text("components: {}\n", encoding="utf-8")
    before = _snapshot(tmp_path)
    with pytest.raises(CommandError) as error:
        call_command("spectacular_modules", output_dir=tmp_path, check=True)
    assert str(error.value).splitlines()[1:] == [
        "Missing: items.yml",
        "Extra: old.json, old.yaml",
        "Changed: components.yml, openapi-full.json",
    ]
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("content", ["{invalid", "[]", '{"generated_at": "ignored", "endpoints": []}'])
def test_check_rejects_invalid_or_changed_catalog_content(tmp_path, generated_schema, content):
    call_command("spectacular_modules", output_dir=tmp_path)
    (tmp_path / "api-catalog.json").write_text(content, encoding="utf-8")
    before = _snapshot(tmp_path)
    with pytest.raises(CommandError, match="Changed: api-catalog.json"):
        call_command("spectacular_modules", output_dir=tmp_path, check=True)
    assert _snapshot(tmp_path) == before


def test_check_does_not_ignore_nested_catalog_timestamp(tmp_path):
    expected = {"api-catalog.json": '{"generated_at": "now", "nested": {"generated_at": "expected"}}'}
    (tmp_path / "api-catalog.json").write_text(
        '{"generated_at": "old", "nested": {"generated_at": "changed"}}', encoding="utf-8"
    )
    with pytest.raises(CommandError, match="Changed: api-catalog.json"):
        Command._check_documents(tmp_path, expected)


def test_check_missing_directory_reports_all_expected_files_without_creating_it(tmp_path, generated_schema):
    output = tmp_path / "absent"
    with pytest.raises(
        CommandError, match="Missing: api-catalog.json, components.yml, items.yml, openapi-full.json, openapi.yml"
    ):
        call_command("spectacular_modules", output_dir=output, check=True)
    assert not output.exists()


@pytest.mark.parametrize("option", ["dry_run", "no_clean"])
def test_check_rejects_conflicting_options_before_generation(monkeypatch, tmp_path, option):
    def unexpected_generation(*args, **kwargs):
        pytest.fail("Conflicting check options must fail before schema generation")

    monkeypatch.setattr(SchemaGenerator, "get_schema", unexpected_generation)
    with pytest.raises(CommandError, match="cannot be combined"):
        call_command("spectacular_modules", output_dir=tmp_path, check=True, **{option: True})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mode", [{"check": True}, {"validate": True}, {"validate": True, "dry_run": True}])
def test_validation_rejects_invalid_schema_before_writes(tmp_path, generated_schema, mode):
    generated_schema["info"].pop("version")
    with pytest.raises(CommandError, match="OpenAPI schema validation failed for items.yml"):
        call_command("spectacular_modules", output_dir=tmp_path, **mode)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "ref",
    ["#/components/schemas/Missing", "https://example.invalid/schema.json#/Item", "./missing.yml#/Item"],
)
def test_validation_rejects_missing_and_remote_refs_without_writes(tmp_path, generated_schema, ref):
    generated_schema["components"]["schemas"]["Item/Name~"]["properties"]["child"]["$ref"] = ref
    with pytest.raises(CommandError, match="OpenAPI reference"):
        call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    assert not list(tmp_path.iterdir())


def test_validation_rejects_unknown_security_schemes(tmp_path, generated_schema):
    generated_schema["components"]["securitySchemes"] = {}
    with pytest.raises(CommandError, match="Unknown OpenAPI security scheme"):
        call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    assert not list(tmp_path.iterdir())


def test_validation_checks_pruned_module_schema_not_only_full_schema(tmp_path, generated_schema, monkeypatch):
    original = Command._build_module_schema

    def broken_module(self, schema, paths):
        module = original(self, schema, paths)
        module["info"].pop("title")
        return module

    monkeypatch.setattr(Command, "_build_module_schema", broken_module)
    with pytest.raises(CommandError, match="OpenAPI schema validation failed for items.yml"):
        call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    assert not list(tmp_path.iterdir())


def test_validation_checks_master_cross_file_pointers(tmp_path, generated_schema, monkeypatch):
    original = Command._build_master_schema

    def broken_master(schema, modules, master_file):
        master = original(schema, modules, master_file)
        master["paths"]["/items/a~b"]["$ref"] = "./items.yml#/paths/missing"
        return master

    monkeypatch.setattr(Command, "_build_master_schema", staticmethod(broken_master))
    with pytest.raises(CommandError, match="Unresolved OpenAPI reference in openapi.yml"):
        call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    assert not list(tmp_path.iterdir())


def test_validate_dry_run_accepts_recursive_and_escaped_refs_without_writes(tmp_path, generated_schema):
    call_command("spectacular_modules", output_dir=tmp_path, validate=True, dry_run=True)
    assert not list(tmp_path.iterdir())


def test_validation_catches_refs_to_components_missing_only_from_module(tmp_path, generated_schema, monkeypatch):
    original = Command._build_module_schema

    def broken_module(self, schema, paths):
        module = original(self, schema, paths)
        module["components"]["schemas"] = {}
        return module

    monkeypatch.setattr(Command, "_build_module_schema", broken_module)
    with pytest.raises(CommandError, match="Unresolved OpenAPI reference in items.yml"):
        call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    assert not list(tmp_path.iterdir())


def test_check_compares_yaml_text_not_only_parsed_content(tmp_path, generated_schema):
    call_command("spectacular_modules", output_dir=tmp_path)
    path = tmp_path / "items.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    with pytest.raises(CommandError, match="Changed: items.yml"):
        call_command("spectacular_modules", output_dir=tmp_path, check=True)


def test_validate_generation_writes_files_that_pass_check(tmp_path, generated_schema):
    call_command("spectacular_modules", output_dir=tmp_path, validate=True)
    before = _snapshot(tmp_path)
    call_command("spectacular_modules", output_dir=tmp_path, check=True)
    assert _snapshot(tmp_path) == before


def test_api_workflow_covers_sources_and_preserves_existing_lint_gates():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows/api-lint.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    required_paths = {
        "openapi/**",
        "core/**",
        "config/**",
        "packages/drf-api-contracts/**",
        "tests/unit/test_openapi*.py",
        "conftest.py",
        "manage.py",
        "pyproject.toml",
        "uv.lock",
        ".spectral.yaml",
        ".github/workflows/api-lint.yml",
    }
    for event in ("pull_request", "push"):
        assert required_paths <= set(workflow["on"][event]["paths"])
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["openapi"]
    assert job["env"]["DJANGO_SETTINGS_MODULE"] == "config.settings.test"
    assert job["env"]["DJANGO_READ_DOT_ENV_FILE"] == "False"
    assert {"DATABASE_URL", "CELERY_BROKER_URL", "DJANGO_SECRET_KEY"} <= job["env"].keys()
    assert "services" not in job
    steps = job["steps"]
    assert any(
        step.get("uses") == "actions/setup-python@v5" and step["with"]["python-version"] == "3.12" for step in steps
    )
    assert any(step.get("uses") == "astral-sh/setup-uv@v5" for step in steps)
    assert [step["run"] for step in steps if "run" in step] == [
        "uv sync --frozen",
        "uv run pytest tests/unit/test_openapi*.py core/common/openapi/tests -q --ds=config.settings.test",
        "uv run python manage.py spectacular_modules --output-dir openapi --check --settings=config.settings.test",
    ]
    assert [step["run"] for step in workflow["jobs"]["spectral"]["steps"] if "run" in step] == [
        "npx --yes @redocly/cli@1.34.21 bundle openapi/openapi.yml -o build/openapi.bundled.yml",
        "npx --yes @stoplight/spectral-cli@6.17.0 lint build/openapi.bundled.yml --ruleset .spectral.yaml --fail-severity=error",
    ]
