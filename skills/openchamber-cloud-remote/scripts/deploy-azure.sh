#!/bin/sh
# Deploy the Azure VM. Read-only unless --apply is passed.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
references=$script_dir/../references

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [--apply]" >&2
  exit 2
fi
case "${1:-}" in
  '') apply=0 ;;
  --apply) apply=1 ;;
  *)
    echo "Usage: $0 [--apply]" >&2
    exit 2
    ;;
esac

if [ -z "${OC_VM_SIZE:-}" ]; then
  echo 'OC_VM_SIZE must be set explicitly; see references/sizing.md' >&2
  exit 2
fi
case "$OC_VM_SIZE" in
  Standard_*) ;;
  *)
    echo "Unexpected Azure size: $OC_VM_SIZE" >&2
    exit 2
    ;;
esac
case "$OC_VM_SIZE" in
  Standard_D2s_v6 | Standard_D4s_v6 | Standard_D8s_v6) ;;
  *)
    echo "Note: $OC_VM_SIZE is not a listed recommendation; see references/sizing.md" >&2
    ;;
esac

command -v az >/dev/null 2>&1 || { echo 'az is required on PATH' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo 'python3 is required on PATH' >&2; exit 1; }

resource_group=${OC_RESOURCE_GROUP:-rg-openchamber-remote}
location=${OC_LOCATION:-uksouth}
vm_name=${OC_VM_NAME:-oc-remote-01}
vm_size=$OC_VM_SIZE
ssh_key=${OC_SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/openchamberazure.pub}
bicep=$references/main.bicep
cloud_init=$references/cloud-init.yaml

[ -f "$ssh_key" ] || { echo "Missing SSH public key: $ssh_key" >&2; exit 1; }
[ -f "$bicep" ] || { echo "Missing template: $bicep" >&2; exit 1; }
[ -f "$cloud_init" ] || { echo "Missing cloud-init: $cloud_init" >&2; exit 1; }

if [ -n "${OC_SSH_SOURCE_CIDR:-}" ]; then
  source_cidr=$OC_SSH_SOURCE_CIDR
else
  echo 'OC_SSH_SOURCE_CIDR is unset; looking up this machine public IP' >&2
  source_cidr="$(curl -fsS https://api.ipify.org)/32"
fi

custom_data=$(python3 -c 'import base64,sys; print(base64.b64encode(open(sys.argv[1],"rb").read()).decode())' "$cloud_init")
ssh_public_key=$(cat "$ssh_key")

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. Re-run with --apply to create the resources.'
  echo "az group create --name $resource_group --location $location"
  echo "az deployment group create --resource-group $resource_group --template-file $bicep"
  echo "  --parameters vmName=$vm_name vmSize=$vm_size sshPublicKey=<contents of $ssh_key> sshSourcePrefix=$source_cidr customData=<base64 cloud-init>"
  exit 0
fi

az group create --name "$resource_group" --location "$location" >/dev/null
az deployment group create \
  --resource-group "$resource_group" \
  --template-file "$bicep" \
  --parameters \
    vmName="$vm_name" \
    vmSize="$vm_size" \
    sshPublicKey="$ssh_public_key" \
    sshSourcePrefix="$source_cidr" \
    customData="$custom_data"
