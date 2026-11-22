#!/usr/bin/env bash
# Create (or reuse) a Debian 12 Azure VM and open the VPN firewall ports.
#
# Opens: SSH (22/tcp) from your current public IP, 443/tcp and 8388/tcp+udp
# from anywhere. The 3x-ui panel port is NOT opened; use an SSH tunnel
# (scripts/ssh-tunnel-panel.sh).
#
# Usage:
#   ./scripts/create-vm-azure.sh
# Env: AZURE_RESOURCE_GROUP, AZURE_LOCATION, AZURE_VM_SIZE, VM_NAME, ADMIN_USER
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib.sh"
maybe_load_local_env
require_cmd az curl ssh

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-vless-3xui-rg}"
LOCATION="${AZURE_LOCATION:-uksouth}"
SIZE="${AZURE_VM_SIZE:-Standard_B2s}"
VM_NAME="${VM_NAME:-vless-3xui}"
ADMIN_USER="${ADMIN_USER:-debian}"
IMAGE="${AZURE_IMAGE:-Debian:debian-12:12-gen2:latest}"
NSG_NAME="${AZURE_NSG_NAME:-${VM_NAME}-nsg}"
SSH_PUB="$(default_ssh_pub)"

OPERATOR_IP="${OPERATOR_IP:-$(detect_public_ip)}"
[[ -n "$OPERATOR_IP" ]] || die "could not detect your public IP; set OPERATOR_IP=x.x.x.x/32"
if [[ "$OPERATOR_IP" != */* ]]; then
  OPERATOR_IP="${OPERATOR_IP}/32"
fi

log "Azure: group=$RESOURCE_GROUP location=$LOCATION size=$SIZE vm=$VM_NAME image=$IMAGE"
log "SSH will be allowed from $OPERATOR_IP"

az account show >/dev/null || die "az is not logged in; run: az login"

if ! az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
  log "Created resource group $RESOURCE_GROUP"
else
  log "Reusing resource group $RESOURCE_GROUP"
fi

if az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" >/dev/null 2>&1; then
  log "VM $VM_NAME already exists; not recreating"
else
  az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --location "$LOCATION" \
    --image "$IMAGE" \
    --size "$SIZE" \
    --admin-username "$ADMIN_USER" \
    --ssh-key-values "$SSH_PUB" \
    --public-ip-sku Standard \
    --nsg "$NSG_NAME" \
    --output none
  log "Created VM $VM_NAME"
fi

# The VM's NIC NSG may already exist with a default SSH rule from 0.0.0.0/0.
# We add our named rules idempotently and tighten SSH to the operator IP.
ensure_rule() {
  local name="$1"
  shift
  if az network nsg rule show --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$name" >/dev/null 2>&1; then
    az network nsg rule update --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$name" "$@" --output none
  else
    az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$name" "$@" --output none
  fi
}

# Discover the NSG actually attached if az vm create named it differently.
DETECTED_NSG="$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --query "networkProfile.networkInterfaces[0].id" -o tsv | xargs -I{} az network nic show --ids {} \
  --query "networkSecurityGroup.id" -o tsv 2>/dev/null || true)"
if [[ -n "${DETECTED_NSG:-}" ]]; then
  NSG_NAME="${DETECTED_NSG##*/}"
fi

ensure_rule allow-ssh-operator \
  --priority 1000 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes "$OPERATOR_IP" --destination-port-ranges 22 \
  --description "SSH from operator IP only"

ensure_rule allow-vless-443 \
  --priority 1100 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes '*' --destination-port-ranges 443 \
  --description "VLESS Reality"

ensure_rule allow-ss-8388-tcp \
  --priority 1110 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes '*' --destination-port-ranges 8388 \
  --description "Shadowsocks TCP (Outline)"

ensure_rule allow-ss-8388-udp \
  --priority 1120 --direction Inbound --access Allow --protocol Udp \
  --source-address-prefixes '*' --destination-port-ranges 8388 \
  --description "Shadowsocks UDP (Outline)"

PUBLIC_IP="$(az vm list-ip-addresses --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --query "[0].virtualMachine.network.publicIpAddresses[0].ipAddress" -o tsv)"
[[ -n "$PUBLIC_IP" ]] || die "could not read the VM public IP"

log "VM public IP: $PUBLIC_IP"
log "Next: wait for SSH, then copy scripts and run install-3xui.sh on the VM."
log "  ssh ${ADMIN_USER}@${PUBLIC_IP}"
printf '%s\n' "$PUBLIC_IP"
