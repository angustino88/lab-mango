"""Inject stub persona users into the local database, with Entra bindings and Labs roles.

Runs inside Django (``DJANGO_SETTINGS_MODULE``, default ``config.settings.local``) and changes users only
through ``core.users.public`` stub commands, which use the lifecycle commands, so routing ``users`` changes
and audit events are published exactly as on production paths. The commands refuse unless
``ENTRA_STUB_ISSUER_ENABLED`` is on in DEBUG for the stub tenant, and they touch ``stub.*`` users only.

    python -m tools.stubs identities seed            # converge every persona of this BACKEND_ID; safe to rerun
    python -m tools.stubs identities list            # username, active, roles, routing key
    python -m tools.stubs identities deactivate ivy  # tombstone in routing; activate publishes it again
    python -m tools.stubs identities unlink alice    # tombstone; seed binds again
    python -m tools.stubs identities replace alice   # new object ID: old key tombstoned, new key published
    python -m tools.stubs identities delete alice    # tombstone and delete the user
    python -m tools.stubs identities reset           # delete every stub user, then seed
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from tools.stubs.common import Persona, PersonaManifest, generations, load_personas, set_generation


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass(frozen=True, slots=True)
class PersonaOutcome:
    key: str
    username: str
    changed: bool
    user_key: str | None
    note: str = ""


def seed(
    manifest: PersonaManifest | None = None, *, keys: list[str] | None = None, all_backends: bool = False
) -> list[PersonaOutcome]:
    """Converge stub users to the manifest. A second run reports ``changed=False`` for every persona."""
    from django.conf import settings

    from core.users import public as users

    manifest = manifest or load_personas()
    tenant = users.stub_tenant_id()
    current = {state.username: state for state in users.list_stub_users()}
    selected = [manifest.get(key) for key in keys] if keys else list(manifest.personas.values())
    outcomes = []
    for persona in selected:
        if not all_backends and not keys and persona.backend != settings.BACKEND_ID:
            continue
        result = users.ensure_stub_user(
            users.StubUserInput(
                username=persona.username, name=persona.name, email=persona.email, labs_role=persona.labs_role
            )
        )
        changed = result.changed
        state = current.get(persona.username)
        object_id = manifest.object_id(persona, tenant=str(tenant))
        # Activity first: an inactive persona is never published, not even for a moment.
        changed |= users.stub_set_user_active(user_id=result.user_id, is_active=persona.active).changed
        if persona.bound:
            if state is not None and state.object_id is not None and state.object_id != object_id:
                changed |= users.stub_replace_entra_identity(user_id=result.user_id, object_id=object_id).changed
            else:
                changed |= users.stub_bind_entra_identity(user_id=result.user_id, object_id=object_id).changed
        elif state is not None and state.object_id is not None:
            changed |= users.stub_unlink_entra_identity(user_id=result.user_id).changed
        outcomes.append(
            PersonaOutcome(
                key=persona.key,
                username=persona.username,
                changed=changed,
                user_key=manifest.user_key(persona, tenant=str(tenant)) if persona.bound else None,
            )
        )
    return outcomes


def _user_id(persona: Persona) -> int:
    from core.users import public as users

    for state in users.list_stub_users():
        if state.username == persona.username:
            return state.user_id
    raise SystemExit(f"{persona.username} does not exist; run: python -m tools.stubs identities seed")


def set_active(persona: Persona, is_active: bool) -> bool:
    from core.users import public as users

    return users.stub_set_user_active(user_id=_user_id(persona), is_active=is_active).changed


def unlink(persona: Persona) -> bool:
    from core.users import public as users

    return users.stub_unlink_entra_identity(user_id=_user_id(persona)).changed


def replace(manifest: PersonaManifest, persona: Persona) -> tuple[str, str]:
    """Bump the persona's generation and rebind; returns (old routing key, new routing key)."""
    from core.users import public as users

    user_id = _user_id(persona)
    old = manifest.user_key(persona)
    generation = generations().get(persona.key, 0) + 1
    users.stub_replace_entra_identity(user_id=user_id, object_id=manifest.object_id(persona, generation=generation))
    set_generation(persona.key, generation)  # after the commit, so a failed rebind keeps the old generation
    return old, manifest.user_key(persona)


def delete(persona: Persona) -> bool:
    from core.users import public as users

    return users.stub_delete_user(user_id=_user_id(persona)).changed


def delete_all() -> list[str]:
    from core.users import public as users

    deleted = []
    for state in users.list_stub_users():
        users.stub_delete_user(user_id=state.user_id)
        deleted.append(state.username)
    return deleted


def describe(manifest: PersonaManifest | None = None) -> list[str]:
    from core.users import public as users

    manifest = manifest or load_personas()
    lines = []
    for state in users.list_stub_users():
        key = (
            f"entra:{str(state.tenant_id).lower()}:{str(state.object_id).lower()}"
            if state.object_id is not None
            else "-"
        )
        routed = "routed" if state.is_active and state.object_id is not None else "not routed"
        lines.append(
            f"{state.username:<12} id={state.user_id:<5} active={str(state.is_active):<5} "
            f"roles={','.join(state.labs_roles) or '-':<6} {routed:<10} {key}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.stubs identities",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    seed_parser = commands.add_parser("seed", help="create or converge personas (this BACKEND_ID only)")
    seed_parser.add_argument("personas", nargs="*", help="only these personas (any backend)")
    seed_parser.add_argument("--all-backends", action="store_true")
    commands.add_parser("list")
    for name in ("activate", "deactivate", "unlink", "replace", "delete"):
        commands.add_parser(name).add_argument("persona")
    commands.add_parser("reset", help="delete every stub user, then seed")
    args = parser.parse_args(argv)

    setup_django()
    from core.users.public import StubIdentitiesDisabled

    manifest = load_personas()
    try:
        if args.command in {"seed", "reset"}:
            if args.command == "reset":
                for username in delete_all():
                    print(f"deleted  {username}")
            keys = args.personas if args.command == "seed" and args.personas else None
            for outcome in seed(manifest, keys=keys, all_backends=getattr(args, "all_backends", False)):
                state = "changed  " if outcome.changed else "unchanged"
                print(f"{state} {outcome.username:<12} {outcome.user_key or '(not bound)'}")
        elif args.command == "list":
            print("\n".join(describe(manifest)) or "(no stub users)")
        else:
            persona = manifest.get(args.persona)
            if args.command in {"activate", "deactivate"}:
                changed = set_active(persona, args.command == "activate")
                print(f"{persona.username}: {'changed' if changed else 'unchanged'}")
            elif args.command == "unlink":
                print(f"{persona.username}: {'unlinked' if unlink(persona) else 'was not bound'}")
            elif args.command == "replace":
                old, new = replace(manifest, persona)
                print(f"{persona.username}: {old} -> {new}")
            elif args.command == "delete":
                delete(persona)
                print(f"{persona.username}: deleted")
    except StubIdentitiesDisabled as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
