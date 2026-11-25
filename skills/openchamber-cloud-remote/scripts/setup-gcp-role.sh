#!/bin/sh
# Create the least-privilege VM power role, service account and conditional binding. Dry run by default.
set -eu

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

region=${OC_GCP_REGION:-europe-west2}
zone=${OC_GCP_ZONE:-${region}-a}
vm_name=${OC_VM_NAME:-oc-remote-01}

role_id=OpenChamberVmPowerManager
role_name=projects/${project}/roles/${role_id}
sa_name=oc-remote-power
sa_email=${sa_name}@${project}.iam.gserviceaccount.com
condition_title=oc-remote-power-${vm_name}
condition_expr="resource.type == \"compute.googleapis.com/Instance\" && resource.name == \"projects/${project}/zones/${zone}/instances/${vm_name}\""

role_exists=0
if gcloud iam roles describe "$role_id" --project "$project" >/dev/null 2>&1; then
  role_exists=1
fi
sa_exists=0
if gcloud iam service-accounts describe "$sa_email" --project "$project" >/dev/null 2>&1; then
  sa_exists=1
fi

policy_json=$(gcloud projects get-iam-policy "$project" --format=json)
binding_state=$(printf '%s\n' "$policy_json" | python3 -c '
import json, sys

role, email, expression = sys.argv[1:4]
policy = json.load(sys.stdin)
member = "serviceAccount:" + email
matches = [
    b for b in policy.get("bindings", [])
    if b.get("role") == role and member in b.get("members", [])
]
if not matches:
    print("none")
elif len(matches) == 1 and matches[0].get("condition", {}).get("expression") == expression:
    print("exact")
else:
    print("update")
' "$role_name" "$sa_email" "$condition_expr")

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. No IAM changes made. Re-run with --apply to apply this plan:'
  if [ "$role_exists" -eq 1 ]; then
    echo "  1. Reuse custom role $role_id"
  else
    echo "  1. Create custom role $role_id with exactly compute.instances.stop and compute.instances.get"
  fi
  if [ "$sa_exists" -eq 1 ]; then
    echo '  2. Reuse the existing service account oc-remote-power'
  else
    echo '  2. Create service account oc-remote-power'
  fi
  case "$binding_state" in
    exact) echo '  3. Reuse the existing single conditional binding for the service account' ;;
    none) echo "  3. Add a conditional binding: $condition_expr" ;;
    *) echo "  3. Replace any earlier binding for this role and service account with one conditional binding: $condition_expr" ;;
  esac
  printf 'Service account: %s\n' "$sa_email"
  exit 0
fi

if [ "$role_exists" -eq 0 ]; then
  gcloud iam roles create "$role_id" \
    --project "$project" \
    --title='OpenChamber VM Power Manager' \
    --description='Read and stop the single OpenChamber remote instance' \
    --permissions=compute.instances.stop,compute.instances.get \
    --stage=GA >/dev/null
fi

if [ "$sa_exists" -eq 0 ]; then
  gcloud iam service-accounts create "$sa_name" \
    --project "$project" \
    --display-name='OpenChamber VM power manager' >/dev/null
fi

if [ "$binding_state" != exact ]; then
  policy_dir=$(mktemp -d "${TMPDIR:-/tmp}/oc-gcp-iam.XXXXXX")
  trap 'rm -rf "$policy_dir"' 0 HUP INT TERM
  policy_file=$policy_dir/policy.json

  # Keep all unrelated bindings; canonicalise this role/member to exactly one
  # conditional binding so repeated runs converge instead of duplicating it.
  printf '%s\n' "$policy_json" | python3 -c '
import json, sys

role, email, title, expression = sys.argv[1:5]
policy = json.load(sys.stdin)
member = "serviceAccount:" + email
policy["bindings"] = [
    b for b in policy.get("bindings", [])
    if not (b.get("role") == role and member in b.get("members", []))
]
policy["version"] = max(policy.get("version", 1), 3)
policy["bindings"].append({
    "role": role,
    "members": [member],
    "condition": {"title": title, "expression": expression},
})
json.dump(policy, sys.stdout, indent=2)
sys.stdout.write("\n")
' "$role_name" "$sa_email" "$condition_title" "$condition_expr" > "$policy_file"

  gcloud projects set-iam-policy "$project" "$policy_file" >/dev/null
fi

printf 'Service account: %s\n' "$sa_email"
