"""Architecture guardrails for Labs features."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = PROJECT_ROOT / "core"


def _production_python_files(package_path: Path):
    excluded_directories = {"__pycache__", "migrations", "tests"}
    if not package_path.exists():
        return
    for path in package_path.rglob("*.py"):
        if not excluded_directories.intersection(path.relative_to(package_path).parts[:-1]):
            yield path


def _imported_modules(source_path: Path):
    source = source_path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(source, filename=str(source_path))
    except Exception:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
        elif isinstance(node, ast.ImportFrom) and node.level > 0:
            if node.module:
                yield "RELATIVE." + node.module
            else:
                for alias in node.names:
                    yield "RELATIVE." + alias.name


def test_queries_do_not_import_application():
    violations = []
    for path in _production_python_files(CORE_ROOT / "labs"):
        if "queries" in path.parts:
            for imp in _imported_modules(path):
                if "application" in imp:
                    violations.append(str(path.relative_to(PROJECT_ROOT)) + " imports " + imp)

    assert not violations, "Query-to-application dependency violations:\n" + "\n".join(violations)


def test_features_do_not_import_config():
    allowlist = {
        "core\\labs\\features\\analytics\\api\\finance\\schema.py",
    }
    violations = []
    for path in _production_python_files(CORE_ROOT / "labs"):
        for imp in _imported_modules(path):
            if imp.startswith("config.") or imp == "config":
                rel = str(path.relative_to(PROJECT_ROOT))
                if rel not in allowlist:
                    violations.append(rel + " imports " + imp)

    assert not violations, "Feature imports of config violations:\n" + "\n".join(violations)


def test_routing_tables_have_one_production_writer():
    """Only the routing publisher may mutate routing stream models in Python source.

    This static guard does not detect dynamic model access, raw SQL, external scripts,
    or writers outside this repository; those require separate inventory and reconciliation.
    """
    model_names = {"SyncState", "RoutingEntity", "RoutingChange"}
    allowed_writer = PROJECT_ROOT / "core/routing/application/publish.py"
    write_methods = {"create", "get_or_create", "update_or_create", "bulk_create", "bulk_update", "update", "delete"}
    violations = []

    for path in _production_python_files(CORE_ROOT):
        relative_path = path.relative_to(PROJECT_ROOT)
        if path == allowed_writer:
            continue
        source = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{relative_path}: cannot parse file for routing write audit: {exc}")
            continue

        violations.extend(_routing_write_violations(tree, relative_path, model_names, write_methods))

    assert not violations, "Routing stream writes must go through the publisher:\n" + "\n".join(violations)


def _routing_write_violations(tree, relative_path, model_names, write_methods):
    model_aliases = set()
    module_aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in model_names and node.module in {
                    "core.labs.models",
                    "core.labs.models.routing",
                    "core.routing.models",
                }:
                    model_aliases.add(alias.asname or alias.name)
                elif alias.name == "routing" and node.module and (node.module.startswith("core.labs.models") or node.module.startswith("core.routing")):
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    alias.name == "core.labs.models"
                    or alias.name.startswith("core.labs.models.routing")
                    or alias.name == "core.routing.models"
                    or alias.name.startswith("core.routing.models")
                ):
                    module_aliases.add(alias.asname or alias.name)

    def references_routing_model(expression):
        if isinstance(expression, ast.Name):
            return expression.id in model_aliases
        if isinstance(expression, ast.Attribute):
            if expression.attr in model_names and isinstance(expression.value, ast.Name):
                return expression.value.id in module_aliases
            return references_routing_model(expression.value)
        if isinstance(expression, ast.Call):
            return references_routing_model(expression.func)
        return False

    instance_names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None or not isinstance(value, ast.Call) or not references_routing_model(value.func):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            instance_names.update(target.id for target in targets if isinstance(target, ast.Name))

    def receiver_is_routing(expression):
        if isinstance(expression, ast.Name):
            return expression.id in instance_names
        if isinstance(expression, ast.Attribute):
            return references_routing_model(expression) or receiver_is_routing(expression.value)
        if isinstance(expression, ast.Call):
            return isinstance(expression.func, ast.Attribute) and receiver_is_routing(expression.func.value)
        return False

    return [
        f"{relative_path}:{node.lineno} writes a routing model outside the publisher"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in write_methods | {"save"}
        and receiver_is_routing(node.func.value)
    ]


def test_routing_writer_guard_detects_common_orm_write_shapes():
    """Keep the static guard sensitive to regular ORM operations and import aliases."""
    source_examples = (
        (
            "from core.labs.models.routing import RoutingEntity; RoutingEntity.objects.filter(pk=1).update(state='active')",
            "update",
        ),
        (
            "from core.labs.models.routing import RoutingEntity as RE; RE.objects.get(pk=1).delete()",
            "delete",
        ),
        ("from core.labs.models import routing as models; models.RoutingEntity.objects.create()", "create"),
        ("from core.labs.models.routing import RoutingEntity; entity = RoutingEntity(); entity.save()", "save"),
        ("from core.labs.models import RoutingEntity as Route; Route.objects.create()", "create"),
        ("from core.labs.models import RoutingEntity; RoutingEntity.objects.filter(pk=1).update()", "update"),
        ("import core.labs.models.routing as route_models; route_models.RoutingEntity.objects.create()", "create"),
    )
    for source, expected_method in source_examples:
        tree = ast.parse(source)
        detected = _routing_write_violations(
            tree,
            Path("fixture.py"),
            {"SyncState", "RoutingEntity", "RoutingChange"},
            {"create", "get_or_create", "update_or_create", "bulk_create", "bulk_update", "update", "delete"},
        )
        assert len(detected) == 1
        write_call = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == expected_method
        )
        assert detected[0].endswith(f":{write_call.lineno} writes a routing model outside the publisher")

    harmless_construction = ast.parse("from core.labs.models.routing import RoutingEntity; entity = RoutingEntity()")
    assert not _routing_write_violations(
        harmless_construction,
        Path("fixture.py"),
        {"SyncState", "RoutingEntity", "RoutingChange"},
        {"create", "get_or_create", "update_or_create", "bulk_create", "bulk_update", "update", "delete"},
    )


def test_routing_writer_guard_finds_known_writer_file():
    publisher = PROJECT_ROOT / "core/routing/application/publish.py"
    assert publisher.is_file()
