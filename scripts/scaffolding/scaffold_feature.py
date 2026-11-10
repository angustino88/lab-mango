"""Generate a feature skeleton from the standard feature template.

See docs/architecture/feature-template.md for the scope of every folder and file.

Run from the repository root (the folder that contains `core/`):

    python scripts/scaffolding/scaffold_feature.py labs benches --entity bench
    python scripts/scaffolding/scaffold_feature.py labs locations --entity location --small
    python scripts/scaffolding/scaffold_feature.py labs bookings --entity booking \\
        --with policies repositories permissions tasks handlers --models
    python scripts/scaffolding/scaffold_feature.py users profiles --entity profile --dry-run

Arguments:
    domain     bounded context: labs, users, jira_integration, notifications
    feature    plural snake_case feature name (URL prefix, list_<feature>)
    --entity   singular snake_case name of the main aggregate
    --small    single application.py / queries.py instead of packages
    --with     optional modules:
                 policies, repositories, adapters -> application/ (split layout only)
                 permissions, schema              -> api/permissions.py, api/schema.py
                 tasks, handlers                  -> feature root
    --models   also create core/<domain>/models/<feature>/ and export the model
               from core/<domain>/models/__init__.py

Also created or updated when missing:
    core/<domain>/urls.py   (feature_urls(...) aggregation; the feature is added)

Existing files are never overwritten; only the two files above are edited
(one appended line / one added feature name).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

OPTIONAL = ("policies", "repositories", "adapters", "permissions", "schema", "tasks", "handlers")
SPLIT_ONLY = {"policies", "repositories", "adapters"}
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")

# Tokens: {{domain}} {{feature}} {{entity}} {{Entity}}

# --------------------------------------------------------------------------
# Files identical in both layouts
# --------------------------------------------------------------------------
COMMON: dict[str, str] = {
    "__init__.py": "",
    "public.py": '''"""Supported command and query entry points for the {{feature}} feature.

Leaf module: nothing inside this feature imports it. Other features and domains
import this module or contracts.py, never internals.
"""

from .application import (
    Create{{Entity}}Input,
    Update{{Entity}}Input,
    create_{{entity}},
    delete_{{entity}},
    update_{{entity}},
)
from .queries import get_{{entity}}, list_{{feature}}

__all__ = (
    "Create{{Entity}}Input",
    "Update{{Entity}}Input",
    "create_{{entity}}",
    "delete_{{entity}}",
    "get_{{entity}}",
    "list_{{feature}}",
    "update_{{entity}}",
)
''',
    "urls.py": '''"""Feature URL entry point: only references the transport-level URL modules.

Leaf module: only the domain urls.py (via feature_urls) reads it.
"""
from .api.urls import urlpatterns

__all__ = ["urlpatterns"]
''',
    "contracts.py": '''"""Types only: DTOs, protocols (ports) and events shared across modules.

Callables belong in public.py. Command inputs stay next to their use case.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class {{Entity}}Ref:
    id: int
''',
    "exceptions.py": '''from core.common.domain.errors import ConflictError, NotFoundError


class {{Entity}}NotFound(NotFoundError):
    code = "{{entity}}_not_found"


class {{Entity}}Conflict(ConflictError):
    code = "{{entity}}_conflict"
''',
    "api/__init__.py": "",
    "api/urls.py": '''"""Resource routes owned by this feature. SimpleRouter: no per-feature API-root view."""
from rest_framework.routers import SimpleRouter

from .views import {{Entity}}ViewSet

router = SimpleRouter()
router.register(r"{{feature}}", {{Entity}}ViewSet, basename="{{entity}}")

urlpatterns = router.urls
''',
    "api/views.py": '''"""HTTP transport only: parse input, call a use case or query, map output."""
from rest_framework import status, viewsets
from rest_framework.response import Response

from ..application import (
    Create{{Entity}}Input,
    Update{{Entity}}Input,
    create_{{entity}},
    delete_{{entity}},
    update_{{entity}},
)
from ..queries import get_{{entity}}, list_{{feature}}
from .serializers import {{Entity}}Serializer


