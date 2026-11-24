# Cloud dependencies (Azure / Google Cloud)

The ops skill mostly talks to the 3x-ui panel (API over the SSH tunnel) and the
VPS (SSH). A few jobs can only be done from the cloud side:

| Job | Why the cloud | Command (`ops.py cloud ...`) | Mode |
|---|---|---|---|
| Disk snapshot before an upgrade | the panel DB backup doesn't cover the OS, binaries, certs | `snapshot`, and automatically as step 1 of `upgrade` when `CLOUD_PROVIDER` is set | WRITE |
| Firewall port changes | NSG / VPC firewall sit outside the VM | `firewall-list`, `firewall-open PORT`, `firewall-close NAME` | RO / WRITE |
| VM restart | SSH is dead, or the VM is hung | `restart` | WRITE |
| VM resize | more/less CPU and RAM | `resize SIZE` | WRITE |
| IP rotation | the public IP is blocked or throttled | `rotate-ip` | WRITE |

All of them follow the same rules as everything else in this skill: preflight
card → action card (what/why, transport, exact command, identity by name,
read-only vs write, rollback) → dry run with a plan id → user says go →
`--execute --plan <id>` → result.

## Default: the cloud CLI

| Cloud | CLI | Install | Log in |
|---|---|---|---|
| Azure | `az` (Azure CLI) | https://learn.microsoft.com/cli/azure/install-azure-cli | `az login`, then `az account set --subscription "<name>"` |
| Google Cloud | `gcloud` (Google Cloud CLI) | https://cloud.google.com/sdk/docs/install | `gcloud auth login`, then `gcloud config set project <id>` |

Why the CLI is the default rather than an MCP server: every step is one
argv you can read on the card before it runs, the dry run shows exactly that
argv, the same command works in your own terminal, and nothing extra has to be
installed or granted to the agent's MCP host. The scripts never read token
caches: they call the CLI, which uses your own login.

## Alternatives: cloud MCP servers

Fine to use **instead of** the CLI if your agent already has them, as long as
the card rules still apply (show the exact tool + arguments, identity, RO/WRITE,
rollback, wait for go on writes):

| Cloud | Server | Notes |
|---|---|---|
| Azure | **Azure MCP Server**, [microsoft/mcp](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server) (`npx -y @azure/mcp@latest server start`) | Uses your Azure CLI / Entra login. Has a read-only mode; use it for status work |
| Google Cloud | **gcloud MCP server**, [googleapis/gcloud-mcp](https://github.com/googleapis/gcloud-mcp) (`npx -y @google-cloud/gcloud-mcp`) | Wraps the gcloud CLI (`run_gcloud_command`), uses the active gcloud account. Preview, "not an officially supported Google product" |
| Google Cloud | **Compute Engine remote MCP server**, `https://compute.googleapis.com/mcp` ([docs](https://docs.cloud.google.com/compute/docs/use-compute-engine-mcp)) | Google-managed. OAuth + IAM; needs `roles/mcp.toolUser` plus Compute roles. Covers instances, disks, snapshots; no firewall-rule or address tools in its published tool list (checked Nov 2026) |

With an MCP server, `ops.py cloud preflight` is still the check to run first:
it proves which identity and subscription/project the CLI login points at.
Make sure the MCP server uses the same one.

## Least privilege

Don't run this as subscription **Owner** or project **owner**. The preflight
warns when it sees one.

- **Azure:** `Contributor` scoped to the resource group (`vless-3xui-rg` by
  default), not the subscription. Narrower: `Virtual Machine Contributor` +
  `Network Contributor` + `Disk Snapshot Contributor` on that resource group.
  ```sh
  az role assignment create --assignee <you-or-sp> --role Contributor \
    --scope /subscriptions/<sub-id>/resourceGroups/vless-3xui-rg
  ```
- **Google Cloud:** `roles/compute.instanceAdmin.v1` (VM, disks, snapshots) +
  `roles/compute.securityAdmin` (firewall rules) on the project;
  `roles/compute.networkAdmin` only if you rotate IPs (address reservation).
  Or a custom role with exactly those permissions. Better still, a dedicated
  project for the VPN.

The role lists are from the providers' built-in role descriptions and were
not tested against a live tenant/project here. If a command fails with
"AuthorizationFailed" / "Required 'compute.X' permission", add that one
permission rather than jumping to Owner.

## Preflight (`scripts/cloud-preflight.sh`)

Read-only. Run before any cloud step (the ops commands run it themselves):

```sh
CLOUD_PROVIDER=azure AZURE_SUBSCRIPTION="VPN Sub" scripts/cloud-preflight.sh azure --require-vm
```

It checks: CLI installed (and version); logged in; active subscription equals
`AZURE_SUBSCRIPTION` (Azure; mismatch = FAIL) or `GCP_PROJECT` is describable
(GCP); resource group / VM exist; role names (best effort; warns on Owner).
It prints `identity=`, `subscription=` / `project=`, `roles=` (names and
ids only, never tokens) and ends with `PREFLIGHT=OK|FAIL`.

Same file ships in the setup skill (`vless-vpn-3xui-skill/scripts/`); a test
keeps the copies identical.

## Provider-specific gotchas

- **GCP ephemeral IPs.** The setup skill creates the VM with an ephemeral
  external IP. *Stopping* the VM (resize) releases it and every link breaks;
  `rotate-ip` deletes it for good. Both refuse unless the IP is reserved or you
  pass `--allow-ip-change`. Promote it first:
  `gcloud compute addresses create vless-3xui-ip --addresses <IP> --region <region>`.
  `restart` uses `instances reset` (hard reset, keeps the ephemeral IP).
- **Azure Standard static IP.** Kept across restart and resize. `rotate-ip`
  creates a new Standard static IP and swaps it on the NIC; the old IP resource
  is left in place (billed) for rollback until you delete it.
- **Snapshots cost money** until deleted. The card shows the delete command.
- **Firewall guard.** `firewall-close` refuses a rule that allows 22 (SSH) or
  443 (VLESS) unless `--allow-lockout`. Never open the panel port: use the tunnel.

## What's not verified

No real Azure subscription or GCP project was used. The command lines were
written from the CLIs' documented syntax and tested only against fake `az` /
`gcloud` binaries (`tests/fake_cloud.py`) that check the arguments we send, not
the clouds' behaviour. In particular unverified: `az snapshot create
--incremental true` on the VM's disk SKU; `az network nic ip-config update
--public-ip-address` on a running VM; GCP `delete-access-config` /
`add-access-config` downtime; the role lists above.
