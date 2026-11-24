#!/bin/sh
# tunnel.sh - open, check or close the SSH tunnel to the 3x-ui panel.
#
#   tunnel.sh check    READ-ONLY: is something listening on 127.0.0.1:$PANEL_LOCAL_PORT,
#                      and does it answer like the panel?
#   tunnel.sh open     start a background tunnel (ssh -f -N -L ...), using a
#                      control socket so `close` can stop exactly this tunnel
#   tunnel.sh close    stop the tunnel opened by `open`
#
# Reads VPS_SSH, PANEL_REMOTE_PORT, PANEL_LOCAL_PORT (default 2053),
# PANEL_BASE_PATH and VPS_SSH_KEY from the environment or the env file
# ($VLESS_OPS_ENV, default ~/.config/vless-ops/.env). Prints names, never secrets.
set -u
ENV_FILE="${VLESS_OPS_ENV:-$HOME/.config/vless-ops/.env}"

# Load only the non-secret keys this script needs.
load() {
  _k="$1"
  eval "_cur=\${$_k:-}"
  # shellcheck disable=SC2154
  if [ -z "$_cur" ] && [ -f "$ENV_FILE" ]; then
    _v=$(sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}$_k=//p" "$ENV_FILE" | tail -n 1 | sed "s/^[\"']//; s/[\"']\$//")
    [ -n "$_v" ] && eval "$_k=\$_v"
  fi
}
for k in VPS_SSH VPS_SSH_KEY PANEL_REMOTE_PORT PANEL_LOCAL_PORT PANEL_BASE_PATH OPS_STATE_DIR; do load "$k"; done
PANEL_LOCAL_PORT="${PANEL_LOCAL_PORT:-2053}"
STATE="${OPS_STATE_DIR:-$HOME/.local/state/vless-ops}"
case "$STATE" in "~"*) STATE="$HOME${STATE#\~}" ;; esac
SOCK="$STATE/tunnel.sock"
BASE="http://127.0.0.1:$PANEL_LOCAL_PORT/$(printf '%s' "${PANEL_BASE_PATH:-}" | sed 's#^/##; s#/$##')"

need() { eval "_x=\${$1:-}"; [ -n "$_x" ] || { echo "ERROR: $1 not set (env or $ENV_FILE)" >&2; exit 2; }; }

ssh_base() {
  if [ -n "${VPS_SSH_KEY:-}" ]; then
    set -- -i "$VPS_SSH_KEY" "$@"
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 "$@"
}

check() {
  echo "Checking 127.0.0.1:$PANEL_LOCAL_PORT (local only, no credentials used)"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE/csrf-token" 2>/dev/null || true)
  case "$code" in
    200) echo "TUNNEL=UP panel answered GET ${BASE}/csrf-token with HTTP 200"; return 0 ;;
    000|"") echo "TUNNEL=DOWN nothing answered on 127.0.0.1:$PANEL_LOCAL_PORT"; return 1 ;;
    *) echo "TUNNEL=UNEXPECTED HTTP $code from ${BASE}/csrf-token (wrong PANEL_BASE_PATH or not the panel?)"; return 1 ;;
  esac
}

case "${1:-check}" in
  check) check ;;
  open)
    need VPS_SSH; need PANEL_REMOTE_PORT
    mkdir -p "$STATE" && chmod 700 "$STATE"
    if check >/dev/null 2>&1; then echo "TUNNEL=UP already (not opening a second one)"; exit 0; fi
    echo "Opening: ssh -f -N -L 127.0.0.1:$PANEL_LOCAL_PORT:127.0.0.1:$PANEL_REMOTE_PORT $VPS_SSH"
    echo "Credential: SSH ${VPS_SSH_KEY:+key $VPS_SSH_KEY }via host $VPS_SSH (~/.ssh/config)"
    ssh_base -f -N -M -S "$SOCK" -L "127.0.0.1:$PANEL_LOCAL_PORT:127.0.0.1:$PANEL_REMOTE_PORT" "$VPS_SSH" || exit 1
    sleep 1; check ;;
  close)
    need VPS_SSH
    if [ -S "$SOCK" ]; then ssh -S "$SOCK" -O exit "$VPS_SSH" 2>/dev/null; echo "TUNNEL=CLOSED"; else echo "no tunnel control socket at $SOCK (nothing to close)"; fi ;;
  *) echo "usage: tunnel.sh check|open|close" >&2; exit 2 ;;
esac
