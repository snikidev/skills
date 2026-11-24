#!/bin/sh
# backup-mtd.sh - READ-ONLY full MTD backup of a Netis NX62 / Netcore N60 Pro.
#
# Streams every /dev/mtdN listed in the router's /proc/mtd over SSH to the host
# (router RAM is never used for the dump), then for EACH partition checks:
#   * dump size == size reported by /proc/mtd
#   * dump is not empty
#   * hash computed ON THE ROUTER == hash computed on the host
#     (sha256 if the router has sha256sum, otherwise md5)
# and records SHA256SUMS + MD5SUMS for later re-verification.
#
# It only ever runs `cat /proc/mtd`, `cat /dev/mtdN` and `*sum /dev/mtdN` on the
# router. It never writes to flash.
#
# Usage:
#   backup-mtd.sh --router useradmin@192.168.1.1 --out /ABSOLUTE/path/new-dir
# Optional: NX62_SSH_KEY=/path/to/key to avoid one password prompt per command.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

ROUTER=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --router) ROUTER="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$ROUTER" ] || die "--router user@ip is required"
[ -n "$OUT" ] || die "--out /absolute/dir is required"
is_abs "$OUT" || die "--out must be an ABSOLUTE path (got: $OUT)"
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  die "$OUT already exists and is not empty - refusing to mix backups. Pick a new directory."
fi
mkdir -p "$OUT" || die "cannot create $OUT"
PHASE=stock

say "Backup directory (absolute): $OUT"
rssh "$PHASE" "$ROUTER" 'cat /proc/mtd' > "$OUT/proc_mtd.txt" </dev/null || die "ssh failed reading /proc/mtd"
rssh "$PHASE" "$ROUTER" 'sh -s' < "$HERE/router-inspect.sh" > "$OUT/inspect.txt" 2>&1 || warn "router-inspect returned non-zero"
grep -q '^INSPECT_RESULT=OK' "$OUT/inspect.txt" || warn "partition map does not match the expected NX62 layout - see $OUT/inspect.txt. Backup continues (it is read-only) but DO NOT FLASH."

if rssh "$PHASE" "$ROUTER" 'command -v sha256sum' </dev/null >/dev/null 2>&1; then RALGO=sha256; else RALGO=md5; fi
say "Router-side hash: $RALGO"

: > "$OUT/SHA256SUMS"; : > "$OUT/MD5SUMS"
FAIL=0; COUNT=0
# Read the list into a temp file so ssh never steals the loop's stdin.
awk 'NR>1{gsub(/:/,"",$1); gsub(/"/,"",$4); print $1" "$2" "$4}' "$OUT/proc_mtd.txt" > "$OUT/.parts"
while read -r dev hexsize name; do
  case "$dev" in mtd[0-9]*) ;; *) continue ;; esac
  COUNT=$((COUNT + 1))
  safe=$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '_')
  f="${dev}_${safe}.bin"
  want=$(hex2dec "$hexsize")
  say "-> /dev/$dev ($name), expected $want bytes"
  rhash=$(rssh "$PHASE" "$ROUTER" "${RALGO}sum /dev/$dev" </dev/null 2>/dev/null | awk '{print $1}')
  rssh "$PHASE" "$ROUTER" "cat /dev/$dev" </dev/null > "$OUT/$f" 2>"$OUT/.err_$dev"
  got=$(fsize "$OUT/$f")
  lhash=$(hash_of "$RALGO" "$OUT/$f")
  if [ "$got" -eq 0 ]; then bad "$f is EMPTY"; FAIL=$((FAIL + 1)); continue; fi
  if [ "$got" -ne "$want" ]; then bad "$f size $got != /proc/mtd $want"; FAIL=$((FAIL + 1)); continue; fi
  if [ -z "$rhash" ] || [ "$rhash" != "$lhash" ]; then
    bad "$f hash mismatch router=$rhash host=$lhash"; FAIL=$((FAIL + 1)); continue
  fi
  printf '%s  %s\n' "$(sha256_of "$OUT/$f")" "$f" >> "$OUT/SHA256SUMS"
  printf '%s  %s\n' "$(md5_of "$OUT/$f")" "$f" >> "$OUT/MD5SUMS"
  rm -f "$OUT/.err_$dev"
  ok "$f size=$got $RALGO=$lhash (router and host agree)"
done < "$OUT/.parts"
rm -f "$OUT/.parts"

{
  echo "created: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "router: $ROUTER"
  echo "router_hash: $RALGO"
  echo "partitions: $COUNT"
  echo "failed: $FAIL"
} > "$OUT/MANIFEST.txt"

say ""
if [ "$COUNT" -eq 0 ]; then die "no partitions found in /proc/mtd"; fi
if [ "$FAIL" -eq 0 ]; then
  say "BACKUP_RESULT=PASS  ($COUNT partitions) in $OUT"
  say "Next: verify-backup.sh $OUT  (then copy it to a second location)."
else
  say "BACKUP_RESULT=FAIL  ($FAIL of $COUNT partitions failed). DO NOT FLASH. Re-run into a NEW directory."
  exit 1
fi
