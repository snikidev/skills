#!/bin/sh
# Provider dispatcher for the VM's self-power identity.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

provider=${1:-}
case "$provider" in
  azure | gcp | aws) shift ;;
  *)
    echo "Usage: $0 <azure|gcp|aws> [--apply]" >&2
    exit 2
    ;;
esac

exec "$script_dir/setup-$provider-role.sh" "$@"
