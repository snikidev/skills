#!/bin/sh
# common.sh - shared helpers for the netis-nx62-openwrt-safe-flash scripts.
# Sourced by the host-side scripts. POSIX sh. Never contains secrets.
# shellcheck disable=SC2034

NX62_WORK="${NX62_WORK:-$HOME/nx62-flash}"
NX62_ROUTER_IP="${NX62_ROUTER_IP:-192.168.1.1}"
NX62_HOST_IP="${NX62_HOST_IP:-192.168.1.254}"
NX62_TFTP_NAME="openwrt-mediatek-filogic-netcore_n60-pro-initramfs-recovery.itb"
NX62_DEVICE_ID="netcore_n60-pro"
NX62_COMPAT="netcore,n60-pro"

# Partition sizes from OpenWrt's mt7986a-netcore-n60-pro.dts (bytes, hex as in /proc/mtd).
# name(lowercase) size
NX62_EXPECTED_PARTS="bl2 00100000
u-boot-env 00080000
factory 00200000
fip 00200000
ubi 07a80000"
NX62_WHOLE_CHIP_SIZE="08000000"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  [PASS] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*"; }
bad()  { printf '  [FAIL] %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

mkwork() { mkdir -p "$NX62_WORK" || die "cannot create work dir $NX62_WORK"; }

is_abs() { case "$1" in /*) return 0 ;; *) return 1 ;; esac; }

# Portable byte size.
fsize() { wc -c < "$1" | tr -d ' '; }

# sha256 / md5 of a file, hex only.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else die "no sha256sum or shasum on this host"; fi
}
md5_of() {
  if command -v md5sum >/dev/null 2>&1; then md5sum "$1" | awk '{print $1}'
  elif command -v md5 >/dev/null 2>&1; then md5 -q "$1"
  else die "no md5sum or md5 on this host"; fi
}
hash_of() { # $1=sha256|md5 $2=file
  case "$1" in sha256) sha256_of "$2" ;; md5) md5_of "$2" ;; *) die "bad algo $1" ;; esac
}

hex2dec() { printf '%d' "0x$1"; }

# SSH with a per-phase known_hosts file. The router's host key legitimately
# changes between stock, recovery and final OpenWrt, so each phase gets its own
# file instead of disabling host-key checking altogether.
# Usage: rssh <phase> <user@host> <command...>
rssh() {
  _phase="$1"; _target="$2"; shift 2
  mkwork
  if [ -n "${NX62_SSH_KEY:-}" ]; then
    ssh -i "$NX62_SSH_KEY" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="$NX62_WORK/known_hosts.$_phase" "$_target" "$@"
  else
    ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="$NX62_WORK/known_hosts.$_phase" "$_target" "$@"
  fi
}
rscp() { # <phase> <local file> <user@host:/path>
  _phase="$1"; shift
  mkwork
  if [ -n "${NX62_SSH_KEY:-}" ]; then
    scp -O -i "$NX62_SSH_KEY" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="$NX62_WORK/known_hosts.$_phase" "$@"
  else
    scp -O -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
      -o UserKnownHostsFile="$NX62_WORK/known_hosts.$_phase" "$@"
  fi
}

# Typed confirmation from the controlling terminal. Refuses when there is no
# terminal, so an agent cannot "type" it on the user's behalf.
typed_confirm() { # $1 = exact phrase
  if ! (exec </dev/tty) 2>/dev/null; then
    die "no interactive terminal: run this command yourself in your own terminal"
  fi
  printf '\nType exactly  %s  to continue (anything else aborts): ' "$1" >/dev/tty
  IFS= read -r _answer </dev/tty || die "aborted"
  [ "$_answer" = "$1" ] || die "confirmation did not match - aborted, nothing was changed"
}

marker() { mkwork; date '+%Y-%m-%d %H:%M:%S %Z' > "$NX62_WORK/$1"; }
has_marker() { [ -s "$NX62_WORK/$1" ]; }
