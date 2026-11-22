#!/usr/bin/env bash
# Verify that the optional ISP SOCKS5 proxy works, and print a client test
# checklist. Run on the VM (or any host that can reach the proxy).
#
# Usage:
#   PROXY_HOST=... PROXY_PORT=12324 PROXY_USER=... PROXY_PASS=... ./scripts/verify-egress.sh
# Direct SOCKS test (no Xray involved):
#   curl -s --proxy socks5h://USER:PASS@HOST:PORT https://ipinfo.io/json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
maybe_load_local_env
require_cmd curl jq

PROXY_HOST="${PROXY_HOST:-}"
PROXY_PORT="${PROXY_PORT:-12324}"
PROXY_USER="${PROXY_USER:-}"
PROXY_PASS="${PROXY_PASS:-}"
VPS_IP="${PUBLIC_IP:-${VPS_IP:-}}"

echo "=== Host egress (this machine, no proxy) ==="
HOST_JSON="$(curl -4 -fsS --max-time 15 https://ipinfo.io/json || true)"
if [[ -n "$HOST_JSON" ]]; then
  echo "$HOST_JSON" | jq -r '{ip, org, city, country, hostname}'
  HOST_IP="$(echo "$HOST_JSON" | jq -r '.ip // empty')"
else
  log "warning: could not reach ipinfo.io from this host"
  HOST_IP=""
fi

if [[ -z "$PROXY_HOST" ]]; then
  log "No PROXY_HOST set. Skipping SOCKS tests. Destination sites will see the VM IP above."
  log "Client checklist:"
  log "  1. nc -zv ${VPS_IP:-VM_IP} 443"
  log "  2. Import the vless:// link, connect, open https://ipinfo.io/json — expect the VM IP."
  log "  3. Optional: import the ss:// link in Outline and repeat."
  log "  4. https://browserleaks.com/dns and /webrtc for leak checks."
  exit 0
fi

if [[ -n "$PROXY_USER" ]]; then
  PROXY_URL="socks5h://${PROXY_USER}:${PROXY_PASS}@${PROXY_HOST}:${PROXY_PORT}"
else
  PROXY_URL="socks5h://${PROXY_HOST}:${PROXY_PORT}"
fi

echo
echo "=== SOCKS5 proxy egress (${PROXY_HOST}:${PROXY_PORT}) ==="
# --proxy plus socks5h:// forces remote DNS. The older --socks5 flag may
# resolve DNS locally and leak the VPS resolver.
set +e
PROXY_JSON="$(curl -4 -fsS --max-time 20 --proxy "$PROXY_URL" https://ipinfo.io/json 2>/tmp/proxy-curl.err)"
PROXY_STATUS=$?
set -e
if [[ $PROXY_STATUS -ne 0 || -z "$PROXY_JSON" ]]; then
  log "SOCKS test failed (curl exit $PROXY_STATUS). First lines of stderr:"
  sed -n '1,8p' /tmp/proxy-curl.err >&2 || true
  die "the ISP proxy did not return ipinfo.io — check host/port/user/pass and that the product is a static ISP proxy (not rotating residential)."
fi
echo "$PROXY_JSON" | jq -r '{ip, org, city, country, hostname}'
PROXY_IP="$(echo "$PROXY_JSON" | jq -r '.ip // empty')"
PROXY_ORG="$(echo "$PROXY_JSON" | jq -r '.org // empty')"

if [[ -n "$HOST_IP" && "$PROXY_IP" == "$HOST_IP" ]]; then
  die "proxy IP equals the VM IP ($HOST_IP). Egress is not going through the ISP proxy."
fi

echo
echo "=== ipapi.is classification for $PROXY_IP ==="
API_JSON="$(curl -4 -fsS --max-time 15 "https://api.ipapi.is/?q=${PROXY_IP}" || true)"
if [[ -n "$API_JSON" ]]; then
  echo "$API_JSON" | jq '{ip, asn: .asn, company: .company, is_datacenter: .is_datacenter, is_proxy: .is_proxy, is_vpn: .is_vpn, type: .company.type}' || echo "$API_JSON"
else
  log "ipapi.is lookup skipped (request failed)"
fi

echo
log "SOCKS egress IP: $PROXY_IP  ASN/org: $PROXY_ORG"
log "If is_datacenter is true, this IP will not look like a residential ISP — pick another."
log "Also open https://scamalytics.com/ip/${PROXY_IP} in a browser."
echo
log "Client checklist (after importing the generated links):"
log "  1. nc -zv ${VPS_IP:-VM_IP} 443   # must succeed before blaming Xray"
log "  2. Connect with VLESS, then https://ipinfo.io/json — must show $PROXY_IP, not ${HOST_IP:-the VM IP}"
log "  3. Repeat with the Outline ss:// link"
log "  4. https://browserleaks.com/dns  — no home-ISP or VM-datacentre resolvers"
log "  5. https://browserleaks.com/webrtc"
log "  6. Optional speed test: https://speed.cloudflare.com"
