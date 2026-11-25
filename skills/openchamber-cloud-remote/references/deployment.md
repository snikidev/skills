# Deployment reference

Manual equivalent of the scripts. Commands are grouped so you can stop and
inspect between writes; every cloud command below that creates or changes a
resource is a write.

## 0. Decide explicitly first

Ask for and record these before any command:

- Provider: `azure`, `gcp` or `aws`.
- Size: one of the options in [sizing.md](sizing.md), or an explicit custom
  value. Never fall back to a default.
- Region, VM name and the client SSH source CIDR (`A.B.C.D/32`).

The scripts export `OC_CLOUD_PROVIDER`, `OC_VM_SIZE`, `OC_SSH_SOURCE_CIDR` and
the provider identifiers; the examples below use shell variables for the same
values. `SKILL_DIR=skills/openchamber-cloud-remote`.

## 1. Azure (live-tested)

```sh
az login
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
RESOURCE_GROUP=rg-openchamber-remote
VM_NAME=oc-remote-01
LOCATION=uksouth
VM_SIZE=Standard_D2s_v6
SSH_PUBLIC_KEY_FILE=~/.ssh/openchamberazure.pub
SSH_SOURCE_CIDR=$(curl -fsS https://api.ipify.org)/32
```

Replace `SSH_SOURCE_CIDR` with a fixed `/32` if your IP is stable; the NSG will
only accept SSH from that address. `main.bicep` has no `vmSize` default — the
size comes from the decision above.

```sh
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
CUSTOM_DATA=$(python3 -c 'import base64,sys; print(base64.b64encode(open(sys.argv[1],"rb").read()).decode())' "$SKILL_DIR/references/cloud-init.yaml")
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$SKILL_DIR/references/main.bicep" \
  --parameters \
    vmName="$VM_NAME" vmSize="$VM_SIZE" \
    sshPublicKey="$(cat "$SSH_PUBLIC_KEY_FILE")" \
    sshSourcePrefix="$SSH_SOURCE_CIDR" customData="$CUSTOM_DATA"
```

The output `publicIp` is the address for the SSH alias. Then give the VM's
system-assigned identity only read/start/deallocate on this VM:

```sh
ROLE_NAME='OpenChamber VM Power Manager'
SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$VM_NAME"
python3 - "$SCOPE" "$SKILL_DIR/references/azure-vm-power-role.json" /tmp/oc-role.json <<'PY'
import json, sys
scope, source, target = sys.argv[1:4]
sub, rg, vm = scope.split('/')[2], scope.split('/')[4], scope.split('/')[8]
text = (open(source).read()
        .replace('${SUBSCRIPTION_ID}', sub)
        .replace('${RESOURCE_GROUP}', rg)
        .replace('${VM_NAME}', vm))
json.loads(text)
open(target, 'w').write(text)
PY
az role definition create --role-definition @/tmp/oc-role.json
PRINCIPAL_ID=$(az vm identity assign -g "$RESOURCE_GROUP" -n "$VM_NAME" --query systemAssignedIdentity -o tsv)
az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal --role "$ROLE_NAME" --scope "$SCOPE"
rm -f /tmp/oc-role.json
```

`scripts/setup-azure-role.sh --apply` does this idempotently.

## 2. GCP

Create the least-privilege identity first, because the VM must be created with
it. `setup-gcp-role.sh --apply` creates a custom role with
`compute.instances.stop` and `compute.instances.get`, a service account and a
project IAM binding conditioned to this one instance.

```sh
gcloud auth login
PROJECT=<chosen project>
REGION=europe-west2
ZONE=${REGION}-a
VM_NAME=oc-remote-01
VM_SIZE=e2-standard-2
SERVICE_ACCOUNT=oc-remote-power@${PROJECT}.iam.gserviceaccount.com
SSH_SOURCE_CIDR=$(curl -fsS https://api.ipify.org)/32
```

Reserve a static address and open only port 22 from the client CIDR:

```sh
gcloud compute addresses create "${VM_NAME}-ip" --project "$PROJECT" --region "$REGION"
gcloud compute firewall-rules create "${VM_NAME}-allow-ssh" --project "$PROJECT" \
  --network default --direction INGRESS --action ALLOW \
  --rules tcp:22 --source-ranges "$SSH_SOURCE_CIDR" --target-tags openchamber-remote
```

Substitute the public key into the generic cloud-init and create the VM:

```sh
python3 - "$SKILL_DIR/references/cloud-init-generic.yaml" \
  "$HOME/.ssh/openchamberazure.pub" /tmp/oc-user-data.yaml <<'PY'
import sys
template, key_file, target = sys.argv[1:4]
open(target, 'w').write(open(template).read().replace('${SSH_PUBLIC_KEY}', open(key_file).read().strip()))
PY
gcloud compute instances create "$VM_NAME" --project "$PROJECT" --zone "$ZONE" \
  --machine-type "$VM_SIZE" --image-family ubuntu-2404-lts-amd64 \
  --image-project ubuntu-os-cloud \
  --service-account "$SERVICE_ACCOUNT" \
  --scopes https://www.googleapis.com/auth/compute \
  --address "${VM_NAME}-ip" --tags openchamber-remote \
  --metadata-from-file user-data=/tmp/oc-user-data.yaml
rm -f /tmp/oc-user-data.yaml
```

