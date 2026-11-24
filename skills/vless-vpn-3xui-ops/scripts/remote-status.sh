#!/bin/sh
# remote-status.sh - READ-ONLY health snapshot, runs ON THE VPS.
#   ssh vps 'sh -s' < remote-status.sh
# Prints key=value lines. Never prints secrets: it does not read
# /etc/x-ui/install-result.env, the database, or Xray's config.json.
# Uses `sudo -n` (non-interactive) only for `x-ui setting -getListen`; if sudo
# would prompt, it reports panel_listen=needs-sudo instead.
XUI=/usr/local/x-ui/x-ui

say() { printf '%s=%s\n' "$1" "$2"; }

if command -v systemctl >/dev/null 2>&1; then
  say xui_service "$(systemctl is-active x-ui 2>/dev/null | head -n 1)"
  say xui_enabled "$(systemctl is-enabled x-ui 2>/dev/null | head -n 1)"
else
  say xui_service no-systemd
fi
if [ -x "$XUI" ]; then say xui_version "$("$XUI" -v 2>/dev/null | head -n 1)"; else say xui_version missing; fi
if pgrep -f 'xray-linux' >/dev/null 2>&1; then say xray_process running; else say xray_process not-running; fi
xbin=""
for f in /usr/local/x-ui/bin/xray-linux-*; do [ -x "$f" ] && { xbin=$f; break; }; done
[ -n "$xbin" ] && say xray_version "$("$xbin" version 2>/dev/null | head -n 1)"

if [ "$(id -u)" = "0" ]; then
  say panel_listen "$("$XUI" setting -getListen true 2>/dev/null | sed -n 's/^listenIP: *//p')"
elif sudo -n true 2>/dev/null; then
  say panel_listen "$(sudo -n "$XUI" setting -getListen true 2>/dev/null | sed -n 's/^listenIP: *//p')"
else
  say panel_listen needs-sudo
fi

if command -v ss >/dev/null 2>&1; then
  # listening TCP sockets owned by x-ui / xray (address:port only)
  ss -ltnH 2>/dev/null | awk '{print $4}' | sort -u | tr '\n' ' ' | sed 's/ $//' | {
    read -r socks; say listening "${socks:-none}"; }
fi
say uptime "$(uptime 2>/dev/null | sed 's/^ *//')"
say disk_root "$(df -P / 2>/dev/null | awk 'NR==2{print $5" used of "$2" KiB"}')"
say ntp_synced "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown)"
