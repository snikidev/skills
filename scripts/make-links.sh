#!/usr/bin/env bash
# Build a vless:// link (and an optional QR code) from inbound state.
#
# The panel /panel/api/inbounds/allLinks response uses the Host header of the
# request (often 127.0.0.1 via the SSH tunnel). This script always writes
# a link that uses PUBLIC_IP, which is what Reality needs.
#
# Usage:
#   PUBLIC_IP=x.x.x.x STATE_FILE=./out/state.json ./scripts/make-links.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
maybe_load_local_env
require_cmd python3

PUBLIC_IP="${PUBLIC_IP:-}"
STATE_FILE="${STATE_FILE:-}"
OUT_DIR="${OUT_DIR:-./out}"
VLESS_PORT="${VLESS_PORT:-443}"
SNI="${REALITY_SNI:-${SNI:-www.microsoft.com}}"

if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(detect_public_ip)"
fi
[[ -n "$PUBLIC_IP" ]] || die "set PUBLIC_IP to the VM's public IPv4"
[[ -n "$STATE_FILE" && -f "$STATE_FILE" ]] || die "set STATE_FILE to the JSON written by configure-inbounds.py"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR" || true

python3 "$SCRIPT_DIR/render_links.py" "$PUBLIC_IP" "$STATE_FILE" "$OUT_DIR" "$VLESS_PORT" "$SNI"

if command -v qrencode >/dev/null 2>&1 && [[ -s "$OUT_DIR/links.txt" ]]; then
  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    png="$OUT_DIR/qr-vless.png"
    qrencode -t PNG -o "$png" "$link"
    chmod 600 "$png" || true
    log "QR written to $png"
    log "Terminal QR:"
    qrencode -t ANSIUTF8 "$link" >&2 || true
  done < "$OUT_DIR/links.txt"
else
  log "qrencode not installed; skipped QR codes (apt install qrencode)"
fi

if [[ -n "${PANEL_BASE_URL:-}" ]]; then
  log "Fetching panel allLinks for comparison (host may be 127.0.0.1; prefer links.txt)"
  export SCRIPT_DIR
  python3 -c "
import os, sys
sys.path.insert(0, os.environ[\"SCRIPT_DIR\"])
from xui_api import XUIClient, XUIError
c = XUIClient.from_env()
if not c.token:
    c.login()
try:
    links = c.all_links()
except XUIError as exc:
    print(\"allLinks skipped:\", exc, file=sys.stderr)
    raise SystemExit(0)
for item in links:
    print(\"panel:\", item)
" || log "allLinks fetch skipped"
fi

log "Link saved under $OUT_DIR/links.txt (mode 600). Re-export after any inbound change."
