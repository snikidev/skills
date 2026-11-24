---
name: vless-vpn-3xui-skill
description: Deploy a personal VLESS Reality VPN on 3x-ui (Azure or GCP), optionally chaining egress through a user-supplied UK static ISP SOCKS5 proxy. Use when the user asks to set up VLESS, XTLS-Reality, or 3x-ui on a VM, or to exit a cloud VPN via IPRoyal or another dedicated ISP proxy.
license: MIT
metadata:
  author: snikidev
  version: "0.3.0"
  xui_pin: v3.11.0
---

# VLESS Reality on 3x-ui

Automate a personal anti-DPI VPN on a new or existing Azure or GCP VM:

- VLESS + XTLS-Reality on TCP 443 (`xtls-rprx-vision`, uTLS chrome)
- Optional SOCKS5 outbound so destination sites see a static ISP IP, not the cloud VM

Configure the panel through its HTTP API, not by clicking the UI. This skill has **not** been run end-to-end against a live VM and proxy; be explicit about that, and read [references/api-and-unverified.md](references/api-and-unverified.md).

The user's longer narrative guide (Docker, WARP, gotchas) is
https://www.sniki.dev/posts/vless-vpn-gcp-setup/ — keep those Reality and client-compatibility lessons; this skill replaces WARP with an optional ISP proxy and uses the official systemd installer instead of Docker.

## Do not buy the proxy

You may create the VM, open firewall ports, SSH in, install 3x-ui, write the inbound, and add a SOCKS outbound. You must **not** purchase the proxy, enter payment details, or write credentials into git.

If the user wants ISP egress, stop and run the **human step** in [references/human-proxy-step.md](references/human-proxy-step.md):

- Buy a **static/dedicated ISP** proxy (e.g. IPRoyal ISP Proxies, UK London, typically a few dollars / 30 days).
- Avoid rotating residential billed per GB (prices like ~$800 / 200 GB).
- Decodo ISP plans that only allow destination ports 80, 443, 563, 8443, and 43 are usable for ordinary HTTPS through this VLESS (TCP 443) setup, but they still block plain DNS, WebRTC STUN, SSH, and most UDP. Prefer IPRoyal if those matter; do not treat Decodo as automatically unsuitable.

Wait until they paste `PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, and `PROXY_PASS`. If they skip this, continue; egress is the VM IP.

## Inputs to collect

Ask only for what is missing:

| Input | Default | Notes |
| --- | --- | --- |
| Cloud provider | — | `azure` or `gcp`. An already-running Debian 12/Ubuntu VM is also fine; skip VM create. |
| Region / zone | Azure `uksouth`, GCP `europe-west2-a` | London is the right default when the proxy is also in London. |
| VM size | Azure `Standard_B2s`, GCP `e2-small` | Debian 12. |
| SOCKS5 proxy | unset | Optional; see the human step. Tag the outbound `iproyal`. |
| Reality donor | `www.microsoft.com:443` | Re-test; see [references/donor-sites.md](references/donor-sites.md). |

Prerequisites on the operator machine: see **Requirements / Dependencies** below. Never embed secrets in command history you then paste into chat.

## Requirements / Dependencies

| Need | For |
| --- | --- |
| `ssh` + an SSH public key, `curl`, `python3`, `jq` | install, tunnel, API scripts |
| **Cloud CLI**: `az` (Azure) or `gcloud` (Google Cloud), logged in | step 1 (VM, public IP, firewall) |

**Cloud access.** The default is the cloud **CLI**: every step is a plain
command you can read and dry-run, and the `create-vm-*.sh` scripts use it.
Optional alternatives, if your agent already has them: the **Azure MCP Server**
([microsoft/mcp](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server),
`npx -y @azure/mcp@latest server start`), Google's **gcloud MCP server**
([googleapis/gcloud-mcp](https://github.com/googleapis/gcloud-mcp), preview),
or the managed **Compute Engine MCP server** (`https://compute.googleapis.com/mcp`).
With an MCP server, still run the preflight below and show the user each
create command before it runs.

