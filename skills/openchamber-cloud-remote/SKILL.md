---
name: openchamber-cloud-remote
description: Deploy and operate an on-demand Azure, GCP or AWS Ubuntu VM for OpenChamber Desktop Remote Instances, with SSH wake-on-connect and 30-minute idle stop/deallocation. Use when setting up, reconnecting, troubleshooting or tearing down that remote; do not use for other cloud VMs, clusters or SSH hosts.
---

# OpenChamber cloud remote

One Ubuntu 24.04 VM that costs compute only while someone is connected.
`ssh oc-remote` wakes a stopped/deallocated VM through a local `ProxyCommand`;
a systemd timer on the VM stops it again after 30 minutes with no SSH sessions.
OpenChamber Desktop connects with managed install over the same SSH alias.

## Ask first — no silent defaults

Before any dry run or write, ask the user in one form (render UI with choices and
a note field) for:

- **Provider** — Azure, GCP or AWS.
- **VM size** — choose from the recommended list in `references/sizing.md` for
  that provider, or let the user type a custom size in the note field.
- **Region** — provider-specific default is only a suggestion in the question,
  never an assumed answer.
- **SSH source CIDR** — the client's public IP as `/32`.

Put the answers in the session and pass them to every script as env vars:

```sh
OC_CLOUD_PROVIDER=azure|gcp|aws
OC_VM_SIZE=<explicit size>
OC_SSH_SOURCE_CIDR=203.0.113.7/32
```

Every deploy script refuses to run when `OC_VM_SIZE` is empty, and
`deploy.sh` refuses to run without an explicit provider argument. If a user
says "just pick one", ask again with the recommendations — do not choose.

## Safety

- Scripts are read-only by default. Writes need `--apply`; show the plan first.
- Stop/deallocation, IAM/role changes, static IPs and firewall/security-group
  changes are writes. Get an explicit go-ahead before applying them.
- Only SSH from the chosen CIDR is exposed. If the client IP changes, update the
  provider's firewall rule or you will lock yourself out.
- Keep the SSH private key, cloud tokens, subscription/project/account ids and
  personal identifiers out of chat and logs.
- Azure is live-tested. GCP and AWS use the same design but have not been
  deployed in this setup; verify IAM and image ids in the target account.

## Prerequisites

- Provider CLI logged in: `az`, `gcloud` or `aws`. Python 3, `curl`, `nc` on the
  client. `python3` also runs on the VM.
- SSH key pair (default `~/.ssh/openchamberazure.pub`), same key on all clouds.
- The public IP must survive a stop: Azure uses a static public IP, GCP a
  reserved address, AWS an Elastic IP. A plain stop/start otherwise changes it.

## Setup order

1. Decide provider, size, region and source CIDR (above).
2. `scripts/deploy.sh <provider>` then `scripts/deploy.sh <provider> --apply` —
   creates the network, firewall, reserved public IP and VM. GCP and AWS need
   the identity from step 3 first; create that identity with the matching
   `scripts/setup-<provider>-role.sh --apply` before deploying those two.
   Azure deploys the VM first and configures its identity in step 3.
3. `scripts/setup-vm-role.sh <provider>` then `--apply` — gives the VM's own
   identity only the permissions needed to read and stop/deallocate itself.
4. `scripts/install-wake-proxy.sh` then `--apply` — installs the local
   `ProxyCommand` and writes `~/.ssh/oc-wake.conf` with the chosen provider and
   resource ids. It prints the `oc-remote` alias for `~/.ssh/config`.
5. `scripts/install-idle-shutdown.sh` then `--apply` — installs the shared idle
   script and systemd units on the VM, plus `/etc/oc-remote.conf` naming the
   provider whose stop API to call.
6. In OpenChamber Desktop: **Settings → Remote Instances → Add**, SSH command
   `ssh oc-remote`, managed install, no SSH password. Set `ConnectTimeout` above
   60 s; a cold start takes about 45 s.

## Verification

`scripts/verify.sh` is read-only: it prints the provider power state and, when
the VM is running, the installed tool versions, timer state and idle log tail.
Logs: `~/.ssh/oc-wake.log` locally, `/var/log/oc-idle-shutdown.log` on the VM.

The idle script ignores the first five minutes after boot, then stops after
1800 seconds with no SSH users and no established port-22 connections. On Azure
it calls `deallocate`, not `stop`: only deallocation ends compute billing.
On GCP and AWS a stopped VM likewise stops compute charges; storage and
reserved/public IPs may still cost money.

`references/deployment.md` has the manual commands and teardown steps.

## Files

| Path | Purpose |
|---|---|
| `scripts/deploy.sh` | Provider dispatcher; requires explicit provider and size |
| `scripts/deploy-azure.sh`, `deploy-gcp.sh`, `deploy-aws.sh` | Per-provider deployment |
| `scripts/setup-vm-role.sh` | Provider dispatcher for self-power identity |
| `scripts/setup-azure-role.sh`, `setup-gcp-role.sh`, `setup-aws-role.sh` | Least-privilege identity setup |
| `scripts/install-wake-proxy.sh` | Local wake proxy and SSH config writer |
| `scripts/install-idle-shutdown.sh` | VM idle script and systemd unit installer |
| `scripts/verify.sh` | Read-only health check |
| `scripts/oc-wake-proxy.sh` | Canonical multi-provider wake proxy |
| `scripts/oc-idle-shutdown.sh` | Canonical VM-side stop script |
| `references/sizing.md` | Explicit size catalogs and quota checks |
| `references/` | Bicep, cloud-init, role definitions, systemd units, manual guide |
