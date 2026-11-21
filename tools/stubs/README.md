# Local identity stubs (`tools/stubs`)

Test routing, agents and user flows locally without a real Entra tenant or a real device. Development and
test only. Design and decisions: `docs/proposals/local-identity-stubs.md`.

Everything runs from the repository root through one entry point:

```bash
uv run python -m tools.stubs <tool> --help
```

| Tool | Runs | Does |
|---|---|---|
| `entra` | stand-alone | Stub Entra issuer: signing key, loopback JWKS server, ID / access / app tokens, persona login |
| `identities` | Django | Injects persona users with Entra bindings and Labs roles, through the user lifecycle commands (routing changes are published) |
| `lab` | Django | Seeds benches, computers placed on them, and a project |
| `agent` | stand-alone | Signed device API, booking actions, signing faults, operator API, `provision` |
| `router` | stand-alone | Routing sync consumer: info, snapshot, changes, digest, long-poll |
| `scenario` | stand-alone + Django | End-to-end scenarios with PASS/FAIL per step |

The former `tools/stub_agent.py` and `tools/stub_router.py` are now `agent` and `router` here: use
`python -m tools.stubs agent ...` and `python -m tools.stubs router ...` (same subcommands and flags).

## One-time setup

1. Create the issuer key and copy the printed block into your untracked `.env`:

   ```bash
   uv run python -m tools.stubs entra init
   ```

   The block sets `ENTRA_STUB_ISSUER_ENABLED=True`, the reserved stub tenant
   `00000000-0000-0000-0000-0000000057ab`, the loopback `AAD_JWKS_URL`, audiences, `BACKEND_ID` and a higher
   local login throttle. The backend refuses this configuration outside `DEBUG` (`users.E014`), and production
   refuses the stub tenant (`users.E015`).
2. Keep the JWKS server running in its own terminal (stop it to simulate "Entra unreachable"):

   ```bash
   uv run python -m tools.stubs entra serve
   ```

3. Start the backend with that `.env` (`uv run python manage.py runserver`), then seed and provision:

   ```bash
   uv run python -m tools.stubs scenario setup
   ```

   `setup` seeds the personas and the lab and enrolls stub agents for `pc-1`, `pc-2` and `pc-loose`.

## Personas (`personas.json`)

| Key | Username | Labs role | Bound | Active | Backend | Use |
|---|---|---|---|---|---|---|
| alice | stub.alice | member | yes | yes | dept_a | books benches; normal user |
| carol | stub.carol | coord | yes | yes | dept_a | operator API, approvals |
| adam | stub.adam | admin | yes | yes | dept_a | admin access |
| dave | stub.dave | member | **no** | yes | dept_a | binds on first login (by username) |
| ivy | stub.ivy | member | yes | **no** | dept_a | inactive: refused, never routed |
| nora | stub.nora | none | yes | yes | dept_a | authenticated but no Labs role: 403 |
| bob | stub.bob | member | yes | yes | **dept_b** | owned by another backend (two-backend routing) |

The UPN is `stub.<key>@stub.labmango.test`. The object ID is `uuid5(namespace, "<tenant>:<key>:<generation>")`, so
a persona has the same routing key after a database reset. `identities replace` bumps the generation.

Stub users have unusable passwords and `is_urs_managed=False`. Their roles come from three inactive URS groups
with reserved ids (`9000000000001..3`), which the scheduled URS sync never fetches. Every stub command refuses
any user that is not `stub.*`, is URS-managed, or is bound in another tenant.

## Common commands

```bash
# Users
uv run python -m tools.stubs identities seed          # converge; safe to rerun
uv run python -m tools.stubs identities list
uv run python -m tools.stubs identities deactivate ivy   # | activate | unlink | replace | delete <persona>
uv run python -m tools.stubs entra login alice
uv run python -m tools.stubs entra call alice GET /api/labs/bench-bookings

# Lab and bookings (bookings are made as a user through the API; agents never create them)
uv run python -m tools.stubs lab seed
uv run python -m tools.stubs lab list
uv run python -m tools.stubs scenario book --as @alice --bench bench-1 --minutes 60   # prints booking_code

# Agents
uv run python -m tools.stubs agent provision --equipment pc-1 --profile pc-1          # as carol
uv run python -m tools.stubs agent --profile pc-1 heartbeat --every 60 --count 10
uv run python -m tools.stubs agent --profile pc-1 activity --status active --remote-user @alice
uv run python -m tools.stubs agent --profile pc-1 booking validate --code <code>     # check-in | extend --by 30m | complete
uv run python -m tools.stubs agent --profile pc-1 session --user @alice --code <code> --extend-by 30m
uv run python -m tools.stubs agent --profile pc-1 session-log --remote-user @alice --minutes 45
uv run python -m tools.stubs agent --profile pc-1 session-log --remote-user @alice --repeat-last
uv run python -m tools.stubs agent --profile pc-1 heartbeat --replay                  # signing faults → 401
uv run python -m tools.stubs agent agents list                                         # operator API, as carol
uv run python -m tools.stubs agent --as @alice grant create --equipment pc-2           # 403: users cannot

# Routing
uv run python -m tools.stubs router --action snapshot --entity users                  # minted app token
uv run python -m tools.stubs entra app-token --no-role                                 # negative tokens

# Everything
uv run python -m tools.stubs scenario all
```

## Scenarios

`setup`, `booking-happy-path`, `booking-wrong-bench`, `booking-unassigned-agent`, `booking-early`,
`booking-extend-conflict`, `booking-idempotent`, `signing-faults`, `operator-authz`, `entra-faults`,
`routing-users`, `agent-lifecycle`. Each prints PASS/FAIL per step and exits non-zero on any failure.
Scenarios delete bookings on `STUB-` benches when they start and when they finish.

## Tests

`tests/stubs/` runs in CI with the normal `pytest` gate. `tools/stubs/testing.py` provides
`stub_entra_environment(issuer)`, which applies the stub settings and serves the issuer's keys to the three
production JWKS lookups in-process. `tests/stubs/test_agent_stub.py` drives the stubs over HTTP against
pytest-django's `live_server`.

## State and safety

State lives in `$LABMANGO_STUB_HOME` (default `~/.labmango-stub`): the issuer key, persona sessions, agent profiles
and generations, all with mode 0600. It holds private keys and tokens for local use only. Never put it in the
repository (it is git-ignored) and never use it for a real device or tenant.
