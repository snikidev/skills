#!/usr/bin/env bash
# Copy this skill's scripts to a VM and run the official 3x-ui installer there.
#
# Usage:
#   ./scripts/remote-setup.sh debian@VM_IP
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
maybe_load_local_env
require_cmd ssh scp

TARGET="${1:-}"
[[ -n "$TARGET" ]] || die "usage: $0 USER@VM_IP"
REMOTE_DIR="${REMOTE_DIR:-/tmp/vless-vpn-3xui-skill}"

log "Waiting for SSH on $TARGET..."
tries=36
for ((i = 1; i <= tries; i++)); do
  if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
    "$TARGET" 'echo ok' >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" -eq "$tries" ]]; then
    die "cannot SSH to $TARGET"
  fi
  log "Waiting for SSH on $TARGET ($i/$tries)..."
  sleep 5
done

log "Copying scripts and templates to ${TARGET}:${REMOTE_DIR}"
ssh -o StrictHostKeyChecking=accept-new "$TARGET" "mkdir -p '$REMOTE_DIR'"
scp -q -r "$SCRIPT_DIR" "$ROOT/templates" "$TARGET:$REMOTE_DIR/"

log "Running install-3xui.sh on $TARGET (sudo)"
# Forward the version pin and optional installer pins only. Do not scp a local
# .env — it may contain ISP proxy credentials.
ssh -t "$TARGET" "sudo env XUI_VERSION='${XUI_VERSION:-v3.11.0}' \
  XUI_USERNAME='${XUI_USERNAME:-}' \
  XUI_PASSWORD='${XUI_PASSWORD:-}' \
  XUI_PANEL_PORT='${XUI_PANEL_PORT:-}' \
  XUI_WEB_BASE_PATH='${XUI_WEB_BASE_PATH:-}' \
  XUI_SSL_MODE='${XUI_SSL_MODE:-none}' \
  ENABLE_UFW='${ENABLE_UFW:-0}' \
  ENABLE_BBR='${ENABLE_BBR:-1}' \
  bash '${REMOTE_DIR}/scripts/install-3xui.sh'"

log "Install finished. Open a panel tunnel:"
log "  $SCRIPT_DIR/ssh-tunnel-panel.sh $TARGET"
log "Configure inbounds on the VM with:"
log "  sudo bash -c 'set -a; source /etc/x-ui/install-result.env; set +a;"
log "    export PANEL_BASE_URL=http://127.0.0.1:\$XUI_PANEL_PORT/\$XUI_WEB_BASE_PATH;"
log "    python3 ${REMOTE_DIR}/scripts/configure-inbounds.py --state-out /root/inbound-state.json'"
