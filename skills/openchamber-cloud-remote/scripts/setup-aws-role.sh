#!/bin/sh
# Create the least-privilege IAM role and instance profile used by the VM idle timer.
# Dry run by default.
set -eu

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

command -v aws >/dev/null 2>&1 || { echo 'aws is required on PATH' >&2; exit 1; }

role_name=OpenChamberVmPowerRole
profile_name=OpenChamberVmPowerProfile
policy_name=OpenChamberVmPowerPolicy
vm_name=${OC_VM_NAME:-oc-remote-01}

case "$vm_name" in
  ''|*[!A-Za-z0-9._-]*)
    echo "Invalid OC_VM_NAME: $vm_name" >&2
    exit 2
    ;;
esac

existing_role=$(aws iam get-role \
  --role-name "$role_name" \
  --query 'Role.RoleName' \
  --output text 2>/dev/null || true)
case "$existing_role" in ''|None) existing_role= ;; esac

existing_profile=$(aws iam get-instance-profile \
  --instance-profile-name "$profile_name" \
  --query 'InstanceProfile.InstanceProfileName' \
  --output text 2>/dev/null || true)
case "$existing_profile" in ''|None) existing_profile= ;; esac

profile_roles=
if [ -n "$existing_profile" ]; then
  profile_roles=$(aws iam get-instance-profile \
    --instance-profile-name "$profile_name" \
    --query 'InstanceProfile.Roles[].RoleName' \
    --output text 2>/dev/null || true)
  case "$profile_roles" in ''|None) profile_roles= ;; esac
fi

attached=0
if printf '%s\n' "$profile_roles" | awk '{for (i=1; i<=NF; i++) print $i}' | grep -Fqx "$role_name"; then
  attached=1
fi

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. No IAM changes made. Re-run with --apply to create or update the role.'
  echo 'IAM is global; OC_AWS_REGION is not needed here.'
  echo 'Plan:'
  if [ -n "$existing_role" ]; then
    printf '  1. Reuse role %s\n' "$role_name"
  else
    printf '  1. Create role %s with the EC2 trust policy\n' "$role_name"
  fi
  printf '  2. Set inline policy %s: StopInstances only when Name=%s; DescribeInstances with Resource "*"\n' "$policy_name" "$vm_name"
  echo '     DescribeInstances does not support resource tags, so it cannot be tag-scoped.'
  if [ -n "$existing_profile" ]; then
    printf '  3. Reuse instance profile %s\n' "$profile_name"
  else
    printf '  3. Create instance profile %s\n' "$profile_name"
  fi
  if [ "$attached" -eq 1 ]; then
    printf '  4. Reuse the existing role attachment to %s\n' "$profile_name"
  else
    printf '  4. Attach %s to %s\n' "$role_name" "$profile_name"
  fi
  printf '\nInstance profile: %s\n' "$profile_name"
  exit 0
fi

trust_file=$(mktemp "${TMPDIR:-/tmp}/oc-aws-trust.XXXXXX.json")
policy_file=$(mktemp "${TMPDIR:-/tmp}/oc-aws-policy.XXXXXX.json")
trap 'rm -f "$trust_file" "$policy_file"' 0 HUP INT TERM

cat > "$trust_file" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

# DescribeInstances is not a resource-level API, so it cannot be limited with aws:ResourceTag.
cat > "$policy_file" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StopTaggedInstance",
      "Effect": "Allow",
      "Action": "ec2:StopInstances",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/Name": "$vm_name"
        }
      }
    },
    {
      "Sid": "DescribeInstances",
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*"
    }
  ]
}
JSON

if [ -n "$existing_role" ]; then
  printf 'Role %s already exists\n' "$role_name"
else
  aws iam create-role \
    --role-name "$role_name" \
    --assume-role-policy-document "file://$trust_file" >/dev/null
  printf 'Created role %s\n' "$role_name"
fi

aws iam put-role-policy \
  --role-name "$role_name" \
  --policy-name "$policy_name" \
  --policy-document "file://$policy_file" >/dev/null
printf 'Set inline policy %s\n' "$policy_name"

if [ -n "$existing_profile" ]; then
  printf 'Instance profile %s already exists\n' "$profile_name"
else
  aws iam create-instance-profile \
    --instance-profile-name "$profile_name" >/dev/null
  printf 'Created instance profile %s\n' "$profile_name"
fi

if [ "$attached" -eq 1 ]; then
  printf 'Role %s is already attached to %s\n' "$role_name" "$profile_name"
else
  aws iam add-role-to-instance-profile \
    --instance-profile-name "$profile_name" \
    --role-name "$role_name" >/dev/null
  printf 'Attached role %s to %s\n' "$role_name" "$profile_name"
fi

printf '%s\n' "$profile_name"
