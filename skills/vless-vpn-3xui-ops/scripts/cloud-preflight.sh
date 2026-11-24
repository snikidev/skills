#!/bin/sh
# cloud-preflight.sh - READ-ONLY check before ANY cloud step (az / gcloud).
#
# Verifies: the CLI is installed, you are logged in, the active subscription /
# project is the one you expect, and (optionally) the resource group / VM exist.
# Prints WHICH identity and subscription/project will be used: names and ids
# only, never tokens. Exits non-zero on anything that should stop a cloud step.
#
#   cloud-preflight.sh azure|gcp [--require-vm]
#
# Env (same names as the setup skill's .env):
#   azure: AZURE_SUBSCRIPTION (expected name or id; strongly recommended),
#          AZURE_RESOURCE_GROUP (default vless-3xui-rg), VM_NAME (default vless-3xui)
#   gcp:   GCP_PROJECT (expected project id; strongly recommended),
#          GCP_ZONE (default europe-west2-a), VM_NAME (default vless-3xui)
#
# Commands run (all read-only):
#   azure: az version; az account show; az group show; az vm show;
#          az role assignment list (best effort, to warn about Owner)
#   gcp:   gcloud --version; gcloud auth list; gcloud config get-value project;
#          gcloud projects describe; gcloud compute instances describe;
#          gcloud projects get-iam-policy (best effort, to warn about owner)
# Output: KEY=value lines, last line PREFLIGHT=OK or PREFLIGHT=FAIL.
set -u

PROVIDER="${1:-${CLOUD_PROVIDER:-}}"
REQUIRE_VM=0
[ "${2:-}" = "--require-vm" ] && REQUIRE_VM=1
VM="${VM_NAME:-vless-3xui}"
FAIL=0

kv() { printf '%s=%s\n' "$1" "$2"; }
fail() { kv "error" "$1"; FAIL=1; }
warn() { kv "warning" "$1"; }

