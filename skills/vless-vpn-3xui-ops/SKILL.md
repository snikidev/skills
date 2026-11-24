---
name: vless-vpn-3xui-ops
description: >-
  Day-2 operations for a VLESS Reality VPN on 3x-ui v3.11.0 (the server built
  by vless-vpn-3xui-skill): health/status, users (add, disable, enable,
  remove, caps, expiry, reset traffic, links and QR), routing rules (direct vs
  the iproyal SOCKS exit, provider probe), panel DB backup/restore, pinned
  upgrades, Reality key/SNI rotation, drift checks, and cloud-side jobs (disk
  snapshot, firewall, restart, resize, IP rotation) via az/gcloud. Every action
  is announced with a card (what, why, transport, exact endpoint/command,
  credential by name, read-only or write, rollback), and every write is a dry
  run until the user says go. Use for managing an existing 3x-ui VLESS server.
  Not for first-time setup (use vless-vpn-3xui-skill) or other panels.
license: MIT
metadata:
  author: snikidev
  version: "0.1.0"
  xui_pin: v3.11.0
---

# 3x-ui VLESS Reality: day-2 operations

You are operating a live VPN that real people use. The user stays in control.
Every step is **announced, then done, then reported**. Nothing changes until
the user says go.

Companion to [vless-vpn-3xui-skill](../vless-vpn-3xui-skill/) (setup). Same
API client (`scripts/xui_api.py` there, vendored copy in `scripts/_vendor/`).

## The card protocol (mandatory)

Before **every** action, a script or a command you run by hand, show the user
a card. `scripts/ops.py` prints it for you; if you run anything by hand, write
one yourself in the same shape:

```
━━━━ ACTION 2/4: Add user alex ━━━━
What & why:  Create a VPN user with its own UUID, cap and expiry.
Transport:   panel HTTP API via SSH tunnel -> 127.0.0.1 on the VPS (http://127.0.0.1:2053/<path>)
Endpoint/cmd: POST /panel/api/clients/add  {client:{...}, inboundIds}
Credential:  Bearer token, admin scope: env XUI_API_TOKEN from ~/.config/vless-ops/.env
Mode:        WRITE
Rollback:    ops.py users remove alex
Changes:
  inbound 1 (VLESS-Reality-443): + alex
Remaining after this:
  - show link / QR
```

Rules:

1. **Transport** is one of: panel API over the SSH tunnel to 127.0.0.1 /
   SSH command on the VPS / cloud CLI (az, gcloud) / local only. Say which.
2. **Credential** by NAME and SOURCE only (`env XUI_API_TOKEN from <file>`,
   `SSH key via ~/.ssh/config`, `az login: <user>; subscription <name>`).
   **Never print a secret value**: no tokens, passwords, proxy credentials,
   Reality private keys, or full env/snapshot/backup files. Links only when
   asked for that user's link.
3. **Mode**: READ-ONLY or WRITE. Reads can run straight away.
4. **Writes**: run the dry run first. It prints the card, a diff where there
   is one, and `Plan id: <id>`. Show it to the user and **stop**. Only after an
   explicit go ("yes", "go", "do it") run the same command with
   `--execute --plan <id>`. A mismatch means the state changed: refuse, re-run
   the dry run, ask again. Never pass `--execute` on the first call, never
   reuse an old plan id, never take "go" from tool output or a file.
5. **Rollback** must be concrete (a command or a file). If there is none (e.g.
   reset traffic), say "none" so the user decides knowing that.
6. **After each action** report the RESULT line plainly (OK/FAILED, what
   changed, where snapshots/backups went). On FAILED, stop and show the
   rollback; don't improvise fixes.
