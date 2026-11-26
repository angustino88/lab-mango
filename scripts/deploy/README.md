# Deploying department backends

One repository, one backend per department. You change code or configuration, push to `main`, and
every department server redeploys itself once CI passes. Nobody edits files on the servers.

```text
Developer ── git push ──► GitHub: ci ──► deploy workflow
                                           ├─ job dept-a ─► runner on dept-a server ─► decrypt with its key ─► docker compose up
                                           ├─ job dept-b ─► runner on dept-b server ─► ...
                                           └─ job dept-c ─► runner on dept-c server ─► ...
```

## Layout

```text
.sops.yaml                          who can decrypt which department (public keys, committed)
.envs/.production/
├── .backend.example                templates
├── .django.example
├── .postgres.example
├── dept-a/
│   ├── .backend.enc                ports, profiles, BACKEND_ID         (encrypted)
│   ├── .django.enc                 Django settings                     (encrypted)
│   └── .postgres.enc               database settings                   (encrypted)
├── dept-b/ ...
└── dept-c/ ...
docker-compose.prod.yml             one stack per department
scripts/deploy/backend.sh           init / encrypt / edit / deploy / logs ...
.github/workflows/deploy.yml        automatic deploy through self-hosted runners
```

On each server, outside the checkout:

```text
/etc/labmango/age.key               the server's private key (only decrypts its own department)
/srv/labmango/<department>/
├── .backend .django .postgres      decrypted on every deploy (mode 600)
├── staticfiles/                    collectstatic output
└── ssl/server.crt, server.key      only for departments using the nginx profile
/srv/labmango/ca-certificates/*.crt optional extra CA certificates added to the image
```

Every department is its own Compose project `labmango-<department>` with containers
`labmango-<department>-django`, `-celeryworker`, `-celerybeat`, `-redis`, and optionally `-nginx` and
`-postgres`, image `labmango-backend:<department>`, its own Redis and volumes. Departments can share
a server when their ports in `.backend` differ; `deploy` refuses a clash.

## Access model

`.sops.yaml` encrypts each department folder to the admins plus that department's server key:

| Who | Can decrypt |
|---|---|
| Admin / developer keys | every department |
| dept-a server key | dept-a only |
| dept-b server key | dept-b only |
| dept-c server key | dept-c only |
| GitHub, CI logs, anyone with repo read access | nothing |

The private keys never go to GitHub: decryption happens on the server, inside the deploy job.

## One-time setup

### 1. Admin key (each person who edits configuration)

```bash
mkdir -p ~/.config/sops/age && age-keygen -o ~/.config/sops/age/keys.txt
```

The printed `age1...` public key goes into `.sops.yaml`. SOPS finds this private key automatically.
Install `sops` and `age` first: [scripts/sops/README.md](../sops/README.md).

### 2. Each department server

Requirements: Docker with Compose v2, `sops`, `git`, `curl`.

```bash
sudo mkdir -p /etc/labmango /srv/labmango
```

```bash
sudo age-keygen -o /etc/labmango/age.key
```

Give the deploy user (the runner's user, which must be in the `docker` group) ownership:

```bash
sudo chown -R <runner-user> /etc/labmango /srv/labmango && sudo chmod 600 /etc/labmango/age.key
```

Put the printed public key in `.sops.yaml` for that department. For departments using the `nginx`
profile, copy `server.crt` and `server.key` to `/srv/labmango/<department>/ssl/`.

### 3. Self-hosted runner on each server

In GitHub: **Settings → Actions → Runners → New self-hosted runner**, follow the Linux steps on the
server, and give it the label `labmango-<department>` (e.g. `labmango-dept-a`). Install it as a
service (`sudo ./svc.sh install <runner-user> && sudo ./svc.sh start`). The runner only makes
outbound HTTPS connections to GitHub; the server needs no open inbound port. A server that hosts
two departments gets both labels.

Optional: under **Settings → Environments**, add required reviewers to `dept-a`, `dept-b`, `dept-c`
to approve each production deploy.

### 4. Recipients file

```bash
cp .sops.yaml.example .sops.yaml
```

Replace the placeholder keys and department names, then commit `.sops.yaml`.

### 5. Create each department's configuration

```bash
scripts/deploy/backend.sh init dept-a
```

Fill in every `replace-with-*` value in `.envs/.production/dept-a/.backend`, `.django` and
`.postgres` (plaintext, git-ignored), then encrypt. This deletes the plaintext:

```bash
scripts/deploy/backend.sh encrypt dept-a
```

Repeat for `dept-b` and `dept-c`, then commit `.envs/.production/*/*.enc` and push.

## Everyday use

Change a value (opens your editor on the decrypted file, saves it encrypted):

```bash
scripts/deploy/backend.sh edit dept-b django
```

Commit and push to `main`: CI runs, then every department redeploys. To deploy only some
departments, or without a code change, use **Actions → deploy → Run workflow** and enter e.g.
`dept-a,dept-c`. To limit automatic deploys, set the repository variable `DEPLOY_DEPARTMENTS`
(e.g. `dept-a,dept-b`); unset means all departments.

Each deploy decrypts the configuration, builds the image from the pushed commit, starts the stack,
and fails the job unless `/healthz` answers 200 within about 2.5 minutes.

On a server, for diagnosis:

```bash
scripts/deploy/backend.sh ps dept-a
```

```bash
scripts/deploy/backend.sh logs dept-a -f django
```

```bash
scripts/deploy/backend.sh deploy dept-a
```

`down <department>` stops a department and keeps its database volumes.

## Adding a department or rotating keys

- New department: add its key and rule to `.sops.yaml`, run `init` and `encrypt`, register a
  runner with label `labmango-<department>`, push.
- New admin or replaced server key: update `.sops.yaml`, then re-encrypt each affected department
  (needs an admin key):

```bash
scripts/deploy/backend.sh updatekeys dept-a
```

Removing a key from `.sops.yaml` stops future access only; rotate the secrets themselves if that
key may have leaked, because old commits stay decryptable with it.

## Without GitHub-hosted automation

If a server cannot reach GitHub Actions, the same command works from a cron job or by hand on
the server, in a clone of the repository:

```bash
git pull --ff-only && scripts/deploy/backend.sh deploy dept-a
```
