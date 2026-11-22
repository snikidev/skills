# shellcheck shell=bash
# Shared helpers. Scripts that source this file should already have run
# `set -euo pipefail`. Do not source this from an interactive shell.

log() { printf '%s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
  done
}

# Load KEY=value pairs from a file (e.g. a local .env or the VM's
# /etc/x-ui/install-result.env). Values written with printf %q can be
# eval'd safely; we only accept assignments, never bare commands.
load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || die "env file not found: $file"
  # shellcheck disable=SC1090
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}

maybe_load_local_env() {
  local root candidate
  root="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
  for candidate in "${ENV_FILE:-}" "$PWD/.env" "$root/.env"; do
    if [[ -n "${candidate:-}" && -f "$candidate" ]]; then
      log "Loading $candidate"
      load_env_file "$candidate"
      return 0
    fi
  done
}

detect_public_ip() {
  local ip=""
  ip="$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  if [[ -z "$ip" ]]; then
    ip="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
  fi
  printf '%s' "$ip"
}

default_ssh_pub() {
  if [[ -n "${SSH_PUBLIC_KEY_FILE:-}" ]]; then
    [[ -f "$SSH_PUBLIC_KEY_FILE" ]] || die "SSH_PUBLIC_KEY_FILE not found: $SSH_PUBLIC_KEY_FILE"
    printf '%s' "$SSH_PUBLIC_KEY_FILE"
    return
  fi
  local candidate
  for candidate in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  done
  die "no SSH public key found; set SSH_PUBLIC_KEY_FILE or create ~/.ssh/id_ed25519.pub"
}

wait_for_ssh() {
  local host="$1"
  local user="$2"
  local tries="${3:-36}"
  local i
  for ((i = 1; i <= tries; i++)); do
    if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      "${user}@${host}" 'echo ok' >/dev/null 2>&1; then
      log "SSH ready on ${user}@${host}"
      return 0
    fi
    log "Waiting for SSH on ${user}@${host} ($i/$tries)..."
    sleep 5
  done
  die "SSH did not become ready on ${user}@${host}"
}

repo_root() {
  cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd
}
