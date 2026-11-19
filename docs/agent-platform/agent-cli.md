# Agent command line (proposed)

Status: **proposed, needs owner approval.** The operator UI (computing inventory → Agent → Set up) generates
these commands, so the packaged agent must accept them as written. The layout follows established
self-hosted agent installers (GitHub Actions runner, Azure Pipelines agent, Buildkite): download, configure
with a one-time token, install a service, verify.

> **Decision needed — grant on the command line.** [device-design.md](device-design.md) currently says the
> grant is never passed on a command line, URL, config or log. This proposal passes it as `--grant`, as the
> GitHub runner does with its registration token. Accepted only because the grant is one-time, bound to one
> agent and one computer, expires in at most 60 minutes, and is useless without the device-held key proof.
> Residual risk: before redemption, someone who reads shell history or the process list could enroll a key
> of their own. Mitigations below. If accepted, update device-design.md; if rejected, drop `--grant` and keep
> the hidden prompt (the command stays the same otherwise).

## Install layout

| OS | Folder | Package |
|---|---|---|
| Windows | `C:\labmango-agent` | `labmango-agent-win-<arch>.zip` |
| Linux | `/opt/labmango-agent` | `labmango-agent-linux-<arch>.tar.gz` |
| macOS | `~/labmango-agent` | `labmango-agent-osx-<arch>.tar.gz` |

`<arch>` is `x64` or `arm64`. The UI builds download links from `VITE_AGENT_DOWNLOAD_URL` (the folder that holds
the packages of one release); without it the UI omits the download commands.

## Commands

```
labmango-agent enroll --url <server-url> --agent-uid <uuid> [--grant <grant>] [--unattended]
labmango-agent service install [--start]
labmango-agent service start | stop | uninstall
labmango-agent status [--json]
labmango-agent unenroll
```

`enroll`
- `--url`: the server URL from the web app's setup dialog. Production: the public Nginx or Router address (the application server is never exposed); development: the backend directly. HTTPS in production; the agent checks `GET /agent/info` and refuses on mismatch of
  `backend_key` with a later enrollment.
- `--agent-uid`: the pending agent created by the operator; ties the grant to this identity.
- `--grant`: one-time enrollment grant (`eg_…`). Also read from `LABMANGO_AGENT_GRANT`. If neither is given and a
  terminal is attached, prompt with hidden input; with `--unattended`, fail instead of prompting.
- Generates an Ed25519 key in the best store available (TPM, then OS keystore, then software), sends
  `POST /agent/enrollments` with the proof, stores agent UID and URL in the agent config, never the grant.
- Exit codes: `0` enrolled, `2` invalid or expired grant, `3` key proof rejected, `4` already enrolled /
  conflict, `5` backend unreachable.

`service install --start` registers the background service (Windows service, systemd unit, launchd daemon) and
starts it. The service sends `POST /agent/heartbeat` on a fixed interval with jitter, well inside
`AGENT_HEALTH_ONLINE_S` (default 180 s; a 60 s interval is suggested).

`status` prints agent UID, backend, key store, service state and the last heartbeat result; exit `0` only
when the last heartbeat succeeded.

## Grant handling (agent side)
- Never write the grant to config, logs or crash reports; clear it from memory after enrollment.
- On Windows, recommend running from an elevated PowerShell session that is closed afterwards; on Linux/macOS
  the UI prefixes nothing, so operators may use a leading space where `HISTCONTROL=ignorespace` applies.
- A used grant fails with exit code `2`; the operator issues a new one from the UI.

## Health shown to operators

| Health | Meaning |
|---|---|
| Online | Heartbeat within `AGENT_HEALTH_ONLINE_S` (180 s) |
| Delayed | Heartbeat late, within `AGENT_HEALTH_OFFLINE_S` (900 s) |
| Offline | No heartbeat for longer, or never since enrollment |

Pending, revoked and decommissioned agents have no health; the UI shows their state.
