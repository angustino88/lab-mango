#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$repo_root"

force=0
for arg in "$@"; do
  case "$arg" in --force) force=1 ;; esac
done

case "${1:-}" in
  encrypt|decrypt) action="$1" ;;
  *) printf '%s\n' "Usage: ./scripts/sops/sops-env.sh encrypt|decrypt [--force] [age-key-file]" >&2; exit 2 ;;
esac

if [ "$action" = decrypt ] && [ -n "${2:-}" ]; then
  export SOPS_AGE_KEY="$2"
fi

for plain_file in .env .envs/.local/.django .envs/.local/.postgres .envs/.production/.django .envs/.production/.postgres; do
  encrypted_file="${plain_file}.enc"
  if [ "$action" = encrypt ]; then
    : "${SOPS_AGE_RECIPIENT:?Set SOPS_AGE_RECIPIENT to your age public key for encryption}"
    test -f "$plain_file" || { printf 'Missing plaintext file: %s\n' "$plain_file" >&2; exit 1; }
    if [ "$force" = 0 ] && [ -f "$encrypted_file" ] && [ "$encrypted_file" -nt "$plain_file" ]; then
      printf 'Skipping %s (unchanged)\n' "$plain_file"
      continue
    fi
    sops --encrypt --age "$SOPS_AGE_RECIPIENT" --input-type dotenv --output-type dotenv --output "$encrypted_file" "$plain_file"
    printf 'Encrypted %s -> %s\n' "$plain_file" "$encrypted_file"
  else
    if [ -z "${SOPS_AGE_KEY:-}" ] && [ -z "${SOPS_AGE_KEY_FILE:-}" ]; then
      printf '%s\n' 'Provide the age private key as the second argument, or set SOPS_AGE_KEY/SOPS_AGE_KEY_FILE' >&2
      exit 1
    fi
    test -f "$encrypted_file" || { printf 'Missing encrypted file: %s\n' "$encrypted_file" >&2; exit 1; }
    sops --decrypt --input-type dotenv --output-type dotenv --output "$plain_file" "$encrypted_file"
    printf 'Decrypted %s -> %s\n' "$encrypted_file" "$plain_file"
  fi
done
