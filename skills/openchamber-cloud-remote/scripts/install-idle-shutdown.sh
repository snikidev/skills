#!/bin/sh
# Install the idle stop script and timer on the VM. Dry run by default.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
references=$script_dir/../references
host=${OC_SSH_HOST:-oc-remote}
wake_config=${OC_WAKE_CONFIG:-$HOME/.ssh/oc-wake.conf}

case "${1:-}" in
  '') apply=0 ;;
  --apply) apply=1 ;;
  *)
    echo "Usage: $0 [--apply]" >&2
    exit 2
    ;;
esac

provider=${OC_CLOUD_PROVIDER:-}
if [ -z "$provider" ] && [ -f "$wake_config" ]; then
  # Written by install-wake-proxy.sh with mode 0600.
  # shellcheck source=/dev/null
  . "$wake_config"
  provider=${OC_CLOUD_PROVIDER:-}
fi
case "$provider" in
  azure | gcp | aws) ;;
  *)
    echo "Set OC_CLOUD_PROVIDER to azure, gcp or aws (or install the wake proxy first)" >&2
    exit 2
    ;;
esac

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. Re-run with --apply to install on the VM.'
  echo "scp $script_dir/oc-idle-shutdown.sh $host:/tmp/oc-idle-shutdown.sh"
  echo "scp $references/oc-idle-shutdown.service $references/oc-idle-shutdown.timer $host:/tmp/"
  echo "write /etc/oc-remote.conf with OC_CLOUD_PROVIDER=$provider"
  echo "ssh $host to enable --now oc-idle-shutdown.timer"
  exit 0
fi

provider_file=$(mktemp "${TMPDIR:-/tmp}/oc-idle-provider.XXXXXX")
trap 'rm -f "$provider_file"' 0 HUP INT TERM
printf 'OC_CLOUD_PROVIDER=%s\n' "$provider" > "$provider_file"

scp "$script_dir/oc-idle-shutdown.sh" "$host:/tmp/oc-idle-shutdown.sh"
scp "$references/oc-idle-shutdown.service" "$references/oc-idle-shutdown.timer" "$host:/tmp/"
scp "$provider_file" "$host:/tmp/oc-remote.conf"
ssh "$host" 'sudo install -m 0755 /tmp/oc-idle-shutdown.sh /usr/local/sbin/oc-idle-shutdown.sh && \
  sudo install -m 0644 /tmp/oc-idle-shutdown.service /etc/systemd/system/oc-idle-shutdown.service && \
  sudo install -m 0644 /tmp/oc-idle-shutdown.timer /etc/systemd/system/oc-idle-shutdown.timer && \
  sudo install -m 0644 /tmp/oc-remote.conf /etc/oc-remote.conf && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable --now oc-idle-shutdown.timer && \
  sudo systemctl status oc-idle-shutdown.timer --no-pager'
