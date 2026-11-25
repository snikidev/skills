#!/bin/sh
# Deploy the OpenChamber remote VM on GCP. Read-only unless --apply is passed.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
cloud_init=$script_dir/../references/cloud-init-generic.yaml
tag=openchamber-remote

case "${1:-}" in
  '') apply=0 ;;
  --apply) apply=1 ;;
  *)
    echo "Usage: $0 [--apply]" >&2
    exit 2
    ;;
esac

command -v gcloud >/dev/null 2>&1 || { echo 'gcloud is required on PATH' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo 'python3 is required on PATH' >&2; exit 1; }

project=${OC_GCP_PROJECT:-}
[ -n "$project" ] || { echo 'OC_GCP_PROJECT is required' >&2; exit 1; }

service_account=${OC_GCP_SERVICE_ACCOUNT:-}
[ -n "$service_account" ] || {
  echo 'OC_GCP_SERVICE_ACCOUNT is required; run scripts/setup-gcp-role.sh first' >&2
  exit 1
}
case "$service_account" in
  *@*.iam.gserviceaccount.com) ;;
  *)
    echo 'OC_GCP_SERVICE_ACCOUNT must be a service account email' >&2
    exit 2
    ;;
esac

vm_size=${OC_VM_SIZE:-}
[ -n "$vm_size" ] || { echo 'OC_VM_SIZE is required; see references/sizing.md' >&2; exit 1; }
case "$vm_size" in
  [a-z][a-z0-9-]*) ;;
  *)
    echo "Unexpected GCP machine type: $vm_size" >&2
    exit 2
    ;;
esac
case "$vm_size" in
  e2-standard-2 | n2-standard-4 | c3-highcpu-4) ;;
  *)
    echo "Note: $vm_size is not a listed recommendation; see references/sizing.md" >&2
    ;;
esac

region=${OC_GCP_REGION:-europe-west2}
zone=${OC_GCP_ZONE:-${region}-a}
vm_name=${OC_VM_NAME:-oc-remote-01}
ssh_key=${OC_SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/openchamberazure.pub}
address_name=${vm_name}-ip
firewall_name=${vm_name}-allow-ssh

[ -f "$ssh_key" ] || { echo "Missing SSH public key: $ssh_key" >&2; exit 1; }
[ -f "$cloud_init" ] || { echo "Missing cloud-init template: $cloud_init" >&2; exit 1; }
# The placeholder in the template is literal, so single quotes are intentional.
# shellcheck disable=SC2016
grep -Fq '${SSH_PUBLIC_KEY}' "$cloud_init" || {
  echo "Missing \${SSH_PUBLIC_KEY} placeholder in $cloud_init" >&2
  exit 1
}

if [ -n "${OC_SSH_SOURCE_CIDR:-}" ]; then
  source_cidr=$OC_SSH_SOURCE_CIDR
else
  echo 'OC_SSH_SOURCE_CIDR is unset; looking up this machine public IP' >&2
  command -v curl >/dev/null 2>&1 || { echo 'curl is required to detect the client IP' >&2; exit 1; }
  source_cidr="$(curl -fsS https://api.ipify.org)/32"
fi

# Describe calls are read-only, so they also run in dry-run mode.
address_exists=0
if gcloud compute addresses describe "$address_name" --region "$region" --project "$project" >/dev/null 2>&1; then
  address_exists=1
fi
firewall_exists=0
if gcloud compute firewall-rules describe "$firewall_name" --project "$project" >/dev/null 2>&1; then
  firewall_exists=1
fi
vm_exists=0
if gcloud compute instances describe "$vm_name" --zone "$zone" --project "$project" >/dev/null 2>&1; then
  vm_exists=1
fi

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. No GCP resources changed. Re-run with --apply to apply this plan:'
  if [ "$address_exists" -eq 1 ]; then
    echo "  1. Reuse reserved address $address_name in $region"
  else
    echo "  1. Reserve static address $address_name in $region"
  fi
  if [ "$firewall_exists" -eq 1 ]; then
    echo "  2. Reuse firewall rule $firewall_name"
  else
    echo "  2. Create firewall rule $firewall_name: tcp:22 from <client CIDR>, target tag $tag"
  fi
  if [ "$vm_exists" -eq 1 ]; then
    echo "  3. Reuse existing VM $vm_name in $zone"
  else
    echo "  3. Create VM $vm_name in $zone: $vm_size, service account from OC_GCP_SERVICE_ACCOUNT, cloud-init from $cloud_init with the public key substituted"
  fi
  echo '  4. Print the public IP, a verification command and the SSH alias block'
  echo 'Note: if the network has a broader default SSH rule, remove it separately to limit exposure.'
  exit 0
fi

if [ "$address_exists" -eq 0 ]; then
  gcloud compute addresses create "$address_name" --region "$region" --project "$project" >/dev/null
fi
public_ip=$(gcloud compute addresses describe "$address_name" --region "$region" --project "$project" --format='value(address)')

if [ "$firewall_exists" -eq 0 ]; then
  gcloud compute firewall-rules create "$firewall_name" \
    --project "$project" \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:22 \
    --source-ranges="$source_cidr" \
    --target-tags="$tag" >/dev/null
fi

if [ "$vm_exists" -eq 0 ]; then
  user_data_file=$(mktemp "${TMPDIR:-/tmp}/oc-gcp-user-data.XXXXXX")
  trap 'rm -f "$user_data_file"' 0 HUP INT TERM

  python3 - "$cloud_init" "$ssh_key" "$user_data_file" <<'PY'
import sys

template_path, key_path, output_path = sys.argv[1:4]
with open(template_path, encoding="utf-8") as handle:
    template = handle.read()
with open(key_path, encoding="utf-8") as handle:
    public_key = handle.read().strip()
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(template.replace("${SSH_PUBLIC_KEY}", public_key))
PY

  # Only compute scope is needed: the VM's idle timer calls instances.get and
  # instances.stop through the service account. cloud-platform would be broader.
  gcloud compute instances create "$vm_name" \
    --project "$project" \
    --zone "$zone" \
    --machine-type="$vm_size" \
    --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud \
    --service-account="$service_account" \
    --scopes=https://www.googleapis.com/auth/compute \
    --tags="$tag" \
    --address="$public_ip" \
    --metadata-from-file=user-data="$user_data_file" >/dev/null
fi

instance_ip=$(gcloud compute instances describe "$vm_name" --zone "$zone" --project "$project" \
  --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || true)
if [ -n "$instance_ip" ]; then
  public_ip=$instance_ip
fi

printf 'Public IP: %s\n' "$public_ip"
printf 'Verify: gcloud compute instances describe %s --project %s --zone %s\n' "$vm_name" "$project" "$zone"
printf '\nAdd this block to ~/.ssh/config:\n'
printf 'Host oc-remote\n'
printf '    HostName %s\n' "$public_ip"
printf '    User azureuser\n'
printf '    IdentityFile ~/.ssh/openchamberazure\n'
printf '    IdentitiesOnly yes\n'
printf '    ProxyCommand ~/.ssh/bin/oc-wake-proxy.sh %%h %%p\n'
