# VM size catalog

The size is a decision, not a default. Ask the user with these options plus a
free-text "other" field, then pass the answer as `OC_VM_SIZE`. Every deploy
script fails when that variable is empty. A custom size is allowed if it
matches the provider's naming pattern; the script prints a warning when it is
not in this catalog so the choice stays visible.

All images and cloud-init scripts target **amd64 (`x86_64`)** Ubuntu 24.04 —
do not pick ARM64 families (`Standard_D*ps_*`, `t2a-*`, `*g.*`).

## Azure

| Size | vCPU / RAM | Note |
|---|---|---|
| `Standard_D2s_v6` | 2 / 8 GB | Verified in UK South; enough for Node, bun and `opencode` |
| `Standard_D4s_v6` | 4 / 16 GB | Heavier parallel agent work |
| `Standard_D8s_v6` | 8 / 32 GB | Multiple concurrent remote sessions |

`Standard_D2s_v5` had zero quota in UK South when this was set up, which is why
v6 is the recommended family. Check the target region before promising a size:

```sh
az vm list-sizes --location "$LOCATION" --query "[?starts_with(name,'Standard_D2s')].name" -o tsv
az vm list-usage --location "$LOCATION" \
  --query "[?contains(name.value,'standardDSv6Family') || name.value=='cores'].{name:name.value,current:currentValue,limit:limit}" -o table
```

Billing note: only `deallocate` stops compute charges. `stopped` still bills.

## GCP

| Size | vCPU / RAM | Note |
|---|---|---|
| `e2-standard-2` | 2 / 8 GB | Recommended starting point, lowest cost |
| `n2-standard-4` | 4 / 16 GB | More consistent CPU for longer agent runs |
| `c3-highcpu-4` | 4 / 8 GB | CPU-heavy work with less memory |

Check availability and quota in the chosen zone:

```sh
gcloud compute machine-types list --filter="zone:$ZONE AND (name=e2-standard-2 OR name=n2-standard-4)"
gcloud compute project-info describe --format='value(quotas)' --project "$PROJECT"
```

A reserved static external IP may be charged while the instance is stopped;
confirm the current pricing for the project before choosing it.

## AWS

| Size | vCPU / RAM | Note |
|---|---|---|
| `m7i.large` | 2 / 8 GB | Recommended starting point, matches the Azure shape |
| `m7i.xlarge` | 4 / 16 GB | Heavier work |
| `c7i.large` | 2 / 4 GB | CPU-heavy, memory constrained |

Check the instance type is offered in the chosen region:

```sh
aws ec2 describe-instance-type-offerings \
  --region "$REGION" \
  --location-type availability-zone \
  --filters "Name=instance-type,Values=m7i.large,m7i.xlarge,c7i.large" \
  --query 'InstanceTypeOfferings[].InstanceType' --output text
```

An Elastic IP associated with a stopped instance can incur a charge; confirm
the account's pricing before accepting it.

## After the user chooses

Write the answer down in the session, pass it to every script, and mention it
in the plan shown before `--apply`. If the chosen size is unavailable or over
quota, report the exact error and ask the user for a different size; do not
silently substitute one.
