#!/bin/sh
# verify-images.sh - READ-ONLY check of downloaded OpenWrt images for the NX62.
#
# Usage:
#   verify-images.sh --dir /ABS/download-dir --version 25.12.6 [--fetch]
#
# --fetch downloads (over HTTPS) the official sha256sums and profiles.json for
# that release from downloads.openwrt.org into --dir. Without it, both files
# must already be there.
#
# Checks, for the three images this procedure uses (FIP, initramfs recovery,
# squashfs sysupgrade) and, if present, the preloader:
#   * exact filename for device netcore_n60-pro (NOT netcore_n60, the non-Pro)
#   * sha256 matches the official sha256sums line
#   * sha256 and size match profiles.json (firmware-selector metadata)
#   * file type by magic bytes: FIP ToC (01 00 64 aa) / FIT image (d0 0d fe ed)
#   * profiles.json lists netcore,n60-pro as the supported device
# Writes $NX62_WORK/images-verified on success.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

DIR=""; VER=""; FETCH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --version) VER="$2"; shift 2 ;;
    --fetch) FETCH=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
if [ -z "$DIR" ] || ! is_abs "$DIR"; then die "--dir must be an absolute path"; fi
[ -n "$VER" ] || die "--version is required (e.g. 25.12.6) - pick it deliberately"
[ -d "$DIR" ] || die "no such directory: $DIR"

BASE="https://downloads.openwrt.org/releases/$VER/targets/mediatek/filogic"
if [ "$FETCH" -eq 1 ]; then
  for f in sha256sums profiles.json; do
    curl -fsSL --proto '=https' -o "$DIR/$f" "$BASE/$f" || die "could not download $BASE/$f"
  done
fi
[ -s "$DIR/sha256sums" ] || die "missing $DIR/sha256sums (use --fetch)"

P="openwrt-$VER-mediatek-filogic-$NX62_DEVICE_ID"
FAIL=0

magic() { od -An -tx1 -N4 "$1" | tr -d ' \n'; }

check() { # file expected_magic required(1/0)
  f="$1"; m="$2"; req="$3"
  if [ ! -f "$DIR/$f" ]; then
    if [ "$req" -eq 1 ]; then bad "missing $f"; FAIL=$((FAIL + 1)); else say "  [SKIP] $f not downloaded (not needed by this procedure)"; fi
    return
  fi
  official=$(awk -v f="$f" '{n=$2; sub(/^\*/,"",n); if (n==f) print $1}' "$DIR/sha256sums")
  actual=$(sha256_of "$DIR/$f")
  if [ -z "$official" ]; then bad "$f is not listed in sha256sums for $VER"; FAIL=$((FAIL + 1)); return; fi
  if [ "$official" != "$actual" ]; then bad "$f sha256 MISMATCH (got $actual, official $official) - re-download"; FAIL=$((FAIL + 1)); return; fi
  ok "$f sha256 matches official sha256sums"
  got_magic=$(magic "$DIR/$f")
  if [ "$got_magic" = "$m" ]; then ok "$f file type looks right (magic $got_magic)"
  else bad "$f unexpected magic $got_magic (expected $m)"; FAIL=$((FAIL + 1)); fi
  if [ -s "$DIR/profiles.json" ] && command -v python3 >/dev/null 2>&1; then
    meta=$(python3 - "$DIR/profiles.json" "$f" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
p = d.get("profiles", {}).get("netcore_n60-pro")
if not p:
    print("NOPROFILE"); sys.exit()
devs = ",".join(p.get("supported_devices", []))
for i in p.get("images", []):
    if i["name"] == sys.argv[2]:
        print(i["sha256"], i["size"], devs); break
else:
    print("NOIMAGE")
PY
)
    case "$meta" in
      NOPROFILE) bad "profiles.json has no netcore_n60-pro profile"; FAIL=$((FAIL + 1)) ;;
      NOIMAGE) warn "$f not listed in profiles.json" ;;
      *)
        m_sha=$(echo "$meta" | awk '{print $1}'); m_size=$(echo "$meta" | awk '{print $2}'); m_dev=$(echo "$meta" | awk '{print $3}')
        if [ "$m_sha" = "$actual" ] && [ "$m_size" = "$(fsize "$DIR/$f")" ]; then ok "$f matches profiles.json (sha256 + size $m_size)"
        else bad "$f differs from profiles.json"; FAIL=$((FAIL + 1)); fi
        case "$m_dev" in *"$NX62_COMPAT"*) ;; *) bad "profiles.json supported_devices is '$m_dev', expected $NX62_COMPAT"; FAIL=$((FAIL + 1)) ;; esac ;;
    esac
  else
    warn "profiles.json or python3 not available - skipped metadata cross-check"
  fi
}

say "=== Verifying OpenWrt $VER images in $DIR ==="
check "$P-bl31-uboot.fip" 010064aa 1
check "$P-initramfs-recovery.itb" d00dfeed 1
check "$P-squashfs-sysupgrade.itb" d00dfeed 1
check "$P-preloader.bin" 5350494e 0

# Guard against the classic mix-ups.
for wrong in "$DIR"/openwrt-*-netcore_n60-[!p]* "$DIR"/openwrt-*-netcore_n60-squashfs* "$DIR"/*factory*; do
  [ -e "$wrong" ] && warn "found $(basename "$wrong") - that is NOT an NX62 / N60 Pro image for this procedure. Move it out of this folder."
done

say ""
if [ "$FAIL" -eq 0 ]; then
  marker images-verified
  printf '%s\n%s\n' "$DIR" "$VER" > "$NX62_WORK/images-info"
  say "IMAGES_VERIFY=PASS"
  say "Use: FIP=$DIR/$P-bl31-uboot.fip"
  say "     RECOVERY=$DIR/$P-initramfs-recovery.itb (TFTP name: $NX62_TFTP_NAME)"
  say "     SYSUPGRADE=$DIR/$P-squashfs-sysupgrade.itb"
  say "The preloader (BL2) is NOT used by this skill."
else
  say "IMAGES_VERIFY=FAIL ($FAIL problems). Do not continue."
  exit 1
fi
