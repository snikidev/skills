#!/bin/sh
# Install the local wake proxy and write its provider config. Dry run by default.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
target_dir=${OC_SSH_BIN:-$HOME/.ssh/bin}
target=$target_dir/oc-wake-proxy.sh
config=${OC_WAKE_CONFIG:-$HOME/.ssh/oc-wake.conf}
host_name=${OC_PUBLIC_IP:-<public-ip>}

case "${1:-}" in
  '') apply=0 ;;
  --apply) apply=1 ;;
  *)
    echo "Usage: $0 [--apply]" >&2
    exit 2
    ;;
esac

provider=${OC_CLOUD_PROVIDER:-}
case "$provider" in
  azure | gcp | aws) ;;
  *)
    echo 'OC_CLOUD_PROVIDER must be one of azure, gcp or aws' >&2
    exit 2
    ;;
esac

case "$provider" in
  azure)
    resource_group=${OC_RESOURCE_GROUP:-rg-openchamber-remote}
    vm_name=${OC_VM_NAME:-oc-remote-01}
    lines="OC_CLOUD_PROVIDER=azure
OC_RESOURCE_GROUP=$resource_group
OC_VM_NAME=$vm_name"
    ;;
  gcp)
    [ -n "${OC_GCP_PROJECT:-}" ] || { echo 'OC_GCP_PROJECT is required' >&2; exit 2; }
    [ -n "${OC_GCP_ZONE:-}" ] || { echo 'OC_GCP_ZONE is required' >&2; exit 2; }
    instance=${OC_GCP_INSTANCE:-${OC_VM_NAME:-oc-remote-01}}
    lines="OC_CLOUD_PROVIDER=gcp
OC_GCP_PROJECT=$OC_GCP_PROJECT
OC_GCP_ZONE=$OC_GCP_ZONE
OC_GCP_INSTANCE=$instance"
    ;;
  aws)
    [ -n "${OC_AWS_INSTANCE_ID:-}" ] || { echo 'OC_AWS_INSTANCE_ID is required' >&2; exit 2; }
    lines="OC_CLOUD_PROVIDER=aws
OC_AWS_REGION=${OC_AWS_REGION:-eu-west-2}
OC_AWS_INSTANCE_ID=$OC_AWS_INSTANCE_ID"
    ;;
esac

# Identifier values are cloud names, not free text; reject shell metacharacters.
if printf '%s\n' "$lines" | grep -Evq '^[A-Za-z0-9_]+=[A-Za-z0-9._-]*$'; then
  echo 'Provider identifiers may only contain letters, digits, dot, underscore and dash' >&2
  exit 2
fi

if [ "$apply" -eq 0 ]; then
  printf 'Dry run. Re-run with --apply to install:\n'
  printf '  %s\n' "$target"
  printf '  %s (provider %s, identifiers from env)\n' "$config" "$provider"
else
  config_dir=$(dirname -- "$config")
  mkdir -p "$target_dir" "$config_dir"
  tmp_config=$(mktemp "${TMPDIR:-/tmp}/oc-wake-conf.XXXXXX")
  trap 'rm -f "$tmp_config"' 0 HUP INT TERM
  printf '%s\n' "$lines" > "$tmp_config"
  chmod 0600 "$tmp_config"
  cp "$script_dir/oc-wake-proxy.sh" "$target"
  chmod 0755 "$target"
  cp "$tmp_config" "$config"
  chmod 0600 "$config"
  printf 'Installed %s and %s\n' "$target" "$config"
fi

cat <<EOF

Add this to ~/.ssh/config (replace <public-ip> with the deployed address):

Host oc-remote
    HostName $host_name
    User azureuser
    IdentityFile ~/.ssh/openchamberazure
    IdentitiesOnly yes
    ProxyCommand $target %h %p

Cold start takes about 45 seconds, so leave ConnectTimeout above 60 seconds.
EOF
