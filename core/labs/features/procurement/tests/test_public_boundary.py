"""Static tests for procurement feature layer boundaries and exports."""

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


def test_public_surface_exports_application_queries_and_exception():
    # Surface approved by the owner, including the purchase-draft workflow.
    assert _exports(FEATURE_ROOT / "public.py") == {
        "ProcurementCashFlowAggregate", "aggregate_procurement_cash_flow",
        "CreateDraftLineInput", "CreatePurchaseInput", "CreatePurchaseItemInput", "CreatePurchaseItemResourceInput",
        "CreatePurchaseTransactionInput", "DeleteDraftLineInput", "DraftLineInput", "PurchaseLineInput",
        "UpdateDraftLineInput", "UpdatePurchaseDraftInput",
        "create_draft_line", "create_purchase", "create_purchase_item", "create_purchase_item_resource",
        "create_purchase_transaction", "delete_draft_line", "item_etag", "purchase_etag", "update_draft_line",
        "update_purchase_draft",
        "get_purchase", "get_purchase_item", "list_purchase_item_resources", "list_purchase_items",
        "list_purchase_priorities", "list_purchase_transactions", "list_purchases",
    }


def test_api_adapters_use_public_and_have_no_direct_model_workflows():
    views = FEATURE_ROOT / "api" / "views.py"
    imports = _imports(views)
    source = views.read_text(encoding="utf-8-sig")
    assert "core.labs.features.procurement" in imports
    assert "core.labs.features.procurement.public" in imports
    # feature-template.md: any layer may import the feature's business exceptions.
    assert "core.labs.models" not in imports
    assert "public." in source
    assert "transaction.atomic" not in source
    assert "class PurchaseItemResourceListCreateAPIView" in source
    assert "class PurchaseTransactionListCreateAPIView" in source
    assert not source.startswith("from rest_framework.request import Request\nfrom rest_framework.response import Response\nfrom")


def test_layer_packages_have_explicit_exports():
    application = {
        "CreateDraftLineInput", "CreatePurchaseInput", "CreatePurchaseItemInput", "CreatePurchaseItemResourceInput",
        "CreatePurchaseTransactionInput", "DeleteDraftLineInput", "DraftLineInput", "PurchaseLineInput",
        "UpdateDraftLineInput", "UpdatePurchaseDraftInput",
        "create_draft_line", "create_purchase", "create_purchase_item", "create_purchase_item_resource",
        "create_purchase_transaction", "delete_draft_line", "item_etag", "purchase_etag", "update_draft_line",
        "update_purchase_draft",
    }
    assert _exports(FEATURE_ROOT / "application" / "__init__.py") == application
    # The facade may only re-export what commands.py declares.
    assert set(_exports(FEATURE_ROOT / "application" / "commands.py")) == application
    selectors = {
        "get_purchase", "get_purchase_item", "list_purchase_item_resources", "list_purchase_items",
        "list_purchase_priorities", "list_purchase_transactions", "list_purchases",
    }
    assert set(_exports(FEATURE_ROOT / "queries" / "selectors.py")) == selectors
    assert _exports(FEATURE_ROOT / "queries" / "__init__.py") == selectors | {
        "ProcurementCashFlowAggregate", "aggregate_procurement_cash_flow",
    }


def test_exception_contract_is_stable_and_implementation_free():
    exceptions = FEATURE_ROOT / "exceptions.py"
    assert _exports(exceptions) == {
        "PurchaseAllocationConflict", "PurchaseDraftConflict", "PurchaseDraftValidationFailed",
        "PurchaseETagRequired", "PurchaseMachineWriteForbidden", "PurchaseNotFound", "PurchasePreconditionFailed",
    }
    assert not any(".application" in module or ".queries" in module for module in _imports(exceptions))


def test_commands_have_frozen_inputs_and_keyword_only_actor():
    commands = _module(FEATURE_ROOT / "application" / "commands.py")
    classes = [node for node in commands.body if isinstance(node, ast.ClassDef)]
    assert {node.name for node in classes} == {
        "CreateDraftLineInput", "CreatePurchaseInput", "CreatePurchaseItemInput", "CreatePurchaseItemResourceInput",
        "CreatePurchaseTransactionInput", "DeleteDraftLineInput", "DraftLineInput", "PurchaseLineInput",
        "UpdateDraftLineInput", "UpdatePurchaseDraftInput",
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
    assert {node.name for node in functions} >= {
        "create_purchase", "create_purchase_item", "create_purchase_item_resource", "create_purchase_transaction",
    }
    for function in functions:
        if function.name.startswith(("create_", "update_", "delete_")):
            assert "actor" in [argument.arg for argument in function.args.kwonlyargs]
