#!/bin/sh
# Provider dispatcher. Provider and VM size must both be explicit.
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

if [ -z "${OC_VM_SIZE:-}" ]; then
  echo 'OC_VM_SIZE must be set explicitly; see references/sizing.md' >&2
  exit 2
fi

exec "$script_dir/deploy-$provider.sh" "$@"
