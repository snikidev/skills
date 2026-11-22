#!/usr/bin/env bash
# Install a pinned 3x-ui release with the official installer (systemd, not Docker).
#
# Run on the VM as root (or via sudo). This follows the sniki.dev gotcha:
# download the script, then run it — never `sudo bash <(curl ...)`.
#
# Default pin: v3.11.0 (released 2026-10-25, bundles Xray-core v26.10.21).
# Override with XUI_VERSION=vX.Y.Z after reading that tag's release notes.
#
# Non-interactive env (official installer):
#   XUI_NONINTERACTIVE=1
#   XUI_USERNAME, XUI_PASSWORD, XUI_PANEL_PORT, XUI_WEB_BASE_PATH  (optional)
# Credentials land in /etc/x-ui/install-result.env (mode 600).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/lib.sh" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/lib.sh"
else
  log() { printf '%s\n' "$*" >&2; }
  die() { printf 'error: %s\n' "$*" >&2; exit 1; }
  require_cmd() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
fi

if [[ "${EUID}" -ne 0 ]]; then
  die "run this script as root (sudo ./install-3xui.sh)"
fi

XUI_VERSION="${XUI_VERSION:-v3.11.0}"
INSTALL_URL="https://raw.githubusercontent.com/MHSanaei/3x-ui/${XUI_VERSION}/install.sh"
INSTALLER="/tmp/3x-ui-install-${XUI_VERSION}.sh"
ENABLE_UFW="${ENABLE_UFW:-0}"
ENABLE_BBR="${ENABLE_BBR:-1}"

export DEBIAN_FRONTEND=noninteractive
require_cmd curl bash

log "Updating apt and installing curl ca-certificates openssl qrencode jq python3..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y --no-install-recommends \
    ca-certificates curl openssl jq python3 qrencode bash
else
  log "apt-get not found; install curl, openssl, jq, python3, and qrencode yourself"
fi

if [[ "$ENABLE_BBR" == "1" ]]; then
  log "Enabling BBR congestion control"
  cat >/etc/sysctl.d/99-vpn-bbr.conf <<'SYSCTL'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
SYSCTL
  sysctl --system >/dev/null || sysctl -p /etc/sysctl.d/99-vpn-bbr.conf || true
fi

if [[ "$ENABLE_UFW" == "1" ]]; then
  command -v ufw >/dev/null 2>&1 || apt-get install -y ufw
  log "Configuring UFW (SSH, 443/tcp). Panel stays closed."
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH || ufw allow 22/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

log "Downloading official installer from tag ${XUI_VERSION}"
curl -fsSL --retry 5 --retry-delay 2 -o "$INSTALLER" "$INSTALL_URL"
chmod 700 "$INSTALLER"
# Sanity check: refuse to run an HTML error page or an empty file.
if ! grep -q 'XUI_NONINTERACTIVE' "$INSTALLER"; then
  die "downloaded installer does not look like 3x-ui install.sh; check $INSTALL_URL"
fi

log "Running official installer (non-interactive, tag ${XUI_VERSION})"
# Passing the tag as $1 pins the release archive (and its .sha256) rather than
# whatever "latest" is that day. stdin is not a TTY here anyway, but we set
# the flag explicitly.
export XUI_NONINTERACTIVE=1
# Leave SSL off; the panel should be reached over an SSH tunnel, not the
# public internet. See scripts/ssh-tunnel-panel.sh.
export XUI_SSL_MODE="${XUI_SSL_MODE:-none}"
bash "$INSTALLER" "$XUI_VERSION"

RESULT=/etc/x-ui/install-result.env
if [[ ! -f "$RESULT" ]]; then
  die "installer finished but $RESULT is missing"
fi
chmod 600 "$RESULT" || true

# shellcheck disable=SC1090
source "$RESULT"

log "3x-ui ${XUI_VERSION} installed."
log "  Panel port:    ${XUI_PANEL_PORT:-unknown}"
log "  Web base path: ${XUI_WEB_BASE_PATH:-unknown}"
log "  Username:      ${XUI_USERNAME:-unknown}"
log "  Password:      (sudo cat $RESULT)"
log "  API token:     (sudo cat $RESULT)"
log "Do not expose the panel port publicly. Tunnel it:"
log "  ssh -N -L 2053:127.0.0.1:${XUI_PANEL_PORT:-PORT} USER@VM_IP"
log "Then set PANEL_BASE_URL=http://127.0.0.1:2053/${XUI_WEB_BASE_PATH:-} and run configure-inbounds.py"

# Print a machine-readable hint (no secrets) for the operator.
printf 'XUI_VERSION=%s\n' "$XUI_VERSION"
printf 'XUI_PANEL_PORT=%s\n' "${XUI_PANEL_PORT:-}"
printf 'XUI_WEB_BASE_PATH=%s\n' "${XUI_WEB_BASE_PATH:-}"
printf 'XUI_INSTALL_RESULT=%s\n' "$RESULT"
