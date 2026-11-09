"""Static boundary tests for the resource audit feature layers."""

import ast
from pathlib import Path

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _exports(path: Path) -> set[str]:
    for node in _module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"{path} must declare __all__")


def _imports(path: Path) -> set[str]:
    """Absolute modules imported, counting ``from pkg import module`` as ``pkg.module``."""
    modules: set[str] = set()
    for node in ast.walk(_module(path)):
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_public_surface_exports_commands_queries_and_exceptions():
    assert _exports(FEATURE_ROOT / "public.py") == {
        "AuditPermissionDeniedError",
        "InvalidAuditResultError",
        "RecordAuditByIdInput",
        "RecordAuditBySkuInput",
        "RecordAuditByUidInput",
        "RecordResourceAuditInput",
        "ResourceAuditError",
        "ResourceAuditNotFoundError",
        "ResourceNotFoundError",
        "UpdateResourceAuditInput",
        "delete_resource_audit",
        "get_audit_result_options",
        "get_latest_audit_by_resource",
        "get_resource_audit",
        "list_all_resource_audits",
        "list_audits_by_id",
        "list_audits_by_sku",
        "list_audits_by_uid",
        "list_audits_for_resource",
        "record_audit_by_id",
        "record_audit_by_sku",
        "record_audit_by_uid",
        "record_resource_audit",
        "resolve_resource",
        "update_resource_audit",
    }


def test_api_adapters_use_public_and_have_no_direct_model_workflows():
    views = FEATURE_ROOT / "api" / "views.py"
    imports = _imports(views)
    source = views.read_text(encoding="utf-8-sig")
    assert "core.labs.features.resource_audit.public" in imports
    assert "core.labs.models" not in imports
    assert "transaction.atomic" not in source
    assert "public." in source


def test_exception_contract_is_stable_and_implementation_free():
    exceptions = FEATURE_ROOT / "exceptions.py"
    assert _exports(exceptions) == {
        "AuditPermissionDeniedError",
        "InvalidAuditResultError",
        "ResourceAuditError",
        "ResourceAuditNotFoundError",
        "ResourceNotFoundError",
    }
    assert not any(".application" in module or ".queries" in module for module in _imports(exceptions))


def test_commands_have_frozen_inputs_and_keyword_only_actor():
    commands = _module(FEATURE_ROOT / "application" / "commands.py")
    classes = [node for node in commands.body if isinstance(node, ast.ClassDef)]
    assert {node.name for node in classes} == {
        "RecordResourceAuditInput",
        "RecordAuditByIdInput",
        "RecordAuditBySkuInput",
        "RecordAuditByUidInput",
        "UpdateResourceAuditInput",
    }
    for cls in classes:
        assert any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "dataclass"
            and any(
                keyword.arg == "frozen" and isinstance(keyword.value, ast.Constant) and keyword.value.value
                for keyword in decorator.keywords
            )
            for decorator in cls.decorator_list
        )

    functions = [node for node in commands.body if isinstance(node, ast.FunctionDef)]
    command_fn_names = {
        f.name
        for f in functions
        if f.name.startswith("record_") or f.name.startswith("update_") or f.name.startswith("delete_")
    }
    assert command_fn_names >= {
        "record_resource_audit",
        "record_audit_by_id",
        "record_audit_by_sku",
        "record_audit_by_uid",
        "update_resource_audit",
        "delete_resource_audit",
    }
    for function in functions:
        if function.name in command_fn_names:
            assert "actor" in [argument.arg for argument in function.args.kwonlyargs]
