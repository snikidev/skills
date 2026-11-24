#!/bin/sh
# flash-step.sh - the ONLY script in this skill that can change the router.
#
# DRY-RUN BY DEFAULT: without --execute it only checks preconditions and prints
# exactly what it would do. With --execute it re-checks everything, then asks
# YOU to type a confirmation phrase in your own terminal (no terminal = refuse,
# so an agent cannot confirm for you).
#
# Usage:
#   flash-step.sh fip        --router useradmin@192.168.1.1 --image /ABS/...-bl31-uboot.fip [--execute]
#   flash-step.sh erase-ubi  --router useradmin@192.168.1.1 [--execute]
#   flash-step.sh sysupgrade --router root@192.168.1.1      --image /ABS/...-squashfs-sysupgrade.itb [--execute]
#
# Hard refusals (no flag overrides them): writing bl2/preloader, factory,
# u-boot-env/orig-env or the whole-chip partition; ubiformat by number.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

ACTION="${1:-}"; [ -n "$ACTION" ] && shift
ROUTER=""; IMG=""; EXEC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --router) ROUTER="$2"; shift 2 ;;
    --image) IMG="$2"; shift 2 ;;
    --execute) EXEC=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$ACTION" in
  bl2|preloader|factory|u-boot-env|uboot-env|orig-env|spi0.1|whole|ubiformat)
    die "REFUSED: '$ACTION' is never written by this skill. The stock BL2 boots the OpenWrt FIP (this is the upstream OpenWrt method), factory holds your unique Wi-Fi calibration and MACs, and nothing here formats UBI by number. See references/recovery-uboot-tftp.md." ;;
  fip|erase-ubi|sysupgrade) ;;
  *) die "usage: flash-step.sh fip|erase-ubi|sysupgrade --router user@ip [--image /abs/file] [--execute]" ;;
esac
[ -n "$ROUTER" ] || die "--router is required"

need_markers() {
  for m in "$@"; do has_marker "$m" || die "precondition missing: $m. Complete the earlier step first (see steps.sh list)."; done
}

image_ok() { # verify image against the official sha256sums recorded in step 2
  if [ -z "$IMG" ] || ! is_abs "$IMG" || [ ! -f "$IMG" ]; then die "--image must be an absolute path to an existing file"; fi
  [ -s "$NX62_WORK/images-info" ] || die "images-info missing - run verify-images.sh first"
  idir=$(sed -n 1p "$NX62_WORK/images-info")
  base=$(basename "$IMG")
  official=$(awk -v f="$base" '{n=$2; sub(/^\*/,"",n); if (n==f) print $1}' "$idir/sha256sums")
  [ -n "$official" ] || die "$base is not in $idir/sha256sums"
  [ "$(sha256_of "$IMG")" = "$official" ] || die "$base sha256 no longer matches the official value - STOP"
  ok "$base sha256 matches official sha256sums"
}

part_dev() { # $1 phase, $2 name (case-insensitive) -> prints "mtdN hexsize realname"
  rssh "$1" "$ROUTER" 'cat /proc/mtd' </dev/null | awk -v n="$2" 'NR>1{nm=$4; gsub(/"/,"",nm); d=$1; gsub(/:/,"",d); if (tolower(nm)==n) print d" "$2" "nm}' | head -n 1
}

router_hash() { # $1 phase $2 remote-file-or-cmd-output; prints algo:hash
  if rssh "$1" "$ROUTER" 'command -v sha256sum' </dev/null >/dev/null 2>&1; then
    printf 'sha256:%s' "$(rssh "$1" "$ROUTER" "$2 | sha256sum" </dev/null | awk '{print $1}')"
  else
    printf 'md5:%s' "$(rssh "$1" "$ROUTER" "$2 | md5sum" </dev/null | awk '{print $1}')"
  fi
}