class {{Entity}}ViewSet(viewsets.ViewSet):
    def list(self, request):
        return Response({{Entity}}Serializer(list_{{feature}}(), many=True).data)

    def retrieve(self, request, pk=None):
        return Response({{Entity}}Serializer(get_{{entity}}(int(pk))).data)

    def create(self, request):
        serializer = {{Entity}}Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = create_{{entity}}(
            Create{{Entity}}Input(**serializer.validated_data), actor=request.user
        )
        return Response({{Entity}}Serializer(obj).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        serializer = {{Entity}}Serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        obj = update_{{entity}}(
            int(pk), Update{{Entity}}Input(**serializer.validated_data), actor=request.user
        )
        return Response({{Entity}}Serializer(obj).data)

    def destroy(self, request, pk=None):
        delete_{{entity}}(int(pk), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
''',
    "api/serializers.py": '''"""Input validation (shape of the payload) and output mapping. No business rules."""
from rest_framework import serializers

from core.{{domain}}.models.{{feature}} import {{Entity}}


class {{Entity}}Serializer(serializers.ModelSerializer):
    class Meta:
        model = {{Entity}}
        fields = ["id"]  # TODO: list fields explicitly
''',
    "api/filters.py": '''"""Query-string filters for the list endpoint (e.g. a django-filter FilterSet)."""
''',
    "tests/__init__.py": "",
    "tests/conftest.py": '''"""Fixtures for this feature's tests only."""
''',
    "tests/factories.py": '''"""Test data factories for this feature (e.g. factory_boy)."""
''',
    "tests/test_public.py": '''from .. import public


def test_public_exports_resolve():
    missing = [name for name in public.__all__ if not hasattr(public, name)]
    assert not missing, missing
''',
}

# --------------------------------------------------------------------------
# Split layout: application/ and queries/ packages, one use case per file
# --------------------------------------------------------------------------
SPLIT: dict[str, str] = {
    "application/__init__.py": '''from .create_{{entity}} import Create{{Entity}}Input, create_{{entity}}
from .delete_{{entity}} import delete_{{entity}}
from .update_{{entity}} import Update{{Entity}}Input, update_{{entity}}

__all__ = [
    "Create{{Entity}}Input",
    "Update{{Entity}}Input",
    "create_{{entity}}",
    "delete_{{entity}}",
    "update_{{entity}}",
]
''',
    "application/create_{{entity}}.py": '''from dataclasses import dataclass

from django.db import transaction

from core.{{domain}}.models.{{feature}} import {{Entity}}


@dataclass(frozen=True)
class Create{{Entity}}Input:
    pass  # TODO: command fields


@transaction.atomic
def create_{{entity}}(data: Create{{Entity}}Input, *, actor) -> {{Entity}}:
    """Write use case: owns the transaction, policy checks and event emission."""
    # 1. policies.ensure_can_create(actor)
    # 2. change data
    # 3. transaction.on_commit(...) to emit the event
    raise NotImplementedError
''',
    "application/update_{{entity}}.py": '''from dataclasses import dataclass

from django.db import transaction

from core.{{domain}}.models.{{feature}} import {{Entity}}

from ..queries import get_{{entity}}


@dataclass(frozen=True)
class Update{{Entity}}Input:
    pass  # TODO: command fields


@transaction.atomic
def update_{{entity}}({{entity}}_id: int, data: Update{{Entity}}Input, *, actor) -> {{Entity}}:
    obj = get_{{entity}}({{entity}}_id)  # TODO: select_for_update if concurrency matters
    # policies.ensure_can_update(actor, obj)
    raise NotImplementedError
''',
    "application/delete_{{entity}}.py": '''from django.db import transaction

from ..queries import get_{{entity}}


@transaction.atomic
def delete_{{entity}}({{entity}}_id: int, *, actor) -> None:
    obj = get_{{entity}}({{entity}}_id)
    # policies.ensure_can_delete(actor, obj)
    obj.delete()
''',
    "queries/__init__.py": '''from .get_{{entity}} import get_{{entity}}
from .list_{{feature}} import list_{{feature}}

__all__ = ["get_{{entity}}", "list_{{feature}}"]
''',
    "queries/get_{{entity}}.py": '''from core.{{domain}}.models.{{feature}} import {{Entity}}

from ..exceptions import {{Entity}}NotFound


def get_{{entity}}({{entity}}_id: int) -> {{Entity}}:
    try:
        return {{Entity}}.objects.get(pk={{entity}}_id)
    except {{Entity}}.DoesNotExist as exc:
        raise {{Entity}}NotFound() from exc
''',
    "queries/list_{{feature}}.py": '''from django.db.models import QuerySet

from core.{{domain}}.models.{{feature}} import {{Entity}}


def list_{{feature}}() -> QuerySet[{{Entity}}]:
    """Read-only selector. Return a queryset or an explicit projection."""
    return {{Entity}}.objects.all()
''',
    "tests/api/__init__.py": "",
    "tests/api/test_views.py": '''import pytest


@pytest.mark.skip(reason="template: implement")
@pytest.mark.django_db
def test_list_{{feature}}(client):
    ...
''',
    "tests/application/__init__.py": "",
    "tests/application/test_create_{{entity}}.py": '''import pytest


@pytest.mark.skip(reason="template: implement")
@pytest.mark.django_db
def test_create_{{entity}}():
    ...
''',
    "tests/queries/__init__.py": "",
    "tests/queries/test_list_{{feature}}.py": '''import pytest


@pytest.mark.skip(reason="template: implement")
@pytest.mark.django_db
def test_list_{{feature}}():
    ...
''',
}

# --------------------------------------------------------------------------
# Small layout: single application.py / queries.py
# --------------------------------------------------------------------------
SMALL: dict[str, str] = {
    "application.py": '''"""Write use cases for {{feature}}. Split into application/ past ~150 lines."""
from dataclasses import dataclass

from django.db import transaction

from core.{{domain}}.models.{{feature}} import {{Entity}}

from .queries import get_{{entity}}


@dataclass(frozen=True)
class Create{{Entity}}Input:
    pass  # TODO: command fields


@dataclass(frozen=True)
class Update{{Entity}}Input:
    pass  # TODO: command fields


@transaction.atomic
def create_{{entity}}(data: Create{{Entity}}Input, *, actor) -> {{Entity}}:
    """Owns the transaction, rule checks and event emission."""
    raise NotImplementedError


@transaction.atomic
def update_{{entity}}({{entity}}_id: int, data: Update{{Entity}}Input, *, actor) -> {{Entity}}:
    obj = get_{{entity}}({{entity}}_id)  # TODO: select_for_update if concurrency matters
    raise NotImplementedError


@transaction.atomic
def delete_{{entity}}({{entity}}_id: int, *, actor) -> None:
    obj = get_{{entity}}({{entity}}_id)
    obj.delete()
''',
    "queries.py": '''"""Read-only selectors for {{feature}}. Split into queries/ past ~150 lines."""
from django.db.models import QuerySet

from core.{{domain}}.models.{{feature}} import {{Entity}}

from .exceptions import {{Entity}}NotFound


def get_{{entity}}({{entity}}_id: int) -> {{Entity}}:
    try:
        return {{Entity}}.objects.get(pk={{entity}}_id)
    except {{Entity}}.DoesNotExist as exc:
        raise {{Entity}}NotFound() from exc


def list_{{feature}}() -> QuerySet[{{Entity}}]:
    return {{Entity}}.objects.all()
''',
    "tests/test_application.py": '''import pytest


@pytest.mark.skip(reason="template: implement")
@pytest.mark.django_db
def test_create_{{entity}}():
    ...
''',
    "tests/test_queries.py": '''import pytest


@pytest.mark.skip(reason="template: implement")
@pytest.mark.django_db
def test_list_{{feature}}():
    ...
''',
}

# --------------------------------------------------------------------------
# Optional modules
# --------------------------------------------------------------------------
OPTIONAL_TEMPLATES: dict[str, dict[str, str]] = {
    "policies": {
        "application/policies.py": '''"""Authorization and eligibility rules for {{feature}}.

Pure functions: plain arguments in, bool or exception out.
No queries and no imports of sibling use-case modules; use cases import this
module, never the reverse. The use case gathers facts, the policy decides.
"""


def ensure_can_create(actor) -> None:
    ...


def ensure_can_update(actor, {{entity}}) -> None:
    ...


def ensure_can_delete(actor, {{entity}}) -> None:
    ...
''',
        "tests/application/test_policies.py": '''import pytest


@pytest.mark.skip(reason="template: implement (no database needed)")
def test_ensure_can_delete_rejects_non_admin():
    ...
''',
    },
    "repositories": {
        "application/repositories.py": '''"""Aggregates with real invariants or concurrency only; justify in the PR.

Use cases depend on the Protocol; the ORM implementation lives here.
"""
from typing import Protocol

from core.{{domain}}.models.{{feature}} import {{Entity}}


class {{Entity}}Repository(Protocol):
    def get_for_update(self, {{entity}}_id: int) -> {{Entity}}: ...

    def save(self, {{entity}}: {{Entity}}) -> None: ...


class Orm{{Entity}}Repository:
    def get_for_update(self, {{entity}}_id: int) -> {{Entity}}:
        return {{Entity}}.objects.select_for_update().get(pk={{entity}}_id)

    def save(self, {{entity}}: {{Entity}}) -> None:
        {{entity}}.save()
''',
    },
    "adapters": {
        "application/adapters.py": '''"""Translation from {{feature}} to neutral ports. No business rules.

Infrastructure clients are injected by config; never import concrete SDKs here.
"""
''',
    },
    "schema": {
        "api/schema.py": '''"""Optional HTTP contract definitions. Must not duplicate runtime serializers."""
''',
    },
    "permissions": {
        "api/permissions.py": '''"""DRF permission classes: thin wrappers over application policies.

No rules of their own; delegate to ..application.policies.
"""
from rest_framework.permissions import BasePermission


class {{Entity}}Permission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return True  # TODO: delegate to application.policies
''',
    },
    "tasks": {
        "tasks.py": '''"""Background jobs. Call application/queries; never duplicate domain rules.

Register this module explicitly with Celery (autodiscovery only scans <app>.tasks).
"""
''',
    },
    "handlers": {
        "handlers.py": '''"""Subscribers to explicit events. Register in the domain AppConfig.ready()."""
''',
    },
}

MODEL_TEMPLATES = {
    "__init__.py": 'from .models import {{Entity}}\n\n__all__ = ["{{Entity}}"]\n',
    "managers.py": '''from django.db import models


class {{Entity}}QuerySet(models.QuerySet):
    """Reusable filters, e.g. available(). Selectors compose these."""
''',
    "models.py": '''from core.common.models.base import TimeStampedModel

from .managers import {{Entity}}QuerySet


class {{Entity}}(TimeStampedModel):
    # TODO: fields
    objects = {{Entity}}QuerySet.as_manager()
''',
}

DOMAIN_URLS = '''from core.common.api.routing import feature_urls

urlpatterns = feature_urls("{{domain}}", "{{feature}}")
'''


def render(text: str, tokens: dict[str, str]) -> str:
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def add_feature_to_urls(text: str, domain: str, feature: str) -> str | None:
    """Return updated domain urls.py text, or None if it can't be edited safely."""
    if f'"{feature}"' in text:
        return text
    match = re.search(r"feature_urls\(([^)]*)\)", text)
    if not match or f'"{domain}"' not in match.group(1):
        return None
    args = match.group(1).rstrip().rstrip(",")
    return text[: match.start(1)] + args + f', "{feature}"' + text[match.end(1):]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("domain")
    ap.add_argument("feature")
    ap.add_argument("--entity", required=True)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--with", dest="extras", nargs="*", default=[],
                    help="optional modules; space- or comma-separated")
    ap.add_argument("--models", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    args = ap.parse_args()
    aliases = {"policy": "policies", "repository": "repositories", "adapter": "adapters", "permission": "permissions"}
    names = [name.strip() for item in args.extras for name in item.split(",") if name.strip()]
    args.extras = [aliases.get(name, name) for name in names]
    unknown = [name for name in args.extras if name not in OPTIONAL]
    if unknown:
        ap.error(f"unknown --with module(s): {', '.join(unknown)}; choose from {', '.join(OPTIONAL)}")

    for label, value in (("domain", args.domain), ("feature", args.feature), ("entity", args.entity)):
        if not IDENT.match(value):
            sys.exit(f"{label} must be snake_case: {value!r}")
    if args.small and SPLIT_ONLY & set(args.extras):
        bad = ", ".join(sorted(SPLIT_ONLY & set(args.extras)))
        sys.exit(f"--with {bad} lives in application/; use the split layout (omit --small)")

    tokens = {
        "domain": args.domain,
        "feature": args.feature,
        "entity": args.entity,
        "Entity": "".join(p.capitalize() for p in args.entity.split("_")),
    }

    root = Path(args.root)
    domain_dir = root / "core" / args.domain
    if not domain_dir.exists():
        sys.exit(f"{domain_dir} does not exist; create the domain first")

    files = dict(COMMON)
    files.update(SMALL if args.small else SPLIT)
    for extra in args.extras:
        files.update(OPTIONAL_TEMPLATES[extra])

    feature_dir = domain_dir / "features" / args.feature
    plan: dict[Path, str] = {domain_dir / "features" / "__init__.py": ""}
    updates: dict[Path, str] = {}
    manual: list[str] = []

    for rel, content in files.items():
        plan[feature_dir / render(rel, tokens)] = render(content, tokens)

    if args.models:
        if (domain_dir / "models.py").exists():
            sys.exit(f"{domain_dir / 'models.py'} is a module; convert models to a package first")
        model_dir = domain_dir / "models" / args.feature
        for rel, content in MODEL_TEMPLATES.items():
            plan[model_dir / rel] = render(content, tokens)
        init = domain_dir / "models" / "__init__.py"
        line = f"from .{args.feature} import {tokens['Entity']}"
        if init.exists():
            text = init.read_text(encoding="utf-8")
            if line not in text:
                updates[init] = text.rstrip("\n") + ("\n" if text.strip() else "") + line + "\n"
        else:
            plan[init] = line + "\n"

    urls_path = domain_dir / "urls.py"
    if urls_path.exists():
        new_text = add_feature_to_urls(urls_path.read_text(encoding="utf-8"), args.domain, args.feature)
        if new_text is None:
            manual.append(f'add "{args.feature}" to feature_urls(...) in core/{args.domain}/urls.py')
        elif new_text != urls_path.read_text(encoding="utf-8"):
            updates[urls_path] = new_text
    else:
        plan[urls_path] = render(DOMAIN_URLS, tokens)

    created = 0
    for path, content in plan.items():
        if path.exists():
            continue
        created += 1
        print(("would create " if args.dry_run else "create ") + path.relative_to(root).as_posix())
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    for path, content in updates.items():
        print(("would update " if args.dry_run else "update ") + path.relative_to(root).as_posix())
        if not args.dry_run:
            path.write_text(content, encoding="utf-8")

    pkg = f"core.{args.domain}.features.{args.feature}"
    if not args.models:
        manual.append(f"export {tokens['Entity']} from core/{args.domain}/models/__init__.py")
    if "handlers" in args.extras:
        manual.append(f"import {pkg}.handlers in core/{args.domain}/apps.py ready()")
    if "tasks" in args.extras:
        manual.append(f"register {pkg}.tasks with Celery")
    manual.append(f'import-linter: add "{pkg}" to the feature-layer containers, plus the contract below')

    print(f"\n{created} file(s) {'planned' if args.dry_run else 'created'}. Remaining manual steps:")
    for i, step in enumerate(manual, 1):
        print(f"  {i}. {step}")
    print(
        "\n[[tool.importlinter.contracts]]\n"
        f'name = "{args.feature} internals do not import their own public facade or urls"\n'
        'type = "forbidden"\n'
        f'source_modules = ["{pkg}.api", "{pkg}.application", "{pkg}.queries"]\n'
        f'forbidden_modules = ["{pkg}.public", "{pkg}.urls"]'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
