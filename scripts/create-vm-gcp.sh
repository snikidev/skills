#!/usr/bin/env bash
# Create (or reuse) a Debian 12 GCE VM and open the VPN firewall ports.
#
# Opens: SSH (22/tcp) from your current public IP, 443/tcp and 8388/tcp+udp
# from anywhere, tagged onto this VM only. The 3x-ui panel port is NOT
# opened; use an SSH tunnel (scripts/ssh-tunnel-panel.sh).
#
# Usage:
#   ./scripts/create-vm-gcp.sh
# Env: GCP_PROJECT, GCP_ZONE, GCP_MACHINE_TYPE, VM_NAME, ADMIN_USER
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
maybe_load_local_env
require_cmd gcloud curl ssh

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
[[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]] || die "set GCP_PROJECT or run: gcloud config set project <id>"
ZONE="${GCP_ZONE:-europe-west2-a}"
MACHINE="${GCP_MACHINE_TYPE:-e2-small}"
VM_NAME="${VM_NAME:-vless-3xui}"
ADMIN_USER="${ADMIN_USER:-debian}"
NETWORK="${GCP_NETWORK:-default}"
TAG="${GCP_NETWORK_TAG:-vless-3xui}"
SSH_PUB="$(default_ssh_pub)"
SSH_KEY_LINE="${ADMIN_USER}:$(tr -d '\n' < "$SSH_PUB")"

OPERATOR_IP="${OPERATOR_IP:-$(detect_public_ip)}"
[[ -n "$OPERATOR_IP" ]] || die "could not detect your public IP; set OPERATOR_IP=x.x.x.x/32"
if [[ "$OPERATOR_IP" != */* ]]; then
  OPERATOR_IP="${OPERATOR_IP}/32"
fi

log "GCP: project=$PROJECT zone=$ZONE machine=$MACHINE vm=$VM_NAME tag=$TAG"
log "SSH will be allowed from $OPERATOR_IP"

gcloud projects describe "$PROJECT" >/dev/null || die "gcloud cannot describe project $PROJECT; run: gcloud auth login"

ensure_fw() {
  local name="$1"
  shift
  if gcloud compute firewall-rules describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    # Updates to existing rules are best-effort; creating with a new name is
    # safer than mutating a shared default rule.
    log "Firewall rule $name already exists"
  else
    gcloud compute firewall-rules create "$name" --project "$PROJECT" "$@"
  fi
}

ensure_fw "${TAG}-ssh" \
  --network "$NETWORK" \
  --allow=tcp:22 \
  --source-ranges="$OPERATOR_IP" \
  --target-tags="$TAG" \
  --description="SSH to $TAG VMs from operator IP only"

ensure_fw "${TAG}-vless" \
  --network "$NETWORK" \
  --allow=tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags="$TAG" \
  --description="VLESS Reality"

ensure_fw "${TAG}-ss" \
  --network "$NETWORK" \
  --allow=tcp:8388,udp:8388 \
  --source-ranges=0.0.0.0/0 \
  --target-tags="$TAG" \
  --description="Shadowsocks Outline"

if gcloud compute instances describe "$VM_NAME" --project "$PROJECT" --zone "$ZONE" >/dev/null 2>&1; then
  log "VM $VM_NAME already exists; not recreating"
else
  gcloud compute instances create "$VM_NAME" \
    --project "$PROJECT" \
    --zone "$ZONE" \
    --machine-type "$MACHINE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-balanced \
    --tags="$TAG" \
    --metadata="ssh-keys=${SSH_KEY_LINE}"
  log "Created VM $VM_NAME"
fi

PUBLIC_IP="$(gcloud compute instances describe "$VM_NAME" --project "$PROJECT" --zone "$ZONE" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"
[[ -n "$PUBLIC_IP" ]] || die "could not read the VM public IP"

log "VM public IP: $PUBLIC_IP"
log "Next: wait for SSH, then copy scripts and run install-3xui.sh on the VM."
log "  ssh ${ADMIN_USER}@${PUBLIC_IP}"
printf '%s\n' "$PUBLIC_IP"
