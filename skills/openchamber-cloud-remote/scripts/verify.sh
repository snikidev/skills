#!/bin/sh
# Read-only health check for the on-demand OpenChamber remote.
set -eu

wake_config=${OC_WAKE_CONFIG:-$HOME/.ssh/oc-wake.conf}
host=${OC_SSH_HOST:-oc-remote}

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

case "$provider" in
  azure)
    command -v az >/dev/null 2>&1 || { echo 'az is required on PATH' >&2; exit 1; }
    resource_group=${OC_RESOURCE_GROUP:-rg-openchamber-remote}
    vm_name=${OC_VM_NAME:-oc-remote-01}
    state=$(az vm get-instance-view -g "$resource_group" -n "$vm_name" \
      --query "instanceView.statuses[?starts_with(code,'PowerState')].displayStatus" -o tsv)
    running='VM running'
    ;;
  gcp)
    command -v gcloud >/dev/null 2>&1 || { echo 'gcloud is required on PATH' >&2; exit 1; }
    [ -n "${OC_GCP_PROJECT:-}" ] && [ -n "${OC_GCP_ZONE:-}" ] && [ -n "${OC_GCP_INSTANCE:-}" ] || {
      echo 'GCP verify needs OC_GCP_PROJECT, OC_GCP_ZONE and OC_GCP_INSTANCE' >&2
      exit 2
    }
    state=$(gcloud compute instances describe "$OC_GCP_INSTANCE" --project "$OC_GCP_PROJECT" \
      --zone "$OC_GCP_ZONE" --format='value(status)')
    running='RUNNING'
    ;;
  aws)
    command -v aws >/dev/null 2>&1 || { echo 'aws is required on PATH' >&2; exit 1; }
    [ -n "${OC_AWS_INSTANCE_ID:-}" ] || { echo 'AWS verify needs OC_AWS_INSTANCE_ID' >&2; exit 2; }
    state=$(aws ec2 describe-instances --region "${OC_AWS_REGION:-eu-west-2}" \
      --instance-ids "$OC_AWS_INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].State.Name' --output text)
    running='running'
    ;;
esac

printf '%s VM state: %s\n' "$provider" "$state"

if [ "$state" != "$running" ]; then
  printf 'Wake it with: ssh %s\n' "$host"
  exit 0
fi

ssh "$host" 'echo "--- tools ---"; \
  node --version 2>/dev/null || true; \
  ~/.bun/bin/bun --version 2>/dev/null || true; \
  ~/.opencode/bin/opencode --version 2>/dev/null || true; \
  echo "--- idle timer ---"; \
  systemctl is-active oc-idle-shutdown.timer 2>/dev/null || true; \
  echo "--- idle log ---"; \
  sudo tail -n 5 /var/log/oc-idle-shutdown.log 2>/dev/null || true'