- **What the cloud is used for**: creating the VM (Debian 12), its public IP
  (Azure Standard static; GCP ephemeral by default), and the NSG / VPC firewall
  rules (22 from your IP, 443 from anywhere; the panel port stays closed).
- **Auth**: `az login` then `az account set --subscription "<name>"`, or
  `gcloud auth login` then `gcloud config set project <id>`.
- **Least privilege**: don't use Owner. Azure: `Contributor` scoped to the
  resource group (`vless-3xui-rg`; create the group first, or have an admin do
  it). GCP: `roles/compute.instanceAdmin.v1` + `roles/compute.securityAdmin`
  on the project (a dedicated project is better still).
- **Preflight**: `scripts/cloud-preflight.sh azure|gcp` (read-only) checks the
  CLI is installed, you're logged in, and the active subscription/project is
  the expected one (`AZURE_SUBSCRIPTION` / `GCP_PROJECT`). It prints the
  identity, subscription/project and roles (names only, no tokens) and warns
  on Owner. `create-vm-*.sh` run it first and stop if it fails. **Run it
  yourself before step 1, show the user the identity and subscription/project,
  and wait for their go before creating anything.**

Day-2 management (users, routing, backups, upgrades, rotation, cloud
snapshot/firewall/resize/IP rotation) is in the companion skill
[vless-vpn-3xui-ops](../vless-vpn-3xui-ops/).

## Steps

Work from a checkout of this skill so `scripts/` and `templates/` are available. Copy `.env.example` to `.env` locally if useful; do not commit it.

### 1. Create the VM and open the firewall

First: `./scripts/cloud-preflight.sh azure` (or `gcp`). Show the user the `identity=` and `subscription=` / `project=` lines, and wait for their go.

```bash
# Azure
./scripts/create-vm-azure.sh    # prints the public IPv4

# or GCP
./scripts/create-vm-gcp.sh
```

Each script is idempotent enough to reuse an existing VM with the same name. It opens:

- TCP 22 from the operator's current public IP only
- TCP 443 from anywhere (VLESS Reality)

It does **not** publish the 3x-ui panel port. Reach the panel with an SSH tunnel. Re-running also deletes leftover port-8388 rules from earlier revisions of this skill.

### 2. Install 3x-ui (official script, pinned)

```bash
./scripts/remote-setup.sh debian@VM_IP
```

That copies `scripts/` to the VM and runs `install-3xui.sh` with sudo. The installer is downloaded from the **release tag**, then executed (never `sudo bash <(curl ...)`):

```bash
# What install-3xui.sh does on the VM
curl -fsSL -o /tmp/3x-ui-install-v3.11.0.sh \
  https://raw.githubusercontent.com/MHSanaei/3x-ui/v3.11.0/install.sh
sudo XUI_NONINTERACTIVE=1 bash /tmp/3x-ui-install-v3.11.0.sh v3.11.0
```

Default pin: **v3.11.0** (Xray-core v26.10.21). Override with `XUI_VERSION` only after reading that tag's notes. Credentials are written to `/etc/x-ui/install-result.env` (mode 600) on the VM. Do not copy that file into the repo.

Optional host hardening in the installer: BBR on by default (`ENABLE_BBR=1`), UFW off by default (`ENABLE_UFW=1` to allow 22/443 and leave the panel closed).

### 3. Open a panel tunnel

```bash
./scripts/ssh-tunnel-panel.sh debian@VM_IP
# localhost:2053 -> 127.0.0.1:<panel-port>
```

In another terminal, export a local API endpoint (web base path comes from `install-result.env`):

```bash
# On the VM you can instead talk to localhost and skip the tunnel
export PANEL_BASE_URL="http://127.0.0.1:${XUI_PANEL_PORT}/${XUI_WEB_BASE_PATH}"
export XUI_API_TOKEN="..."          # preferred
# or: export XUI_USERNAME=... XUI_PASSWORD=...
```

### 4. Create the VLESS Reality inbound via the API

```bash
mkdir -p out && chmod 700 out
python3 scripts/configure-inbounds.py \
  --dest www.microsoft.com:443 --sni www.microsoft.com \
  --state-out out/state.json
```

