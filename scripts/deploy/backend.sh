#!/usr/bin/env bash
# Deploy and manage LabMango department backends with docker-compose.prod.yml.
#
# Committed (all SOPS-encrypted):   .envs/.production/<department>/{.backend,.django,.postgres}.enc
# Server state (never committed):   $LABMANGO_DATA_DIR/<department>/  (default /srv/labmango/<department>)
#   .backend .django .postgres      decrypted on every deploy, mode 600
#   staticfiles/                    collectstatic output
#   ssl/server.crt, ssl/server.key  nginx TLS (profile "nginx")
# Optional extra CA certificates for the image build: $LABMANGO_DATA_DIR/ca-certificates/*.crt
#
# See scripts/deploy/README.md.
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$repo_root"

envs_root=.envs/.production
compose_file=docker-compose.prod.yml
config_files=(.backend .django .postgres)
port_keys=(UVICORN_PORT REDIS_PORT NGINX_HTTP_PORT NGINX_HTTPS_PORT POSTGRES_PORT)
data_dir=${LABMANGO_DATA_DIR:-/srv/labmango}

# The server's age key: default location unless the caller set one.
if [ -z "${SOPS_AGE_KEY:-}" ] && [ -z "${SOPS_AGE_KEY_FILE:-}" ] && [ -r /etc/labmango/age.key ]; then
  export SOPS_AGE_KEY_FILE=/etc/labmango/age.key
fi

usage() {
  cat >&2 <<'EOF'
Usage: scripts/deploy/backend.sh <command> [department...]

Configuration (developer machine; files stay encrypted in git):
  list                            Departments and their encrypted files
  init <department>               Create plaintext .backend/.django/.postgres from the templates
  encrypt <department> [--keep]   Encrypt them to *.enc (recipients from .sops.yaml) and delete the plaintext
  edit <department> <file>        Edit an encrypted file in place: file is backend, django or postgres
  updatekeys <department>         Re-encrypt after recipients changed in .sops.yaml

Deployment (server; needs the server's age key, default /etc/labmango/age.key):
  decrypt <department>            Decrypt to the state folder only
  deploy <department>...|--all    Decrypt to the state folder, build and start
  down <department>               Stop and remove containers (database volumes are kept)
  ps|logs|restart|config <department> [args]
                                  Pass through to docker compose for that department
EOF
  exit 2
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '==> %s\n' "$*" >&2; }

validate_name() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{0,39}$ ]] \
    || die "department name '$1' must be lowercase letters, digits, '-' or '_' (max 40 chars)"
}

dept_dir() { printf '%s/%s' "$envs_root" "$1"; }
state_dir() { printf '%s/%s' "$data_dir" "$1"; }

require_dept() {
  validate_name "$1"
  local f
  for f in "${config_files[@]}"; do
    [ -f "$(dept_dir "$1")/$f.enc" ] \
      || die "missing $(dept_dir "$1")/$f.enc (create with: scripts/deploy/backend.sh init $1)"
  done
}

all_depts() {
  local f
  for f in "$envs_root"/*/.backend.enc; do
    [ -f "$f" ] && basename "$(dirname "$f")"
  done
}

require_sops() { command -v sops >/dev/null || die "sops is not installed (scripts/sops/README.md)"; }

# Read KEY from a dotenv file without sourcing it.
env_value() {
  sed -n "s/^[[:space:]]*$2=\\(.*\\)$/\\1/p" "$1" | tail -n 1 | tr -d '"'"'"' \r'
}

sops_dotenv() { sops --input-type dotenv --output-type dotenv "$@"; }

compose() {
  local name=$1; shift
  local state; state=$(state_dir "$name")
  [ -f "$state/.backend" ] || die "$state/.backend not found; run: scripts/deploy/backend.sh deploy $name"
  local declared; declared=$(env_value "$state/.backend" BACKEND_NAME)
  [ "$declared" = "$name" ] || die "$name/.backend has BACKEND_NAME=$declared; it must be $name"
  BACKEND_NAME=$name LABMANGO_STATE_DIR=$state docker compose \
    --project-name "labmango-$name" \
    --file "$compose_file" \
    --env-file "$state/.backend" \
    "$@"
}

cmd_list() {
  local d f
  printf '%-24s %s\n' DEPARTMENT FILES
  for d in "$envs_root"/*/; do
    [ -d "$d" ] || continue
    printf '%-24s' "$(basename "$d")"
    for f in "${config_files[@]}"; do
      if [ -f "$d/$f.enc" ]; then printf ' %s.enc' "$f"; else printf ' (missing %s.enc)' "$f"; fi
    done
    printf '\n'
  done
}

