#!/bin/sh
# SSH ProxyCommand: wake the configured cloud VM, wait for SSH, then forward.
set -eu

host=${1:?host required}
port=${2:?port required}

config=${OC_WAKE_CONFIG:-$HOME/.ssh/oc-wake.conf}
log_file=${OC_WAKE_LOG:-$HOME/.ssh/oc-wake.log}
if [ -f "$config" ]; then
  # Written by install-wake-proxy.sh with mode 0600.
  # shellcheck source=/dev/null
  . "$config"
fi

provider=${OC_CLOUD_PROVIDER:-}
case "$provider" in
  azure | gcp | aws) ;;
  *)
    echo "Set OC_CLOUD_PROVIDER in $config (azure, gcp or aws)" >&2
    exit 1
    ;;
esac

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "The wake proxy needs $1 on PATH" >&2; exit 1; }
}

need_cmd nc
nc_bin=$(command -v nc)

mkdir -p "$(dirname -- "$log_file")"
log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$log_file"
}

case "$provider" in
  azure)
    need_cmd az
    az_bin=$(command -v az)
    resource_group=${OC_RESOURCE_GROUP:-rg-openchamber-remote}
    vm_name=${OC_VM_NAME:-oc-remote-01}
    state=$("$az_bin" vm get-instance-view -g "$resource_group" -n "$vm_name" \
      --query "instanceView.statuses[?starts_with(code,'PowerState')].displayStatus" -o tsv 2>/dev/null || true)
    log "SSH requested; Azure power state: ${state:-unknown}"
    if [ "$state" != 'VM running' ]; then
      log 'starting Azure VM'
      "$az_bin" vm start -g "$resource_group" -n "$vm_name" --no-wait >/dev/null 2>&1 || true
    fi
    ;;
  gcp)
    need_cmd gcloud
    gcloud_bin=$(command -v gcloud)
    project=${OC_GCP_PROJECT:-}
    zone=${OC_GCP_ZONE:-}
    instance=${OC_GCP_INSTANCE:-}
    if [ -z "$project" ] || [ -z "$zone" ] || [ -z "$instance" ]; then
      echo "GCP wake needs OC_GCP_PROJECT, OC_GCP_ZONE and OC_GCP_INSTANCE in $config" >&2
      exit 1
    fi
    state=$("$gcloud_bin" compute instances describe "$instance" --project "$project" --zone "$zone" \
      --format='value(status)' 2>/dev/null || true)
    log "SSH requested; GCP status: ${state:-unknown}"
    if [ "$state" != 'RUNNING' ]; then
      log 'starting GCP VM'
      "$gcloud_bin" compute instances start "$instance" --project "$project" --zone "$zone" --async >/dev/null 2>&1 || true
    fi
    ;;
  aws)
    need_cmd aws
    aws_bin=$(command -v aws)
    region=${OC_AWS_REGION:-eu-west-2}
    instance_id=${OC_AWS_INSTANCE_ID:-}
    if [ -z "$instance_id" ]; then
      echo "AWS wake needs OC_AWS_INSTANCE_ID in $config" >&2
      exit 1
    fi
    state=$("$aws_bin" ec2 describe-instances --region "$region" --instance-ids "$instance_id" \
      --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)
    log "SSH requested; AWS state: ${state:-unknown}"
    if [ "$state" != 'running' ]; then
      log 'starting AWS VM'
      "$aws_bin" ec2 start-instances --region "$region" --instance-ids "$instance_id" >/dev/null 2>&1 || true
    fi
    ;;
esac

attempt=0
while [ "$attempt" -lt 120 ]; do
  if "$nc_bin" -z -w 2 "$host" "$port" 2>/dev/null; then
    log 'VM reachable; forwarding SSH'
    exec "$nc_bin" "$host" "$port"
  fi
  attempt=$((attempt + 1))
  sleep 2
done

log 'VM did not become reachable in time'
echo 'OpenChamber VM did not become reachable after a cold start' >&2
exit 1
