# Deploying backends

One repository, many backends. Each backend's configuration is committed under
`.envs/.production/<backend>/`, with secrets encrypted by SOPS + age. A server only needs the
repository and its age private key to deploy any backend; nobody edits files on the server.

```text
.envs/.production/
├── backend.env.example        template: ports, profiles (non-secret)
├── .django.example            template: Django secrets
├── .postgres.example          template: database secrets
└── <backend>/
    ├── backend.env            committed, plaintext, non-secret
    ├── .django.enc            committed, encrypted
    ├── .postgres.enc          committed, encrypted
    ├── .django                ignored, decrypted on the server (mode 600)
    └── .postgres              ignored, decrypted on the server (mode 600)
```

Every backend runs as its own Compose project `labmango-<backend>` with its own containers
(`labmango-<backend>-django`, `-celeryworker`, `-celerybeat`, `-redis`, `-nginx`, `-postgres`),
image tag (`labmango-backend:<backend>`), Redis, volumes and `staticfiles/<backend>/`.
Several backends can share one host as long as their ports differ; `deploy` refuses duplicates.

Requirements: Docker with Compose v2, [SOPS](https://github.com/getsops/sops) and
[age](https://github.com/FiloSottile/age) (install steps: [scripts/sops/README.md](../sops/README.md)).

## Add a backend (developer machine)

```bash
scripts/deploy/backend.sh init dept_a
```

This creates `.envs/.production/dept_a/` with the next free ports and plaintext `.django` and
`.postgres` copied from the templates. Edit all three files:

- `backend.env`: `COMPOSE_PROFILES` (`nginx` if this backend runs without the router,
  `postgres` to run the database in a container), ports, optional `BACKEND_ID`.
- `.django` and `.postgres`: replace every `replace-with-*` value.

Encrypt for every server (and teammate) that must read it, then commit:

```bash
export SOPS_AGE_RECIPIENT=age1server...,age1teammate...
scripts/deploy/backend.sh encrypt dept_a
git add .envs/.production/dept_a && git commit -m "Add dept_a backend"
```

To change a secret later: `decrypt`, edit, `encrypt`, commit.

## Deploy (server)

One-time: put the server's age private key on the host, readable only by the deploy user, e.g.
`/etc/labmango/age.key` (`chmod 600`). Its public key is what you list in `SOPS_AGE_RECIPIENT`.

```bash
export SOPS_AGE_KEY_FILE=/etc/labmango/age.key
git pull
scripts/deploy/backend.sh deploy dept_a
```

`deploy` decrypts that backend's secrets, builds `labmango-backend:dept_a`, makes
`staticfiles/dept_a/` writable for the image's non-root user, and starts the stack.
Deploy several at once with `deploy dept_a dept_b`, or every backend with `deploy --all`.

## Day to day

```bash
scripts/deploy/backend.sh list
```

```bash
scripts/deploy/backend.sh ps dept_a
```

```bash
scripts/deploy/backend.sh logs dept_a -f django
```

```bash
scripts/deploy/backend.sh restart dept_a celeryworker
```

```bash
scripts/deploy/backend.sh down dept_a
```

`down` keeps the database volumes. `config <backend>` prints the fully resolved Compose file.

## Certificates

nginx (profile `nginx`) reads `server.crt` and `server.key` from `ssl_certifactes/`, or from
`SSL_DIR` in `backend.env` when backends need different certificates. Extra CA certificates
(`*.crt`) in `ssl_certifactes/` are trusted by the Django image; see
[ssl_certifactes/README.md](../../ssl_certifactes/README.md).
