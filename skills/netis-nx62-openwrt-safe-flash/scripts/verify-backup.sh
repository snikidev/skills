#!/bin/sh
# verify-backup.sh - READ-ONLY re-verification of NX62 MTD backups on the host.
#
# Usage:
#   verify-backup.sh /ABS/primary-backup-dir                 # check #1
#   verify-backup.sh /ABS/primary-dir /ABS/second-copy-dir   # check #2 (both + compare)
#   verify-backup.sh --user-confirm /ABS/primary-dir /ABS/second-copy-dir   # check #3
#
# For every directory it checks: absolute path, required files, every partition
# from proc_mtd.txt present, non-empty, size == /proc/mtd size, sha256 matches
# SHA256SUMS, the critical partitions (bl2, factory, fip, u-boot-env, ubi) exist,
# factory is not blank (all 0xFF/0x00), prints the MACs stored in factory, and
# cross-checks every partition against the whole-chip dump when one exists.
# With two directories it also requires identical SHA256SUMS and warns when both
# live on the same filesystem.
#
# --user-confirm: after the automatic checks pass, prints what YOU should look
# at, then asks you to type a phrase in your own terminal. Only then is the
# backup considered verified for flashing.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

USER_CONFIRM=0
if [ "${1:-}" = "--user-confirm" ]; then USER_CONFIRM=1; shift; fi
[ $# -ge 1 ] || die "usage: verify-backup.sh [--user-confirm] /abs/dir [/abs/second-dir]"
[ $# -le 2 ] || die "at most two directories"

TOTAL_FAIL=0

check_dir() {
  d="$1"; fails=0
  say ""
  say "=== Verifying backup: $d ==="
  is_abs "$d" || { bad "not an absolute path: $d"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); return; }
  [ -d "$d" ] || { bad "directory does not exist: $d"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); return; }
  for req in proc_mtd.txt SHA256SUMS MANIFEST.txt; do
    if [ -s "$d/$req" ]; then ok "$req present"; else bad "$req missing or empty"; fails=$((fails + 1)); fi
  done
  [ -s "$d/proc_mtd.txt" ] || { TOTAL_FAIL=$((TOTAL_FAIL + fails)); return; }

  awk 'NR>1{gsub(/:/,"",$1); gsub(/"/,"",$4); print $1" "$2" "$4}' "$d/proc_mtd.txt" > "$d/.vparts"
  whole=""; whole_dev=""
  while read -r dev hexsize name; do
    case "$dev" in mtd[0-9]*) ;; *) continue ;; esac
    safe=$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '_')
    f="${dev}_${safe}.bin"
    want=$(hex2dec "$hexsize")
    if [ ! -f "$d/$f" ]; then bad "$f missing"; fails=$((fails + 1)); continue; fi
    got=$(fsize "$d/$f")
    if [ "$got" -eq 0 ]; then bad "$f is empty"; fails=$((fails + 1)); continue; fi
    if [ "$got" -ne "$want" ]; then bad "$f is $got bytes, /proc/mtd says $want"; fails=$((fails + 1)); continue; fi
    rec=$(awk -v f="$f" '$2==f{print $1}' "$d/SHA256SUMS")
    now=$(sha256_of "$d/$f")
    if [ -z "$rec" ]; then bad "$f has no entry in SHA256SUMS"; fails=$((fails + 1)); continue; fi
    if [ "$rec" != "$now" ]; then bad "$f sha256 changed since backup ($now != $rec)"; fails=$((fails + 1)); continue; fi
    ok "$f  $got bytes  sha256=$now"
    [ "$hexsize" = "$NX62_WHOLE_CHIP_SIZE" ] && { whole="$d/$f"; whole_dev="$dev"; }
  done < "$d/.vparts"

  # critical partitions present?
  for crit in bl2 u-boot-env factory fip ubi; do
    hit=$(awk -v n="$crit" 'tolower($3)==n{print $1"_"$3".bin"}' "$d/.vparts" | head -n 1)
    if [ -n "$hit" ] && [ -f "$d/$hit" ]; then ok "critical partition '$crit' saved as $hit"
    else bad "critical partition '$crit' NOT found in this backup"; fails=$((fails + 1)); fi
  done

  # factory sanity: not blank, show MACs (offsets from OpenWrt DTS: 0x1fef20, 0x1fef26)
  fac=$(awk 'tolower($3)=="factory"{print $1"_"$3".bin"}' "$d/.vparts" | head -n 1)
  if [ -n "$fac" ] && [ -f "$d/$fac" ]; then
    nonblank=$(od -An -tx1 -N4096 "$d/$fac" | tr -s ' ' '\n' | grep -c -v -e '^$' -e '^ff$' -e '^00$')
    if [ "$nonblank" -gt 0 ]; then ok "factory: Wi-Fi calibration area is not blank ($nonblank non-empty bytes in first 4 KiB)"
    else bad "factory: first 4 KiB is blank (all 0xFF/0x00) - this does not look like a real calibration dump"; fails=$((fails + 1)); fi
    mac1=$(od -An -tx1 -j $((0x1fef20)) -N6 "$d/$fac" | tr -s ' ' ':' | sed 's/^://; s/:$//')
    mac2=$(od -An -tx1 -j $((0x1fef26)) -N6 "$d/$fac" | tr -s ' ' ':' | sed 's/^://; s/:$//')
    say "  [INFO] factory MACs @0x1fef20=$mac1 @0x1fef26=$mac2 (compare with the label on the router)"
  fi

  # whole-chip cross-check: each partition must equal the matching slice of the full dump
  if [ -n "$whole" ]; then
    off=0
    while read -r dev hexsize name; do
      [ "$dev" = "$whole_dev" ] && continue
      case "$dev" in mtd[0-9]*) ;; *) continue ;; esac
      safe=$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '_')
      f="${dev}_${safe}.bin"; sz=$(hex2dec "$hexsize")
      [ -f "$d/$f" ] || { off=$((off + sz)); continue; }
      a=$(dd if="$whole" bs=65536 skip=$((off / 65536)) count=$((sz / 65536)) 2>/dev/null | { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; } | awk '{print $1}')
      b=$(sha256_of "$d/$f")
      if [ "$a" = "$b" ]; then ok "whole-chip slice @0x$(printf '%x' "$off") matches $f"
      else warn "whole-chip slice @0x$(printf '%x' "$off") differs from $f (can happen with NAND bad blocks or a non-contiguous layout - investigate before flashing)"; fi
      off=$((off + sz))
    done < "$d/.vparts"
  else
    warn "no whole-chip (0x$NX62_WHOLE_CHIP_SIZE) dump in this backup - per-partition dumps only"
  fi
  rm -f "$d/.vparts"
  if [ "$fails" -eq 0 ]; then say "  => $d: PASS"; else say "  => $d: FAIL ($fails problems)"; fi
  TOTAL_FAIL=$((TOTAL_FAIL + fails))
}

