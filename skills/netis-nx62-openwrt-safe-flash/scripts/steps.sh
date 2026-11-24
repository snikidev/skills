#!/bin/sh
# steps.sh - progress tracker for the NX62 safe-flash procedure.
# Prints done / current / remaining steps. Steps can only be completed in order.
#
# Usage:
#   steps.sh list            show every step with its status (default)
#   steps.sh current         show only the current step
#   steps.sh done <N>        mark step N done (must be the current step)
#   steps.sh reset --yes     forget progress (does not touch backups or the router)
#
# State lives in $NX62_WORK/steps.state (default ~/nx62-flash).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=common.sh
. "$HERE/common.sh"

STATE="$NX62_WORK/steps.state"

STEPS="Orientation: risks, rules and consent
Identify the exact device and pick the OpenWrt release
Download images and verify sha256 against official sha256sums
Host network: static 192.168.1.254/24, no gateway
SSH into stock firmware and inspect the partition map (read-only)
Full MTD backup to the host (all partitions)
Backup check #1: automatic verification of the primary copy
Backup check #2: second copy off the host, verify both copies
Backup check #3: YOU inspect the backups yourself and confirm
Recovery plan, power check and TFTP server self-test
Pre-flash preflight (everything green)
Write OpenWrt FIP (bootloader) - reversible until reboot
Erase ubi and reboot - POINT OF NO RETURN
Confirm the router loaded recovery over TFTP
Sysupgrade the permanent OpenWrt image from recovery
Verify the install, set root password, restore host network"

total=$(printf '%s\n' "$STEPS" | wc -l | tr -d ' ')

last_done() {
  if [ -s "$STATE" ]; then tail -n 1 "$STATE" | awk '{print $1}'; else echo -1; fi
}

title_of() { printf '%s\n' "$STEPS" | sed -n "$(( $1 + 1 ))p"; }

show_list() {
  ld=$(last_done); cur=$((ld + 1))
  say "NX62 safe flash - progress ($((ld + 1))/$total steps done)"
  i=0
  printf '%s\n' "$STEPS" | while IFS= read -r t; do
    if [ "$i" -le "$ld" ]; then mark="[x]"
    elif [ "$i" -eq "$cur" ]; then mark="[>]"
    else mark="[ ]"; fi
    printf '  %s %2d. %s\n' "$mark" "$i" "$t"
    i=$((i + 1))
  done
  if [ "$cur" -lt "$total" ]; then
    say ""
    say "CURRENT: step $cur - $(title_of "$cur")"
    say "REMAINING after this one: $((total - cur - 1))"
  else
    say ""
    say "ALL STEPS DONE."
  fi
}

cmd="${1:-list}"
case "$cmd" in
  list) show_list ;;
  current)
    cur=$(( $(last_done) + 1 ))
    if [ "$cur" -lt "$total" ]; then say "step $cur - $(title_of "$cur")"; else say "all steps done"; fi ;;
  done)
    n="${2:?usage: steps.sh done <N>}"
    case "$n" in *[!0-9]*|'') die "step must be a number" ;; esac
    cur=$(( $(last_done) + 1 ))
    [ "$n" -eq "$cur" ] || die "step $n is not the current step ($cur). Steps cannot be skipped or repeated."
    mkwork
    printf '%s %s %s\n' "$n" "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$(title_of "$n")" >> "$STATE"
    show_list ;;
  reset)
    [ "${2:-}" = "--yes" ] || die "add --yes to reset progress"
    rm -f "$STATE"; say "progress reset"; show_list ;;
  *) die "unknown command: $cmd" ;;
esac
