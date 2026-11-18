"""Local identity stubs for routing, agent and user tests (development and test only).

One package, one entry point: ``python -m tools.stubs <tool> ...``. See ``tools/stubs/README.md`` and the
design in ``docs/proposals/local-identity-stubs.md``.

| Tool | Runs | Does |
|---|---|---|
| ``entra`` | stand-alone | stub Entra issuer: signing keys, JWKS server, ID / access / app tokens, login |
| ``identities`` | Django | inject persona users with Entra bindings and roles, through the lifecycle commands |
| ``lab`` | Django | seed a bookable lab: benches, computers placed on them, a project |
| ``agent`` | stand-alone | signed device API, booking actions, operator API, provisioning |
| ``router`` | stand-alone | routing sync consumer (snapshot, changes, long-poll) |
| ``scenario`` | stand-alone | end-to-end scenarios with pass/fail per step |
"""