case "$PROVIDER" in
  azure)
    if ! command -v az >/dev/null 2>&1; then
      fail "az not installed (https://learn.microsoft.com/cli/azure/install-azure-cli)"
      kv PREFLIGHT FAIL; exit 1
    fi
    kv cli "az $(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo unknown)"
    acct="$(az account show --query '[name, id, user.name, user.type, tenantId]' -o tsv 2>/dev/null | tr '\n' '\t')"
    if [ -z "$acct" ]; then
      fail "not logged in: run az login (then az account set --subscription <name>)"
      kv PREFLIGHT FAIL; exit 1
    fi
    sub_name="$(printf '%s' "$acct" | cut -f1)"
    sub_id="$(printf '%s' "$acct" | cut -f2)"
    user="$(printf '%s' "$acct" | cut -f3)"
    utype="$(printf '%s' "$acct" | cut -f4)"
    kv identity "$user ($utype)"
    kv subscription "$sub_name ($sub_id)"
    kv tenant "$(printf '%s' "$acct" | cut -f5)"
    if [ -n "${AZURE_SUBSCRIPTION:-}" ]; then
      if [ "$AZURE_SUBSCRIPTION" = "$sub_name" ] || [ "$AZURE_SUBSCRIPTION" = "$sub_id" ]; then
        kv subscription_match yes
      else
        kv subscription_match no
        fail "active subscription is not AZURE_SUBSCRIPTION ($AZURE_SUBSCRIPTION); run: az account set --subscription \"$AZURE_SUBSCRIPTION\""
      fi
    else
      warn "AZURE_SUBSCRIPTION not set: cannot prove this is the right subscription; set it in your env file"
    fi
    RG="${AZURE_RESOURCE_GROUP:-vless-3xui-rg}"
    kv resource_group "$RG"
    if az group show --name "$RG" --query name -o tsv >/dev/null 2>&1; then
      kv resource_group_exists yes
      vm_state="$(az vm show -d --resource-group "$RG" --name "$VM" --query powerState -o tsv 2>/dev/null || true)"
      if [ -n "$vm_state" ]; then kv vm "$VM ($vm_state)"
      elif [ "$REQUIRE_VM" = 1 ]; then fail "VM $VM not found in $RG"
      else kv vm "$VM (not found)"; fi
      roles="$(az role assignment list --assignee "$user" --include-inherited \
        --scope "/subscriptions/$sub_id/resourceGroups/$RG" --query '[].roleDefinitionName' -o tsv 2>/dev/null | sort -u | tr '\n' ',' | sed 's/,$//')"
      kv roles "${roles:-unknown (no permission to list, or none)}"
      case ",$roles," in
        *,Owner,*) warn "identity has Owner: prefer Contributor scoped to resource group $RG only (narrower: Virtual Machine Contributor + Network Contributor + Disk Snapshot Contributor on $RG)" ;;
      esac
    else
      kv resource_group_exists no
      if [ "$REQUIRE_VM" = 1 ]; then fail "resource group $RG not found (or no access)"; fi
    fi
    ;;
  gcp)
    if ! command -v gcloud >/dev/null 2>&1; then
      fail "gcloud not installed (https://cloud.google.com/sdk/docs/install)"
      kv PREFLIGHT FAIL; exit 1
    fi
    kv cli "$(gcloud --version 2>/dev/null | head -n 1)"
    account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n 1)"
    if [ -z "$account" ]; then
      fail "not logged in: run gcloud auth login"
      kv PREFLIGHT FAIL; exit 1
    fi
    kv identity "$account"
    active="$(gcloud config get-value project 2>/dev/null)"
    project="${GCP_PROJECT:-$active}"
    kv active_project "${active:-(unset)}"
    if [ -z "${GCP_PROJECT:-}" ]; then
      warn "GCP_PROJECT not set: using the gcloud default project; set it in your env file"
    elif [ "$GCP_PROJECT" != "$active" ]; then
      warn "gcloud default project ($active) differs from GCP_PROJECT; every command here passes --project $GCP_PROJECT explicitly"
    fi
    if [ -z "$project" ] || [ "$project" = "(unset)" ]; then
      fail "no project: set GCP_PROJECT"
      kv PREFLIGHT FAIL; exit 1
    fi
    pinfo="$(gcloud projects describe "$project" --format='value(projectId,name)' 2>/dev/null | tr '\t' ' ')"
    if [ -z "$pinfo" ]; then
      fail "cannot describe project $project (wrong id, or token expired: gcloud auth login)"
    else
      kv project "$pinfo"
    fi
    ZONE="${GCP_ZONE:-europe-west2-a}"
    kv zone "$ZONE"
    st="$(gcloud compute instances describe "$VM" --project "$project" --zone "$ZONE" --format='value(status)' 2>/dev/null || true)"
    if [ -n "$st" ]; then kv vm "$VM ($st)"
    elif [ "$REQUIRE_VM" = 1 ]; then fail "VM $VM not found in $project/$ZONE"
    else kv vm "$VM (not found)"; fi
    roles="$(gcloud projects get-iam-policy "$project" --flatten='bindings[].members' \
      --filter="bindings.members:$account" --format='value(bindings.role)' 2>/dev/null | sort -u | tr '\n' ',' | sed 's/,$//')"
    kv roles "${roles:-unknown (no permission to read IAM policy, or none)}"
    case ",$roles," in
      *,roles/owner,*) warn "identity has roles/owner: prefer roles/compute.instanceAdmin.v1 + roles/compute.securityAdmin (+ roles/compute.networkAdmin only for IP rotation), or a custom role, on project $project" ;;
    esac
    ;;
  *)
    echo "usage: cloud-preflight.sh azure|gcp [--require-vm]   (or set CLOUD_PROVIDER)" >&2
    exit 2
    ;;
esac

if [ "$FAIL" = 0 ]; then kv PREFLIGHT OK; else kv PREFLIGHT FAIL; fi
exit "$FAIL"
