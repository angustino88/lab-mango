"""Static tests for the agents feature's supported import boundary."""

import ast
from pathlib import Path

FEATURE_ROOT = Path(__file__).resolve().parents[1]


def test_public_exports_agent_operations_and_types():
    source = ast.parse((FEATURE_ROOT / "public.py").read_text(encoding="utf-8"))
    exported = next(
        ast.literal_eval(node.value)
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    assert set(exported) == {
        "AgentEnrollmentConflict",
        "AgentProofInvalid",
        "CreateEnrollmentGrantInput",
        "EnrollAgentInput",
        "EnrollmentGrantInvalid",
        "EnrollmentGrantIssued",
        "create_enrollment_grant",
        "enroll_agent",
        "revoke_enrollment_grant",
        "require_active_agent_identity",
        "transition_agent_state",
    }


def test_agent_commands_have_transactions_and_no_transport_imports():
    application = FEATURE_ROOT / "application.py"
    tree = ast.parse(application.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module is not None
        and ("rest_framework" in node.module or ".api" in node.module)
        for node in ast.walk(tree)
    )
    commands = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {
        "create_enrollment_grant",
        "enroll_agent",
        "revoke_enrollment_grant",
        "transition_agent_state",
        "require_active_agent_identity",
    } <= commands.keys()
    assert all(
        any(
            isinstance(decorator, ast.Attribute) and decorator.attr == "atomic"
            for decorator in commands[name].decorator_list
        )
        for name in (
            "create_enrollment_grant",
            "enroll_agent",
            "revoke_enrollment_grant",
            "transition_agent_state",
            "require_active_agent_identity",
        )
    )
