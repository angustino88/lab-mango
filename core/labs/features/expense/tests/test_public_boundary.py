"""Static boundary tests for the expense feature layers."""

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
    return {
        node.module
        for node in ast.walk(_module(path))
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0
    }


def test_public_surface_exports_commands_queries_and_exception():
    assert _exports(FEATURE_ROOT / "public.py") == {
        "ExpenseCashFlowAggregate",
        "aggregate_expense_cash_flow",
        "CreateExpenseInput",
        "CreateExpensePaymentInput",
        "ExpenseConflict",
        "create_expense",
        "create_expense_payment",
        "get_financial_report",
        "list_expense_payments",
        "list_room_expenses",
    }


def test_api_adapters_use_public_and_have_no_direct_model_workflows():
    views = FEATURE_ROOT / "api" / "views.py"
    imports = _imports(views)
    source = views.read_text(encoding="utf-8-sig")
    assert "core.labs.features.expense.public" in imports
    assert "core.labs.models" not in imports
    assert "transaction.atomic" not in source
    assert "public." in source


def test_exception_contract_is_stable_and_implementation_free():
    exceptions = FEATURE_ROOT / "exceptions.py"
    assert _exports(exceptions) == {"ExpenseConflict"}
    assert not any(".application" in module or ".queries" in module for module in _imports(exceptions))


def test_commands_have_frozen_inputs_and_keyword_only_actor():
    commands = _module(FEATURE_ROOT / "application" / "commands.py")
    classes = [node for node in commands.body if isinstance(node, ast.ClassDef)]
    assert {node.name for node in classes} == {"CreateExpenseInput", "CreateExpensePaymentInput"}
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
    assert {node.name for node in functions} >= {"create_expense", "create_expense_payment"}
    for function in functions:
        if function.name.startswith("create_"):
            assert "actor" in [argument.arg for argument in function.args.kwonlyargs]
