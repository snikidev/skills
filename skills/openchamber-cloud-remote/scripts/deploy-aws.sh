#!/bin/sh
# Deploy an on-demand AWS VM for OpenChamber Desktop. Read-only unless --apply is passed.
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
command -v python3 >/dev/null 2>&1 || { echo 'python3 is required on PATH' >&2; exit 1; }

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
cloud_init=$script_dir/../references/cloud-init-generic.yaml

vm_size=${OC_VM_SIZE:-}
if [ -z "$vm_size" ]; then
  echo 'OC_VM_SIZE is required. See references/sizing.md for supported sizes.' >&2
  exit 2
fi
case "$vm_size" in
  [a-z][a-z0-9.]*) ;;
  *)
    echo "Unexpected AWS instance type: $vm_size" >&2
    exit 2
    ;;
esac
case "$vm_size" in
  m7i.large | m7i.xlarge | c7i.large) ;;
  *)
    echo "Note: $vm_size is not a listed recommendation; see references/sizing.md" >&2
    ;;
esac

instance_profile=${OC_AWS_INSTANCE_PROFILE:-}
if [ -z "$instance_profile" ]; then
  echo 'OC_AWS_INSTANCE_PROFILE is required; create it with scripts/setup-aws-role.sh first.' >&2
  exit 2
fi

region=${OC_AWS_REGION:-eu-west-2}
vm_name=${OC_VM_NAME:-oc-remote-01}
ssh_key=${OC_SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/openchamberazure.pub}
eip_tag="oc-remote-$vm_name"
sg_name="$vm_name-ssh"

case "$vm_name" in
  ''|*[!A-Za-z0-9._-]*)
    echo "Invalid OC_VM_NAME: $vm_name" >&2
    exit 2
    ;;
esac

[ -f "$ssh_key" ] && [ -r "$ssh_key" ] || { echo "Missing or unreadable SSH public key: $ssh_key" >&2; exit 1; }
[ -f "$cloud_init" ] && [ -r "$cloud_init" ] || { echo "Missing or unreadable cloud-init template: $cloud_init" >&2; exit 1; }

if [ -n "${OC_SSH_SOURCE_CIDR:-}" ]; then
  source_cidr=$OC_SSH_SOURCE_CIDR
else
  command -v curl >/dev/null 2>&1 || { echo 'curl is required when OC_SSH_SOURCE_CIDR is unset' >&2; exit 1; }
  echo 'OC_SSH_SOURCE_CIDR is unset; looking up this machine public IP' >&2
  source_cidr="$(curl -fsS https://api.ipify.org)/32"
fi
if [ -z "$source_cidr" ]; then
  echo 'Could not determine SSH source CIDR' >&2
  exit 1
fi

ami_id=$(aws ec2 describe-images \
  --region "$region" \
  --owners 099720109477 \
  --filters 'Name=name,Values=ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-*' \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text)
case "$ami_id" in ''|None) echo "No Ubuntu 24.04 amd64 HVM AMI found in $region" >&2; exit 1 ;; esac

vpc_id=$(aws ec2 describe-vpcs \
  --region "$region" \
  --filters 'Name=isDefault,Values=true' \
  --query 'Vpcs[0].VpcId' \
  --output text)
case "$vpc_id" in ''|None) echo "No default VPC found in $region" >&2; exit 1 ;; esac

subnet_id=$(aws ec2 describe-subnets \
  --region "$region" \
  --filters "Name=vpc-id,Values=$vpc_id" \
  --query 'Subnets[0].SubnetId' \
  --output text)
case "$subnet_id" in ''|None) echo "No subnet found in default VPC $vpc_id ($region)" >&2; exit 1 ;; esac

eip_allocation=$(aws ec2 describe-addresses \
  --region "$region" \
  --filters "Name=tag:Name,Values=$eip_tag" \
  --query 'Addresses[0].AllocationId' \
  --output text 2>/dev/null || true)
case "$eip_allocation" in ''|None) eip_allocation= ;; esac

sg_id=$(aws ec2 describe-security-groups \
  --region "$region" \
  --filters "Name=group-name,Values=$sg_name" \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || true)
case "$sg_id" in ''|None) sg_id= ;; esac

allowed_cidrs=
if [ -n "$sg_id" ]; then
  allowed_cidrs=$(aws ec2 describe-security-groups \
    --region "$region" \
    --group-ids "$sg_id" \
    --query "SecurityGroups[0].IpPermissions[?IpProtocol==\`tcp\` && FromPort==\`22\` && ToPort==\`22\`].IpRanges[].CidrIp" \
    --output text)
fi

ingress_present=0
if [ -n "$sg_id" ] && printf '%s\n' "$allowed_cidrs" | awk '{for (i=1; i<=NF; i++) print $i}' | grep -Fqx "$source_cidr"; then
  ingress_present=1
fi

existing_instance=$(aws ec2 describe-instances \
  --region "$region" \
  --filters "Name=tag:Name,Values=$vm_name" 'Name=instance-state-name,Values=pending,running,stopping,stopped' \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text 2>/dev/null || true)
case "$existing_instance" in ''|None) existing_instance= ;; esac

