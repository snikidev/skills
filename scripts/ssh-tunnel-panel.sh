#!/usr/bin/env bash
# Open a local SSH tunnel to the 3x-ui panel so the API can be used without
# publishing the panel port.
#
# Usage:
#   ./scripts/ssh-tunnel-panel.sh USER@VM_IP [panel-port] [local-port]
# If panel-port is omitted, the script SSHes in and reads
# /etc/x-ui/install-result.env (requires sudo on the VM unless you are root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
require_cmd ssh

TARGET="${1:-}"
[[ -n "$TARGET" ]] || die "usage: $0 USER@VM_IP [panel-port] [local-port]"
PANEL_PORT="${2:-}"
LOCAL_PORT="${3:-2053}"

if [[ -z "$PANEL_PORT" ]]; then
  log "Reading panel port from /etc/x-ui/install-result.env on $TARGET"
  PANEL_PORT="$(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$TARGET" \
    'sudo bash -c "set -a; source /etc/x-ui/install-result.env; set +a; printf %s \"\$XUI_PANEL_PORT\""')"
  [[ -n "$PANEL_PORT" ]] || die "could not read XUI_PANEL_PORT from the VM"
fi

log "Tunnel: localhost:${LOCAL_PORT} -> ${TARGET}:127.0.0.1:${PANEL_PORT}"
log "Leave this running. In another terminal, point PANEL_BASE_URL at:"
log "  http://127.0.0.1:${LOCAL_PORT}/<webBasePath>"
exec ssh -N -L "${LOCAL_PORT}:127.0.0.1:${PANEL_PORT}" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o StrictHostKeyChecking=accept-new \
  "$TARGET"
