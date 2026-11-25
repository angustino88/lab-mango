# Certificates (not committed)

Place deployment certificates here on the host. Everything except this README is git-ignored.

| File | Used by |
|---|---|
| `server.crt`, `server.key` | nginx TLS (`nginx/templates/default.conf.template`), mounted read-only at `/etc/nginx/ssl`. Override the folder per backend with `SSL_DIR` in its `backend.env`. |
| any other `*.crt` | Optional extra CA certificates trusted by the Django images (for example a company proxy or internal API CA). |

`.dockerignore` keeps `server.crt` and `server.key` out of the Django image build context.
