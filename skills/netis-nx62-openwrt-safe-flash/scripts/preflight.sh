#!/bin/sh
# preflight.sh - READ-ONLY go/no-go checklist before any flash write.
#
# Usage:
#   preflight.sh --router useradmin@192.168.1.1 [--phase stock|recovery]
#
# Checks the host (tools, wired IP, default route NOT on the router link, disk),
# the router (ping, SSH, partition map via router-inspect.sh, /tmp space), and
# the markers left by the earlier steps (images verified, backups verified by the
# scripts AND by you, TFTP self-test). Never changes anything.
# Last line: PREFLIGHT=PASS or PREFLIGHT=FAIL.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

ROUTER=""; PHASE=stock
while [ $# -gt 0 ]; do
  case "$1" in
    --router) ROUTER="$2"; shift 2 ;;
    --phase) PHASE="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$ROUTER" ] || die "--router user@ip is required"
FAIL=0
f() { bad "$*"; FAIL=$((FAIL + 1)); }

say "=== Host tools ==="
for t in ssh scp curl od awk; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t"; else f "$t missing"; fi
done
if command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1; then ok "sha256 tool"; else f "no sha256sum/shasum"; fi
if command -v tcpdump >/dev/null 2>&1; then ok "tcpdump (packet-capture gate)"; else warn "tcpdump not found - you need it (or Wireshark) to watch the recovery TFTP request"; fi

say "=== Host network ==="
if command -v ip >/dev/null 2>&1; then
  if ip -4 addr show | grep -q "inet $NX62_HOST_IP/24"; then ok "a wired interface has $NX62_HOST_IP/24"; else f "no interface has $NX62_HOST_IP/24 (U-Boot TFTPs from exactly this address)"; fi
  dev=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1)}' | head -n 1)
  case "$dev" in 192.168.1.*) f "default route goes via $dev (the router link) - remove the gateway from the wired interface" ;; *) ok "internet route is not via the router link (via ${dev:-direct})" ;; esac
elif command -v route >/dev/null 2>&1; then
  if ifconfig 2>/dev/null | grep -q "inet $NX62_HOST_IP "; then ok "a wired interface has $NX62_HOST_IP"; else f "no interface has $NX62_HOST_IP"; fi
  gw=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
  case "$gw" in 192.168.1.*) f "default gateway is $gw (the router link)" ;; *) ok "default gateway is ${gw:-none} (not the router link)" ;; esac
fi
avail=$(df -Pk "$HOME" | awk 'NR==2{print $4}')
if [ "${avail:-0}" -gt 1048576 ]; then ok "more than 1 GiB free in \$HOME"; else f "less than 1 GiB free in \$HOME"; fi

say "=== Router ==="
host=${ROUTER#*@}
if ping -c 1 -W 2 "$host" >/dev/null 2>&1 || ping -c 1 -t 2 "$host" >/dev/null 2>&1; then ok "ping $host"; else f "router $host does not answer ping"; fi
out=$(rssh "$PHASE" "$ROUTER" 'sh -s' < "$HERE/router-inspect.sh" 2>&1)
if printf '%s\n' "$out" | grep -q '^INSPECT_RESULT=OK'; then ok "SSH works and the partition map matches the NX62 / N60 Pro layout"
else f "partition map check failed or SSH failed:"; printf '%s\n' "$out" | grep -E 'MISMATCH|MISSING|INSPECT_RESULT|denied|refused|timed out' | sed 's/^/        /'; fi
tmpkb=$(printf '%s\n' "$out" | awk '/=== memory/{m=1;next} m && /tmp/{print $4; exit}')
if [ -n "$tmpkb" ] && [ "$tmpkb" -gt 16384 ] 2>/dev/null; then ok "router /tmp has ${tmpkb} KiB free"; else warn "could not confirm router /tmp free space (need ~16 MiB for the sysupgrade image)"; fi

say "=== Earlier gates ==="
for m in images-verified backup-verified.auto backup-verified.user tftp-selftest.ok; do
  if has_marker "$m"; then ok "$m ($(cat "$NX62_WORK/$m"))"; else f "$m not recorded - go back and complete that step"; fi
done
if [ -s "$NX62_WORK/backup-paths" ]; then
  while IFS= read -r p; do
    if [ -s "$p/SHA256SUMS" ]; then ok "backup still present at $p"; else f "backup NOT found at $p"; fi
  done < "$NX62_WORK/backup-paths"
fi

say ""
if [ "$FAIL" -eq 0 ]; then say "PREFLIGHT=PASS"; else say "PREFLIGHT=FAIL ($FAIL problems). Do not flash."; exit 1; fi
