# Extra CA certificates (not committed)

Any `*.crt` placed here is trusted by the Django images at build time (for example a company proxy
or internal API CA). Everything except this README is git-ignored.

- Local development: put the files here yourself.
- Department servers: keep them in `/srv/labmango/ca-certificates/`; `scripts/deploy/backend.sh deploy`
  copies them here before building.

nginx TLS certificates do not belong here: they live on each server in
`/srv/labmango/<department>/ssl/` (see [scripts/deploy/README.md](../scripts/deploy/README.md)).
