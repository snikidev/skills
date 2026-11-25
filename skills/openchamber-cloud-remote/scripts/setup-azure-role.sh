#!/bin/sh
# Create the Azure self-power role and assign it to the VM identity. Dry run by default.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
template=$script_dir/../references/azure-vm-power-role.json

case "${1:-}" in
  '') apply=0 ;;
  --apply) apply=1 ;;
  *)
    echo "Usage: $0 [--apply]" >&2
    exit 2
    ;;
esac

command -v az >/dev/null 2>&1 || { echo 'az is required on PATH' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo 'python3 is required on PATH' >&2; exit 1; }
[ -f "$template" ] || { echo "Missing role template: $template" >&2; exit 1; }

resource_group=${OC_RESOURCE_GROUP:-rg-openchamber-remote}
vm_name=${OC_VM_NAME:-oc-remote-01}
role_name=${OC_POWER_ROLE_NAME:-OpenChamber VM Power Manager}
subscription=$(az account show --query id -o tsv)
scope="/subscriptions/$subscription/resourceGroups/$resource_group/providers/Microsoft.Compute/virtualMachines/$vm_name"

role_id=$(az role definition list --name "$role_name" --query '[0].name' -o tsv 2>/dev/null || true)
principal_id=$(az vm show -g "$resource_group" -n "$vm_name" --query 'identity.principalId' -o tsv 2>/dev/null || true)
assignment_id=''
if [ -n "$principal_id" ]; then
  assignment_id=$(az role assignment list --assignee "$principal_id" --role "$role_name" --scope "$scope" --query '[0].id' -o tsv 2>/dev/null || true)
fi

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. Re-run with --apply to change Azure roles.'
  if [ -z "$role_id" ]; then echo "create role definition: $role_name"; else echo "reuse role definition: $role_id"; fi
  if [ -z "$principal_id" ]; then echo "enable system-assigned identity on $vm_name"; else echo "reuse VM identity: $principal_id"; fi
  if [ -z "$assignment_id" ]; then echo "assign $role_name at $scope"; else echo "reuse role assignment: $assignment_id"; fi
  exit 0
fi

role_file=$(mktemp "${TMPDIR:-/tmp}/oc-vm-role.XXXXXX.json")
trap 'rm -f "$role_file"' 0 HUP INT TERM

if [ -z "$role_id" ]; then
  python3 - "$template" "$subscription" "$resource_group" "$vm_name" "$role_file" <<'PY'
import json
import sys

source, sub, group, vm, target = sys.argv[1:6]
text = open(source).read()
for key, value in (("${SUBSCRIPTION_ID}", sub), ("${RESOURCE_GROUP}", group), ("${VM_NAME}", vm)):
    text = text.replace(key, value)
json.loads(text)
open(target, "w").write(text)
PY
  role_id=$(az role definition create --role-definition "@$role_file" --query name -o tsv)
fi

if [ -z "$principal_id" ]; then
  principal_id=$(az vm identity assign -g "$resource_group" -n "$vm_name" --query systemAssignedIdentity -o tsv)
fi

if [ -z "$assignment_id" ]; then
  az role assignment create \
    --assignee-object-id "$principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "$role_name" \
    --scope "$scope" >/dev/null
fi

printf 'Role %s assigned to %s at %s\n' "$role_name" "$principal_id" "$scope"