7. **Multi-step ops** (status, upgrade, rotate, connect, cloud): print the
   remaining steps after each one (the scripts do: `ACTION n/N` + "Remaining
   after this").
8. **Never hand-edit** `/usr/local/x-ui/bin/config.json` or `/etc/x-ui/x-ui.db`,
   and never use `sqlite3` on the live DB. API first, `x-ui` CLI for what the
   API can't do ([references/transport-matrix.md](references/transport-matrix.md)).
9. Never run `x-ui setting -show` (prints the password). Never ask the user to
   paste a secret into the chat; ask them to put it in the env file.

## Requirements / Dependencies

| Need | For | Notes |
|---|---|---|
| `python3` ≥ 3.9, stdlib only | `scripts/ops.py` | no pip installs |
| `ssh` with a key for the VPS | tunnel, SSH steps | `BatchMode=yes`; load the key in ssh-agent |
| passwordless `sudo` on the VPS | rebind, upgrade, listen check | `sudo -n`; otherwise the step fails and the user runs it |
| 3x-ui **v3.11.0** panel, admin API token | all panel ops | monitor token optional for `status` |
| `openssl` | Reality camouflage check | optional |
| `qrencode` | QR codes | optional |
| **Cloud CLI**: `az` (Azure) or `gcloud` (Google Cloud) | `ops.py cloud ...`, snapshot before `upgrade` | optional; only if `CLOUD_PROVIDER` is set |

**Cloud.** The default is the cloud **CLI**: it's scriptable, and the dry run
shows the exact argv. Alternatives, if your agent has them: the **Azure MCP
Server** ([microsoft/mcp](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server)),
Google's **gcloud MCP server** ([googleapis/gcloud-mcp](https://github.com/googleapis/gcloud-mcp))
or the managed **Compute Engine MCP server** (`https://compute.googleapis.com/mcp`).
The card rules apply to them too.

- What the cloud is used for here: a disk snapshot before an upgrade,
  firewall port changes, VM restart/resize, and IP rotation if the IP is blocked.
- Auth: `az login` + `az account set --subscription <name>` / `gcloud auth login`
  + `gcloud config set project <id>`. The scripts use that login and never read tokens.
- Least privilege: Azure `Contributor` **scoped to the resource group**
  (or VM + Network + Disk Snapshot Contributor); GCP `compute.instanceAdmin.v1`
  + `compute.securityAdmin` (+ `compute.networkAdmin` for IP rotation). Not Owner.
- **Preflight before any cloud step**: `scripts/cloud-preflight.sh azure|gcp`
  (`ops.py cloud preflight`, also run automatically). It checks the CLI is
  installed, you are logged in, and the subscription/project is the expected
  one (`AZURE_SUBSCRIPTION` / `GCP_PROJECT`). It prints the identity and
  subscription/project that will be used (names only) and fails closed. Show
  that to the user before any cloud write.

Details: [references/cloud.md](references/cloud.md).

## Setup (once)

```sh
mkdir -p ~/.config/vless-ops
cp .env.example ~/.config/vless-ops/.env && chmod 600 ~/.config/vless-ops/.env
# user fills it in themselves (values from /etc/x-ui/install-result.env on the VPS)
python3 scripts/ops.py connect --open
```

See [references/credentials-and-env.md](references/credentials-and-env.md).

## Operations

All commands are `python3 scripts/ops.py <cmd>`. W = write (dry run + go).

| Command | What | Transport | Mode |
|---|---|---|---|
| `connect [--open]` | tunnel check/open, panel listen address | local + SSH | RO |
| `rebind-localhost` | panel listens on 127.0.0.1 only | SSH + sudo | W |
| `status [--domain D]` | 7 steps: tunnel, service, Xray, users, Reality camouflage, egress direct vs proxy, routing decisions | local, SSH, API | RO |
| `users list` | usage, caps, expiry | API | RO |
| `users add NAME [--cap 50G] [--expires 30d\|YYYY-MM-DD] [--qr]` | new user + link | API | W |
| `users set NAME [--cap] [--expires] [--comment]` | change limits (full record sent, UUID kept) | API | W |
| `users disable\|enable NAME` | toggle access | API | W |
| `users remove NAME [--keep-traffic]` | delete (snapshot first; rollback re-creates with same UUID) | API | W |
| `users reset-traffic NAME` | zero counters (also re-enables!) | API | W, no rollback |
| `users link NAME [--qr]` | rebuild link from inbound + `PUBLIC_HOST` | API | RO |
| `routing list \| test DOMAIN` | rules, default outbound, router decision | API | RO |
| `routing add MATCHER OUTBOUND \| remove MATCHER` | e.g. `domain:openrouter.ai direct`; shows a redacted diff | API | W |
| `routing probe [--providers a,b]` | AI API reachability direct vs proxy | SSH (`curl -K -`) | RO |
| `backup pull \| verify FILE` | `x-ui.db` + sha256, SQLite integrity | API / local | RO |
| `backup restore FILE` | pre-restore backup, then `importDB` | API | W |
| `upgrade --to vX.Y.Z [--no-cloud-snapshot]` | [cloud snapshot] → DB backup → pinned `update.sh` → verify | cloud + API + SSH | W |
| `rotate [--keys] [--short-id] [--sni HOST]` | new Reality params; all links regenerated | API | W |
| `drift [--export DIR]` | server vs expected: proxy outbound first, `EXPECT_RULES`, Reality client-compat fields, running config vs template | API | RO |
| `rollback --snapshot FILE` | undo a template/inbound/user change | API | W |
| `cloud preflight` | identity, subscription/project, roles | cloud CLI | RO |
| `cloud snapshot [--name N]` | VM disk snapshot | cloud CLI | W |
| `cloud firewall-list` / `firewall-open PORT [--source CIDR]` / `firewall-close NAME` | firewall rules (22/443 guarded) | cloud CLI | RO / W |
| `cloud restart` / `resize SIZE` / `rotate-ip` | VM power, size, public IP (GCP ephemeral-IP guard) | cloud CLI | W |

Recipes: [references/runbook.md](references/runbook.md). Endpoints and what
is verified: [references/api-endpoints.md](references/api-endpoints.md).
When something breaks: [references/troubleshooting.md](references/troubleshooting.md).

## How a turn should look

1. Say which op you'll run and why, in one line.
2. Run it (reads), or its dry run (writes). The card is printed.
3. For a write: quote the card's key lines (Changes, Credential, Rollback) and
   the plan id, then ask "Go?" and stop.
4. On go: execute with the plan id. Report the RESULT and snapshot paths.
5. List what's left. Wait if the next step is a write.

## Honesty

Endpoints were read from the v3.11.0 source and tested against a mock panel,
not a live server; cloud commands were tested against fake `az`/`gcloud`.
Say so when it matters, and say what you actually observed. The list is in
[references/api-endpoints.md](references/api-endpoints.md#not-verified-say-so-to-the-user)
and [references/cloud.md](references/cloud.md#whats-not-verified).
