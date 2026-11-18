"""``python -m tools.stubs <tool> ...``: one entry point for every stub."""

from __future__ import annotations

import importlib
import sys

TOOLS = {
    "entra": "tools.stubs.entra",
    "identities": "tools.stubs.identities",
    "lab": "tools.stubs.lab",
    "agent": "tools.stubs.agent",
    "router": "tools.stubs.router",
    "scenario": "tools.stubs.scenario",
}

USAGE = """usage: python -m tools.stubs <tool> [args]

tools:
  entra       stub Entra issuer: keys, JWKS server, ID / access / app tokens, persona login
  identities  inject persona users with Entra bindings and roles (Django)
  lab         seed benches, computers on benches and a project (Django)
  agent       signed device API, booking actions, operator API, provisioning
  router      routing sync consumer
  scenario    end-to-end scenarios with PASS/FAIL per step

Run 'python -m tools.stubs <tool> --help' for details; setup steps are in tools/stubs/README.md."""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"} or argv[0] not in TOOLS:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2
    module = importlib.import_module(TOOLS[argv[0]])
    result = module.main(argv[1:])
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