This calls `GET /panel/api/server/getNewX25519Cert` for Reality keys, allocates a UUID and an 8-byte shortId, and `POST /panel/api/inbounds/add`:

- VLESS, listen IP empty (cloud NATs), port 443, flow `xtls-rprx-vision`, `network=tcp`, `security=reality`, `fingerprint=chrome`, empty mldsa65 / min/max client versions

If a VLESS inbound on that port already exists, it is reused. Then `POST /panel/api/server/restartXrayService`.

Before locking the donor, on the VM: `curl -I https://www.microsoft.com` (no 301/302) and `xray tls ping www.microsoft.com` (no post-quantum if clients cannot handshake). See [references/donor-sites.md](references/donor-sites.md).

### 5. Optional: add the ISP SOCKS outbound

Only after the user has pasted proxy details:

```bash
export PROXY_HOST=... PROXY_PORT=12324 PROXY_USER=... PROXY_PASS=...
python3 scripts/add-proxy-outbound.py          # tag iproyal, first outbound
./scripts/verify-egress.sh
```

`add-proxy-outbound.py` will:

1. `POST /panel/api/xray/` to read the template
2. Insert a SOCKS outbound tagged `iproyal` at **index 0** (Xray's default)
3. Point the `geoip:private` routing rule at `direct`
4. Relax `direct`'s freedom `finalRules` so that rule is not silently blocked (3x-ui v3.6+ SSRF hardening)
5. Add DoH (`https://1.1.1.1/dns-query`) tagged so DNS can egress via the proxy
6. `POST /panel/api/xray/update` and restart Xray

Keep the `api` → `api` and `bittorrent` → `blocked` rules.

`verify-egress.sh` curls `ipinfo.io` from the host and again through `socks5h://` (remote DNS). The proxy IP must differ from the VM IP and should look like an ISP ASN. That proves the proxy, not the VLESS path — still have the user test from a client (checklist below).

### 6. Emit the link, QR code, and the test checklist

```bash
PUBLIC_IP=x.x.x.x STATE_FILE=out/state.json ./scripts/make-links.sh
```

Give the user the `vless://` URL (and a QR image under `out/` if `qrencode` is installed). Use the VM's public IP, never the panel hostname or `127.0.0.1`. Reality links that get a stale UUID, `sid`, or `pbk` after a later inbound change fail silently (the server forwards bad clients to the real donor site). Re-run `make-links.sh` after any inbound edit.

## Client test checklist

1. From the client network: `nc -zv VM_IP 443` — if this fails, it is a firewall or path problem, not Xray.
2. Import `vless://` into a Reality-capable client (e.g. Streisand, Rabbithole, v2rayNG, v2rayN, command-line xray). Connect. Open https://ipinfo.io/json — expect the **proxy** IP if one was configured, otherwise the VM IP.
3. https://browserleaks.com/dns and https://browserleaks.com/webrtc — no home-ISP or VM-datacentre leaks.
4. Optional: https://speed.cloudflare.com. Voice/video calls need a proxy that allows UDP to non-443 ports.

## Security rules for the agent

- Prefer the SSH tunnel; do not open the panel port to `0.0.0.0/0`. If the user insists on browser access, restrict that port to their current IP only and say so.
- Never commit `.env`, `/etc/x-ui/install-result.env`, `out/state.json`, or proxy passwords.
- Do not print full passwords or API tokens in the chat; refer to the mode-600 files on the VM.
- Listen IP on inbounds stays empty (cloud external IPs are usually 1:1 NAT).
- This is a personal VPN. Follow the law and the ToS of the cloud and proxy providers. 3x-ui itself is documented by its authors as not a production control plane.

## If something already exists

The user may already have a 3x-ui VM. Skip step 1 (and maybe step 2). Probe with SSH, read `install-result.env` or `x-ui settings`, then run steps 3–6. `configure-inbounds.py` and `add-proxy-outbound.py` are safe to re-run: they reuse a matching inbound and update the `iproyal` outbound in place.

## After setup

Use [vless-vpn-3xui-ops](../vless-vpn-3xui-ops/) for everything after day 1. It reuses `scripts/xui_api.py` and announces every action with a card: transport, endpoint, credential by name, read-only or write, rollback.