cmd_init() {
  local name=$1 dir f; validate_name "$name"; dir=$(dept_dir "$name")
  mkdir -p "$dir"
  for f in "${config_files[@]}"; do
    [ -e "$dir/$f.enc" ] && die "$dir/$f.enc already exists; use: scripts/deploy/backend.sh edit $name ${f#.}"
  done
  (umask 077
   sed "s/^BACKEND_NAME=.*/BACKEND_NAME=$name/" "$envs_root/.backend.example" > "$dir/.backend"
   cp "$envs_root/.django.example" "$dir/.django"
   cp "$envs_root/.postgres.example" "$dir/.postgres")
  info "Created plaintext $dir/.backend, .django and .postgres (git-ignored)"
  info "Next: fill in every replace-with-* value, then: scripts/deploy/backend.sh encrypt $name"
}

# Encrypt with .sops.yaml rules; SOPS_AGE_RECIPIENT overrides them when set.
encrypt_file() {
  local in=$1 out=$2
  if [ -n "${SOPS_AGE_RECIPIENT:-}" ]; then
    sops_dotenv --encrypt --age "$SOPS_AGE_RECIPIENT" --output "$out" "$in"
  else
    [ -f .sops.yaml ] || die "no .sops.yaml (copy .sops.yaml.example) and SOPS_AGE_RECIPIENT is not set"
    sops_dotenv --encrypt --output "$out" "$in"
  fi
}

cmd_encrypt() {
  local name=$1 keep=${2:-} dir f; validate_name "$name"; dir=$(dept_dir "$name"); require_sops
  for f in "${config_files[@]}"; do
    [ -f "$dir/$f" ] || die "missing plaintext $dir/$f"
  done
  [ "$(env_value "$dir/.backend" BACKEND_NAME)" = "$name" ] || die "$dir/.backend must set BACKEND_NAME=$name"
  for f in "${config_files[@]}"; do
    grep -q 'replace-with-' "$dir/$f" && printf 'warning: %s still contains replace-with-* values\n' "$dir/$f" >&2
    encrypt_file "$dir/$f" "$dir/$f.enc"
    info "Encrypted $dir/$f -> $dir/$f.enc"
  done
  if [ "$keep" != "--keep" ]; then
    for f in "${config_files[@]}"; do rm -f "$dir/$f"; done
    info "Removed plaintext files; change values later with: scripts/deploy/backend.sh edit $name <file>"
  fi
}

cmd_edit() {
  local name=$1 file=${2:-}; require_dept "$name"; require_sops
  case "$file" in backend|django|postgres) ;; *) usage ;; esac
  sops_dotenv "$(dept_dir "$name")/.$file.enc"
}

cmd_updatekeys() {
  local name=$1 f; require_dept "$name"; require_sops
  for f in "${config_files[@]}"; do
    sops updatekeys --yes --input-type dotenv "$(dept_dir "$name")/$f.enc"
  done
}