upload_and_check() { # $1 phase ; uploads $IMG to /tmp and compares hashes
  base=$(basename "$IMG")
  rscp "$1" "$IMG" "$ROUTER:/tmp/$base" </dev/null || die "upload failed"
  rh=$(router_hash "$1" "cat /tmp/$base")
  algo=${rh%%:*}; rv=${rh#*:}
  lv=$(hash_of "$algo" "$IMG")
  if [ -z "$rv" ] || [ "$rv" != "$lv" ]; then die "uploaded copy differs from local image ($algo router=$rv local=$lv) - STOP"; fi
  ok "router /tmp/$base matches local file ($algo $lv)"
}

case "$ACTION" in
fip)
  say "=== Step: write OpenWrt FIP (BL31 + U-Boot) on STOCK firmware ==="
  need_markers images-verified backup-verified.auto backup-verified.user tftp-selftest.ok
  image_ok
  case "$(basename "$IMG")" in *-netcore_n60-pro-bl31-uboot.fip) ;; *) die "this is not the netcore_n60-pro bl31-uboot.fip" ;; esac
  p=$(part_dev stock fip); [ -n "$p" ] || die "no partition named FIP on the router"
  dev=${p%% *}; rest=${p#* }; hex=${rest%% *}; pname=${rest#* }
  [ "$hex" = "00200000" ] || die "FIP partition is 0x$hex, expected 0x00200000 - layout differs, STOP"
  isz=$(fsize "$IMG"); [ "$isz" -lt 2097152 ] || die "image larger than the FIP partition"
  ok "target: /dev/$dev name=$pname size=0x$hex, image $isz bytes"
  say "Would run on router:  mtd write /tmp/$(basename "$IMG") $pname"
  say "Then read back the first $isz bytes of /dev/$dev and compare hashes."
  say "Why it is reversible: until the next reboot the running stock system is untouched;"
  say "you can rewrite the stock FIP from your backup (mtd write <backup>_FIP.bin $pname)."
  [ "$EXEC" -eq 1 ] || { say "DRY RUN - nothing written. Re-run with --execute in your own terminal."; exit 0; }
  upload_and_check stock
  typed_confirm "WRITE FIP"
  rssh stock "$ROUTER" "mtd write /tmp/$(basename "$IMG") $pname" </dev/null || die "mtd write returned an error - DO NOT REBOOT. Re-check, and if needed restore FIP from backup."
  rh=$(router_hash stock "dd if=/dev/$dev bs=$isz count=1 2>/dev/null")
  algo=${rh%%:*}; rv=${rh#*:}; lv=$(hash_of "$algo" "$IMG")
  if [ "$rv" = "$lv" ]; then ok "readback matches ($algo $lv)"; marker fip-written.ok; say "FIP_WRITE=PASS"
  else bad "readback MISMATCH ($rv vs $lv). DO NOT REBOOT. Restore FIP from backup or retry the write."; exit 1; fi
  ;;
erase-ubi)
  say "=== Step: erase ubi + reboot (POINT OF NO RETURN) ==="
  need_markers fip-written.ok tftp-selftest.ok backup-verified.user
  p=$(part_dev stock ubi); [ -n "$p" ] || die "no partition named ubi"
  hex=$(echo "$p" | awk '{print $2}'); [ "$hex" = "07a80000" ] || die "ubi is 0x$hex, expected 0x07a80000 - STOP"
  ok "target: $(echo "$p" | awk '{print "/dev/"$1" name="$3}') size=0x$hex"
  say "Would run on router:  mtd erase ubi ; reboot"
  say "After this the stock firmware is gone. The OpenWrt U-Boot you just wrote finds"
  say "no system and requests $NX62_TFTP_NAME from $NX62_HOST_IP over TFTP."
  say "Have the TFTP server running and the packet capture open BEFORE you confirm."
  [ "$EXEC" -eq 1 ] || { say "DRY RUN - nothing erased. Re-run with --execute in your own terminal."; exit 0; }
  typed_confirm "ERASE UBI"
  rssh stock "$ROUTER" 'mtd erase ubi' </dev/null || die "mtd erase reported an error - do NOT power off; read references/troubleshooting.md"
  ok "ubi erased"
  typed_confirm "REBOOT"
  rssh stock "$ROUTER" 'reboot' </dev/null || true
  marker ubi-erased.ok
  say "Rebooting. Now watch the capture for the TFTP request (step 13)."
  ;;
sysupgrade)
  say "=== Step: sysupgrade from the RAM recovery system ==="
  need_markers ubi-erased.ok images-verified
  image_ok
  case "$(basename "$IMG")" in *-netcore_n60-pro-squashfs-sysupgrade.itb) ;; *) die "this is not the netcore_n60-pro squashfs-sysupgrade.itb" ;; esac
  compat=$(rssh recovery "$ROUTER" "tr '\\000' ' ' < /proc/device-tree/compatible" </dev/null)
  case "$compat" in *"$NX62_COMPAT"*) ok "router reports $NX62_COMPAT" ;; *) die "router compatible is '$compat', not $NX62_COMPAT - STOP" ;; esac
  rootfs=$(rssh recovery "$ROUTER" "awk '\$2==\"/\"{print \$3}' /proc/mounts | tail -n 1" </dev/null)
  case "$rootfs" in rootfs|tmpfs|ramfs) ok "running from RAM ($rootfs) - this is the recovery system" ;; *) die "root filesystem is '$rootfs', expected the RAM recovery - STOP" ;; esac
  say "Would run on router:  sysupgrade -T /tmp/<image>  (OpenWrt's own image test), then  sysupgrade -n /tmp/<image>"
  [ "$EXEC" -eq 1 ] || { say "DRY RUN - nothing written. Re-run with --execute in your own terminal."; exit 0; }
  upload_and_check recovery
  rssh recovery "$ROUTER" "sysupgrade -T /tmp/$(basename "$IMG")" </dev/null || die "sysupgrade -T rejected the image - STOP"
  ok "sysupgrade -T accepted the image"
  typed_confirm "SYSUPGRADE"
  say "The SSH session will drop and the router reboots (~2-3 min). That is expected."
  rssh recovery "$ROUTER" "sysupgrade -n /tmp/$(basename "$IMG")" </dev/null || true
  marker sysupgrade-started.ok
  ;;
esac