if [ "$apply" -eq 0 ]; then
  echo 'Dry run. No AWS changes made. Re-run with --apply to create the VM resources.'
  echo 'Plan:'
  printf '  1. AMI: %s (latest Ubuntu 24.04 amd64 HVM in %s)\n' "$ami_id" "$region"
  printf '  2. Network: default VPC %s, subnet %s\n' "$vpc_id" "$subnet_id"
  if [ -n "$eip_allocation" ]; then
    printf '  3. Reuse Elastic IP tagged Name=%s\n' "$eip_tag"
  else
    printf '  3. Allocate an Elastic IP and tag it Name=%s\n' "$eip_tag"
  fi
  if [ -n "$sg_id" ]; then
    printf '  4. Reuse security group %s (%s)\n' "$sg_name" "$sg_id"
  else
    printf '  4. Create security group %s in %s\n' "$sg_name" "$vpc_id"
  fi
  if [ "$ingress_present" -eq 1 ]; then
    printf '     Reuse existing tcp/22 ingress from %s\n' "$source_cidr"
  else
    printf '     Authorize tcp/22 ingress from %s\n' "$source_cidr"
  fi
  if [ -n "$existing_instance" ]; then
    printf '  5. Reuse existing instance %s tagged Name=%s\n' "$existing_instance" "$vm_name"
  else
    printf '  5. Run one %s instance tagged Name=%s with instance profile %s\n' "$vm_size" "$vm_name" "$instance_profile"
    echo '     user-data: rendered cloud-init with the public key substituted (AWS CLI base64-encodes it)'
    echo '     no SSH key pair is passed; cloud-init installs the public key'
  fi
  echo '  6. Wait for running state, associate the Elastic IP, then print the public IP, verification command and SSH alias'
  exit 0
fi

user_data_file=$(mktemp "${TMPDIR:-/tmp}/oc-aws-user-data.XXXXXX")
trap 'rm -f "$user_data_file"' 0 HUP INT TERM

python3 - "$cloud_init" "$ssh_key" > "$user_data_file" <<'PY'
import sys

template_path, key_path = sys.argv[1:3]
with open(template_path, "r", encoding="utf-8") as handle:
    template = handle.read()
with open(key_path, "r", encoding="utf-8") as handle:
    public_key = handle.read().strip()

placeholder = "${SSH_PUBLIC_KEY}"
if placeholder not in template:
    raise SystemExit("cloud-init template is missing ${SSH_PUBLIC_KEY}")

sys.stdout.write(template.replace(placeholder, public_key))
PY

if [ -z "$eip_allocation" ]; then
  eip_allocation=$(aws ec2 allocate-address \
    --region "$region" \
    --domain vpc \
    --query AllocationId \
    --output text)
  aws ec2 create-tags \
    --region "$region" \
    --resources "$eip_allocation" \
    --tags "Key=Name,Value=$eip_tag" >/dev/null
  echo "Allocated Elastic IP tagged Name=$eip_tag"
else
  echo "Reusing Elastic IP tagged Name=$eip_tag"
fi

if [ -z "$sg_id" ]; then
  sg_id=$(aws ec2 create-security-group \
    --region "$region" \
    --group-name "$sg_name" \
    --description "SSH access for $vm_name" \
    --vpc-id "$vpc_id" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$sg_name}]" \
    --query GroupId \
    --output text)
  echo "Created security group $sg_name"
fi

if [ "$ingress_present" -eq 0 ]; then
  aws ec2 authorize-security-group-ingress \
    --region "$region" \
    --group-id "$sg_id" \
    --protocol tcp \
    --port 22 \
    --cidr "$source_cidr" >/dev/null
  echo "Authorized tcp/22 from $source_cidr"
fi

if [ -n "$existing_instance" ]; then
  instance_id=$existing_instance
  echo "Reusing existing instance $instance_id"
else
  # AWS CLI base64-encodes --user-data file:// automatically; pass plain YAML.
  instance_id=$(aws ec2 run-instances \
    --region "$region" \
    --image-id "$ami_id" \
    --instance-type "$vm_size" \
    --iam-instance-profile "Name=$instance_profile" \
    --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
    --user-data "file://$user_data_file" \
    --count 1 \
    --security-group-ids "$sg_id" \
    --subnet-id "$subnet_id" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$vm_name}]" \
    --query 'Instances[0].InstanceId' \
    --output text)
  aws ec2 wait instance-running \
    --region "$region" \
    --instance-ids "$instance_id"
fi

aws ec2 associate-address \
  --region "$region" \
  --allocation-id "$eip_allocation" \
  --instance-id "$instance_id" \
  --allow-reassociation >/dev/null

public_ip=$(aws ec2 describe-addresses \
  --region "$region" \
  --allocation-ids "$eip_allocation" \
  --query 'Addresses[0].PublicIp' \
  --output text)

printf '\nPublic IP: %s\n' "$public_ip"
printf "Verify: aws ec2 describe-instances --region %s --instance-ids %s --query 'Reservations[0].Instances[0].State.Name' --output text\n" "$region" "$instance_id"
printf '\nAdd this to ~/.ssh/config:\n'
cat <<EOF
Host oc-remote
  HostName $public_ip
  User azureuser
  IdentityFile ~/.ssh/openchamberazure
  IdentitiesOnly yes
  ProxyCommand ~/.ssh/bin/oc-wake-proxy.sh %h %p
EOF