cmd_decrypt() {
  local name=$1 state f; require_dept "$name"; require_sops
  if [ -z "${SOPS_AGE_KEY:-}" ] && [ -z "${SOPS_AGE_KEY_FILE:-}" ]; then
    die "no age key: put the server key at /etc/labmango/age.key or set SOPS_AGE_KEY_FILE"
  fi
  state=$(state_dir "$name")
  mkdir -p "$state" 2>/dev/null || die "cannot create $state; create $data_dir owned by the deploy user"
  chmod 700 "$state"
  for f in "${config_files[@]}"; do
    (umask 077; sops_dotenv --decrypt --output "$state/$f.tmp" "$(dept_dir "$name")/$f.enc") \
      || die "cannot decrypt $name/$f.enc: this server's key is not a recipient for $name"
    mv "$state/$f.tmp" "$state/$f"
  done
  info "Decrypted $name configuration to $state"
}

# Fail when two departments deployed together on this host share a port.
check_ports() {
  local seen="" d key v owner
  for d in "$@"; do
    for key in "${port_keys[@]}"; do
      v=$(env_value "$(state_dir "$d")/.backend" "$key")
      [ -n "$v" ] || continue
      owner=$(printf '%s\n' "$seen" | awk -v p="$v" '$1 == p { print $2; exit }')
      [ -z "$owner" ] || die "port $v is used by both $owner and $d/$key"
      seen=$(printf '%s\n%s %s' "$seen" "$v" "$d/$key")
    done
  done
}

check_tls() {
  local name=$1 state; state=$(state_dir "$name")
  mkdir -p "$state/ssl"
  case ",$(env_value "$state/.backend" COMPOSE_PROFILES)," in
    *,nginx,*)
      [ -f "$state/ssl/server.crt" ] && [ -f "$state/ssl/server.key" ] \
        || die "profile nginx needs $state/ssl/server.crt and server.key" ;;
  esac
}

# Extra CA certificates kept on the server are added to the image build context.
stage_ca_certificates() {
  local f
  for f in "$data_dir"/ca-certificates/*.crt; do
    [ -f "$f" ] && cp "$f" ssl_certifactes/
  done
  return 0
}

# Give the image's non-root django user the bind-mounted static folder.
prepare_static() {
  local name=$1 dir uid gid
  dir=$(state_dir "$name")/staticfiles
  mkdir -p "$dir"
  uid=$(docker run --rm --entrypoint id "labmango-backend:$name" -u)
  gid=$(docker run --rm --entrypoint id "labmango-backend:$name" -g)
  if [ "$(stat -c '%u' "$dir")" != "$uid" ]; then
    chown "$uid:$gid" "$dir" 2>/dev/null || sudo -n chown "$uid:$gid" "$dir" \
      || die "cannot chown $dir to $uid:$gid; run once: sudo chown $uid:$gid $dir"
  fi
}

cmd_deploy() {
  local depts=("$@") d
  if [ "${depts[0]:-}" = "--all" ]; then
    mapfile -t depts < <(all_depts)
    [ "${#depts[@]}" -gt 0 ] || die "no departments in $envs_root"
  fi
  [ "${#depts[@]}" -gt 0 ] || usage
  for d in "${depts[@]}"; do require_dept "$d"; done
  for d in "${depts[@]}"; do cmd_decrypt "$d"; check_tls "$d"; done
  check_ports "${depts[@]}"
  stage_ca_certificates
  for d in "${depts[@]}"; do
    info "Deploying $d ($(git rev-parse --short HEAD 2>/dev/null || echo 'unknown revision'))"
    compose "$d" build
    prepare_static "$d"
    compose "$d" up -d --remove-orphans
    compose "$d" ps
  done
}

[ $# -ge 1 ] || usage
command=$1; shift
case "$command" in
  list) cmd_list ;;
  init|updatekeys|decrypt) [ $# -eq 1 ] || usage; "cmd_$command" "$1" ;;
  encrypt) [ $# -ge 1 ] || usage; cmd_encrypt "$@" ;;
  edit) [ $# -eq 2 ] || usage; cmd_edit "$1" "$2" ;;
  deploy) cmd_deploy "$@" ;;
  down|ps|logs|restart|config)
    [ $# -ge 1 ] || usage
    name=$1; shift; validate_name "$name"
    compose "$name" "$command" "$@" ;;
  -h|--help|help) usage ;;
  *) usage ;;
esac