The `compute` scope is enough for the instance to call its own stop API. A
reserved address keeps the SSH alias stable while the instance is stopped;
check the project's pricing for unused reservations.

## 3. AWS

`setup-aws-role.sh --apply` creates an EC2 trust role with an inline policy
allowing `ec2:StopInstances` on instances tagged `Name=$VM_NAME` (plus
`ec2:DescribeInstances`, which does not support resource tags), an instance
profile and the role/profile attachment. Create it before the VM.

```sh
REGION=eu-west-2
VM_NAME=oc-remote-01
VM_SIZE=m7i.large
INSTANCE_PROFILE=OpenChamberVmPowerProfile
SSH_SOURCE_CIDR=$(curl -fsS https://api.ipify.org)/32

VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNET_ID=$(aws ec2 describe-subnets --region "$REGION" \
  --filters Name=vpc-id,Values="$VPC_ID" --query 'Subnets[0].SubnetId' --output text)
AMI_ID=$(aws ec2 describe-images --region "$REGION" --owners 099720109477 \
  --filters 'Name=name,Values=ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-*' \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)

SG_ID=$(aws ec2 create-security-group --region "$REGION" \
  --group-name "${VM_NAME}-ssh" --description 'OpenChamber remote SSH' \
  --vpc-id "$VPC_ID" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$SSH_SOURCE_CIDR"

ALLOC_JSON=$(aws ec2 allocate-address --region "$REGION" --domain vpc)
ALLOC_ID=$(printf '%s\n' "$ALLOC_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["AllocationId"])')
PUBLIC_IP=$(printf '%s\n' "$ALLOC_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["PublicIp"])')
```

Use the same substitution as GCP and pass the plain YAML file to `--user-data`
(`aws ec2 run-instances` base64-encodes `file://` automatically):

```sh
python3 - "$SKILL_DIR/references/cloud-init-generic.yaml" "$HOME/.ssh/openchamberazure.pub" /tmp/oc-user-data.yaml <<'PY'
import sys
template, key_file, target = sys.argv[1:4]
open(target, 'w').write(open(template).read().replace('${SSH_PUBLIC_KEY}', open(key_file).read().strip()))
PY
INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI_ID" \
  --instance-type "$VM_SIZE" --subnet-id "$SUBNET_ID" --security-group-ids "$SG_ID" \
  --iam-instance-profile "Name=$INSTANCE_PROFILE" \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
  --user-data file:///tmp/oc-user-data.yaml \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$VM_NAME}]" \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
aws ec2 associate-address --region "$REGION" --instance-id "$INSTANCE_ID" \
  --allocation-id "$ALLOC_ID"
rm -f /tmp/oc-user-data.yaml
```

`PUBLIC_IP` comes from the single allocation associated above, so the SSH alias
stays stable across stops. An Elastic IP associated with a stopped instance may
still be charged; confirm pricing in the account.

## 4. Wake proxy, idle timer and OpenChamber Desktop

The local config `~/.ssh/oc-wake.conf` is written by
`scripts/install-wake-proxy.sh --apply`. It names the provider and just the
resource identifiers, for example `OC_CLOUD_PROVIDER=aws` and
`OC_AWS_INSTANCE_ID=...`. Keep it mode 0600.

```sshconfig
Host oc-remote
    HostName <public-ip>
    User azureuser
    IdentityFile ~/.ssh/openchamberazure
    IdentitiesOnly yes
    ProxyCommand ~/.ssh/bin/oc-wake-proxy.sh %h %p
```

The proxy checks the chosen cloud's state, starts the VM if needed, polls port
22 with `nc`, then hands the connection to SSH. A cold wake takes about 45
seconds; keep `ConnectTimeout` above 60 seconds.

Install the shared idle script, systemd units and `/etc/oc-remote.conf` with
`scripts/install-idle-shutdown.sh --apply`. The timer fires five minutes after
boot and then every minute. The script skips the first five minutes of uptime,
resets its timer while `who` shows SSH users or `ss` shows established port-22
connections, then calls the provider's stop API. Status goes to
`/var/log/oc-idle-shutdown.log`. `OC_IDLE_SECONDS` on the VM overrides 1800.

To test without waiting, backdate the marker once uptime is over five minutes:

```sh
ssh oc-remote 'sudo date +%s -d "40 minutes ago" | sudo tee /var/tmp/oc-idle-since'
```

Disconnect SSH before the check so no session holds the timer open.

In OpenChamber Desktop: **Settings → Remote Instances → Add** with SSH command
`ssh oc-remote`, managed install enabled and no SSH password.

## 5. Ongoing changes

- Client IP changed: update the Azure NSG rule `AllowSSH`, the GCP firewall
  rule or the AWS security-group ingress — not the SSH alias.
- Reinstall an updated wake proxy or idle script with the install scripts.
- Read-only check: `scripts/verify.sh`.
- Teardown is destructive: delete the resource group, the GCP project resources
  (instance, address, firewall, service account and custom role) or the AWS
  instance, EIP, security group and IAM role. Confirm with the user first.