check_dir "$1"
if [ $# -eq 2 ]; then
  check_dir "$2"
  say ""
  say "=== Comparing the two copies ==="
  if cmp -s "$1/SHA256SUMS" "$2/SHA256SUMS"; then ok "SHA256SUMS identical in both copies"
  else bad "SHA256SUMS differ between copies"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); fi
  m1=$(df -P "$1" | awk 'NR==2{print $6}'); m2=$(df -P "$2" | awk 'NR==2{print $6}')
  if [ "$m1" = "$m2" ]; then warn "both copies are on the same filesystem ($m1). Put the second copy on a USB drive, another machine or cloud storage."
  else ok "copies are on different filesystems ($m1 vs $m2)"; fi
fi

say ""
if [ "$TOTAL_FAIL" -ne 0 ]; then
  say "BACKUP_VERIFY=FAIL ($TOTAL_FAIL problems). DO NOT FLASH."
  exit 1
fi
say "BACKUP_VERIFY=PASS"
if [ $# -eq 2 ]; then
  marker backup-verified.auto
  printf '%s\n%s\n' "$1" "$2" > "$NX62_WORK/backup-paths"
fi

if [ "$USER_CONFIRM" -eq 1 ]; then
  [ $# -eq 2 ] || die "--user-confirm needs both the primary and the second copy"
  say ""
  say "=== Check #3: your turn. Do this yourself, in another window: ==="
  say "  1. Open:  $1"
  say "  2. Open:  $2"
  say "  3. In both, confirm you can see the factory dump, the bl2 dump, the fip dump"
  say "     and the whole-chip dump, with the sizes printed above."
  say "  4. Confirm the second location is somewhere that survives this computer dying"
  say "     (USB stick, another machine, cloud drive)."
  say "  5. Optional: open SHA256SUMS in each and compare a line or two by eye."
  typed_confirm "BACKUPS CHECKED"
  marker backup-verified.user
  say "Recorded: you confirmed the backups at $(cat "$NX62_WORK/backup-verified.user")."
fi
