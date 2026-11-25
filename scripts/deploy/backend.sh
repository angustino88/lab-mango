#!/usr/bin/env bash
# Deploy and manage LabMango backends with docker-compose.prod.yml.
# Each backend lives in .envs/.production/<backend>/ (see scripts/deploy/README.md):
#   backend.env    non-secret topology, committed
#   .django.enc    SOPS-encrypted secrets, committed   -> decrypted to .django on the server
#   .postgres.enc  SOPS-encrypted secrets, committed   -> decrypted to .postgres on the server
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$repo_root"

envs_root=.envs/.production
compose_file=docker-compose.prod.yml
secret_files=(.django .postgres)
port_keys=(UVICORN_PORT REDIS_PORT NGINX_HTTP_PORT NGINX_HTTPS_PORT POSTGRES_PORT)

usage() {
  cat >&2 <<'EOF'
Usage: scripts/deploy/backend.sh <command> [backend...]

  list                      Backends in .envs/.production and their ports
  init <backend>            Create a backend folder with the next free ports and editable secret files
  encrypt <backend>         Encrypt .django/.postgres to .enc (needs SOPS_AGE_RECIPIENT)
  decrypt <backend>         Decrypt .enc files (needs SOPS_AGE_KEY_FILE or SOPS_AGE_KEY)
  deploy <backend>...|--all Decrypt, build and start the backend(s)
  down <backend>            Stop and remove the backend's containers (volumes are kept)
  ps|logs|restart|config <backend> [args]
                            Pass through to docker compose for that backend
EOF
  exit 2
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '==> %s\n' "$*" >&2; }

validate_name() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{0,39}$ ]] \
    || die "backend name '$1' must be lowercase letters, digits, '-' or '_' (max 40 chars)"
}

backend_dir() { printf '%s/%s' "$envs_root" "$1"; }

require_backend() {
  validate_name "$1"
  [ -f "$(backend_dir "$1")/backend.env" ] \
    || die "no $(backend_dir "$1")/backend.env (create it with: scripts/deploy/backend.sh init $1)"
}

all_backends() {
  local f
  for f in "$envs_root"/*/backend.env; do
    [ -f "$f" ] && basename "$(dirname "$f")"
  done
}

# Read KEY from a backend.env without sourcing it.
env_value() {
  sed -n "s/^[[:space:]]*$2=\\(.*\\)$/\\1/p" "$1" | tail -n 1 | tr -d '"'"'"' \r'
}

compose() {
  local name=$1; shift
  local dir; dir=$(backend_dir "$name")
  local declared; declared=$(env_value "$dir/backend.env" BACKEND_NAME)
  [ "$declared" = "$name" ] || die "$dir/backend.env has BACKEND_NAME=$declared; it must be $name"
  BACKEND_NAME=$name docker compose \
    --project-name "labmango-$name" \
    --file "$compose_file" \
    --env-file "$dir/backend.env" \
    "$@"
}

next_port() {
  local key=$1 default=$2 max=0 b v
  for b in $(all_backends); do
    v=$(env_value "$(backend_dir "$b")/backend.env" "$key")
    [[ "$v" =~ ^[0-9]+$ ]] && [ "$v" -gt "$max" ] && max=$v
  done
  if [ "$max" -eq 0 ]; then echo "$default"; else echo $((max + 1)); fi
}

cmd_list() {
  printf '%-20s %-12s %-8s %-8s %-8s %-8s %-8s\n' BACKEND PROFILES UVICORN REDIS HTTP HTTPS POSTGRES
  local b f
  for b in $(all_backends); do
    f=$(backend_dir "$b")/backend.env
    printf '%-20s %-12s %-8s %-8s %-8s %-8s %-8s\n' "$b" "$(env_value "$f" COMPOSE_PROFILES)" \
      "$(env_value "$f" UVICORN_PORT)" "$(env_value "$f" REDIS_PORT)" \
      "$(env_value "$f" NGINX_HTTP_PORT)" "$(env_value "$f" NGINX_HTTPS_PORT)" \
      "$(env_value "$f" POSTGRES_PORT)"
  done
}

cmd_init() {
  local name=$1 dir; validate_name "$name"; dir=$(backend_dir "$name")
  [ -e "$dir/backend.env" ] && die "$dir/backend.env already exists"
  mkdir -p "$dir"
  sed -e "s/^BACKEND_NAME=.*/BACKEND_NAME=$name/" \
      -e "s/^UVICORN_PORT=.*/UVICORN_PORT=$(next_port UVICORN_PORT 9001)/" \
      -e "s/^REDIS_PORT=.*/REDIS_PORT=$(next_port REDIS_PORT 6380)/" \
      -e "s/^NGINX_HTTP_PORT=.*/NGINX_HTTP_PORT=$(next_port NGINX_HTTP_PORT 8081)/" \
      -e "s/^NGINX_HTTPS_PORT=.*/NGINX_HTTPS_PORT=$(next_port NGINX_HTTPS_PORT 8443)/" \
      -e "s/^POSTGRES_PORT=.*/POSTGRES_PORT=$(next_port POSTGRES_PORT 5432)/" \
      "$envs_root/backend.env.example" > "$dir/backend.env"
  local s
  for s in "${secret_files[@]}"; do
    if [ ! -e "$dir/$s" ]; then
      (umask 077; cp "$envs_root/$s.example" "$dir/$s")
    fi
  done
  info "Created $dir"
  info "Next: edit $dir/backend.env, $dir/.django and $dir/.postgres, then"
  info "      scripts/deploy/backend.sh encrypt $name   and commit backend.env + *.enc"
}

