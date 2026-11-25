# Certificates (not committed)

Place deployment certificates here on the host. Everything except this README is git-ignored.

| File | Used by |
|---|---|
| `RB_IssuingCA_RSA_G21.crt`, `RB_RootCA_RSA_G01.crt` | Required by `compose/production/django/Dockerfile` (trusted CA bundle). Optional for the local image. |
| `server.crt`, `server.key` | nginx TLS on port 8443 (`nginx/conf.d/default.conf`), mounted read-only at `/etc/nginx/ssl`. |

`.dockerignore` keeps `server.crt`/`server.key` out of the Django image build context.
