#!/bin/sh
# router-inspect.sh - READ-ONLY inspection, runs ON THE ROUTER (busybox ash).
# Run it from the host without copying it anywhere:
#   ssh useradmin@192.168.1.1 'sh -s' < router-inspect.sh
# It never writes to flash. It only reads /proc, /sys and /etc.
# Last line is INSPECT_RESULT=OK or INSPECT_RESULT=MISMATCH.

echo "=== identity ==="
if [ -r /proc/device-tree/model ]; then
  printf 'model: '; tr '\000' ' ' < /proc/device-tree/model; echo
fi
if [ -r /proc/device-tree/compatible ]; then
  printf 'compatible: '; tr '\000' ' ' < /proc/device-tree/compatible; echo
fi
uname -a 2>/dev/null
[ -r /etc/openwrt_release ] && grep -E 'DISTRIB_(ID|RELEASE|DESCRIPTION|TARGET)' /etc/openwrt_release
printf 'rootfs: '; awk '$2=="/"{print $1" "$3}' /proc/mounts | tail -n 1

echo "=== memory / tmp ==="
grep -E 'MemTotal|MemFree|MemAvailable' /proc/meminfo
df /tmp 2>/dev/null | tail -n 1

echo "=== tools ==="
for t in sha256sum md5sum dd mtd sysupgrade head; do
  if command -v "$t" >/dev/null 2>&1; then echo "have: $t"; else echo "missing: $t"; fi
done

echo "=== /proc/mtd ==="
cat /proc/mtd

echo "=== partition size check (expected values from OpenWrt DTS) ==="
result=OK
for pair in bl2:00100000 u-boot-env:00080000 factory:00200000 fip:00200000 ubi:07a80000; do
  want_name=${pair%%:*}; want_size=${pair#*:}
  # case-insensitive match on the quoted name
  line=$(awk -v n="$want_name" 'NR>1{nm=$4; gsub(/"/,"",nm); if (tolower(nm)==n) print $1" "$2" "nm}' /proc/mtd | head -n 1)
  if [ -z "$line" ]; then
    echo "MISSING  $want_name (expected size 0x$want_size)"; result=MISMATCH; continue
  fi
  dev=${line%% *}; rest=${line#* }; size=${rest%% *}; name=${rest#* }
  if [ "$size" = "$want_size" ]; then
    echo "MATCH    ${dev%:} $name size=0x$size"
  else
    echo "MISMATCH ${dev%:} $name size=0x$size expected=0x$want_size"; result=MISMATCH
  fi
done
whole=$(awk 'NR>1 && $2=="08000000"{print $1" "$4}' /proc/mtd | head -n 1)
[ -n "$whole" ] && echo "INFO     whole-chip partition present: $whole"
echo "INSPECT_RESULT=$result"