cmd_encrypt() {
  local name=$1 dir s; require_backend "$name"; dir=$(backend_dir "$name")
  : "${SOPS_AGE_RECIPIENT:?Set SOPS_AGE_RECIPIENT to the age public key(s), comma-separated}"
  command -v sops >/dev/null || die "sops is not installed (scripts/sops/README.md)"
  for s in "${secret_files[@]}"; do
    [ -f "$dir/$s" ] || die "missing plaintext $dir/$s"
    if grep -q 'replace-with-' "$dir/$s"; then
      printf 'warning: %s still contains replace-with-* placeholders\n' "$dir/$s" >&2
    fi
    sops --encrypt --age "$SOPS_AGE_RECIPIENT" --input-type dotenv --output-type dotenv \
      --output "$dir/$s.enc" "$dir/$s"
    info "Encrypted $dir/$s -> $dir/$s.enc"
  done
}

cmd_decrypt() {
  local name=$1 dir s; require_backend "$name"; dir=$(backend_dir "$name")
  command -v sops >/dev/null || die "sops is not installed (scripts/sops/README.md)"
  if [ -z "${SOPS_AGE_KEY:-}" ] && [ -z "${SOPS_AGE_KEY_FILE:-}" ]; then
    die "set SOPS_AGE_KEY_FILE (or SOPS_AGE_KEY) to the server's age private key"
  fi
  for s in "${secret_files[@]}"; do
    [ -f "$dir/$s.enc" ] || die "missing $dir/$s.enc"
    (umask 077; sops --decrypt --input-type dotenv --output-type dotenv \
      --output "$dir/$s" "$dir/$s.enc")
    chmod 600 "$dir/$s"
  done
  info "Decrypted secrets for $name"
}

# Fail when two backends deployed on this host share a port.
check_ports() {
  local seen="" b key v owner
  for b in "$@"; do
    for key in "${port_keys[@]}"; do
      v=$(env_value "$(backend_dir "$b")/backend.env" "$key")
      [ -n "$v" ] || continue
      owner=$(printf '%s\n' "$seen" | awk -v p="$v" '$1 == p { print $2; exit }')
      [ -z "$owner" ] || die "port $v is used by both $owner and $b/$key"
      seen=$(printf '%s\n%s %s' "$seen" "$v" "$b/$key")
    done
  done
}

# Give the image's non-root django user the bind-mounted static folder.
prepare_static() {
  local name=$1 dir="staticfiles/$1" uid gid
  mkdir -p "$dir"
  uid=$(docker run --rm --entrypoint id "labmango-backend:$name" -u)
  gid=$(docker run --rm --entrypoint id "labmango-backend:$name" -g)
  if [ "$(stat -c '%u' "$dir")" != "$uid" ]; then
    chown "$uid:$gid" "$dir" 2>/dev/null || sudo chown "$uid:$gid" "$dir" \
      || die "cannot chown $dir to $uid:$gid; run: sudo chown $uid:$gid $dir"
  fi
}

cmd_deploy() {
  local backends=("$@") b
  if [ "${backends[0]:-}" = "--all" ]; then
    mapfile -t backends < <(all_backends)
    [ "${#backends[@]}" -gt 0 ] || die "no backends in $envs_root"
  fi
  [ "${#backends[@]}" -gt 0 ] || usage
  for b in "${backends[@]}"; do require_backend "$b"; done
  check_ports "${backends[@]}"
  for b in "${backends[@]}"; do
    info "Deploying $b"
    cmd_decrypt "$b"
    compose "$b" build
    prepare_static "$b"
    compose "$b" up -d --remove-orphans
    compose "$b" ps
  done
}

[ $# -ge 1 ] || usage
command=$1; shift
case "$command" in
  list) cmd_list ;;
  init|encrypt|decrypt) [ $# -eq 1 ] || usage; "cmd_$command" "$1" ;;
  deploy) cmd_deploy "$@" ;;
  down|ps|logs|restart|config)
    [ $# -ge 1 ] || usage
    name=$1; shift; require_backend "$name"
    compose "$name" "$command" "$@" ;;
  -h|--help|help) usage ;;
  *) usage ;;
esac
