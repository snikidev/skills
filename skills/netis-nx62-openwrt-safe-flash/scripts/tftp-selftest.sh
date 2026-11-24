#!/bin/sh
# tftp-selftest.sh - READ-ONLY proof that your TFTP server serves the recovery
# image under the exact name the OpenWrt U-Boot requests, with blksize 1468.
#
# Usage:
#   tftp-selftest.sh --image /ABS/openwrt-<VER>-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb
#                    [--server 192.168.1.254]
#
# The name U-Boot asks for (from OpenWrt's U-Boot default env, bootfile=) is:
#   openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb
# Writes $NX62_WORK/tftp-selftest.ok on success.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

IMG=""; SERVER="$NX62_HOST_IP"
while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMG="$2"; shift 2 ;;
    --server) SERVER="$2"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
if [ -z "$IMG" ] || [ ! -f "$IMG" ]; then die "--image must point at the versioned recovery .itb you verified"; fi
command -v curl >/dev/null 2>&1 || die "curl is required"

TMP=$(mktemp "${TMPDIR:-/tmp}/nx62-tftp.XXXXXX") || die "mktemp failed"
trap 'rm -f "$TMP"' EXIT INT TERM
say "Fetching tftp://$SERVER/$NX62_TFTP_NAME with blksize 1468 ..."
if ! curl -s --max-time 120 --tftp-blksize 1468 -o "$TMP" "tftp://$SERVER/$NX62_TFTP_NAME"; then
  bad "TFTP fetch failed: is the server running, bound to $SERVER, UDP/69 open, file present under that exact name?"
  exit 1
fi
want=$(sha256_of "$IMG"); got=$(sha256_of "$TMP")
if [ "$want" = "$got" ]; then
  ok "served file is byte-identical to the verified image (sha256 $got)"
  marker tftp-selftest.ok
  say "TFTP_SELFTEST=PASS"
else
  bad "served file differs (served $got, expected $want)"
  say "TFTP_SELFTEST=FAIL"; exit 1
fi
