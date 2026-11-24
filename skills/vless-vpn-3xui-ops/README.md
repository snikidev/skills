# vless-vpn-3xui-ops

Day-2 operations for a personal VLESS Reality VPN on
[3x-ui](https://github.com/MHSanaei/3x-ui) **v3.11.0**, the server that
[`vless-vpn-3xui-skill`](../vless-vpn-3xui-skill/) sets up (optional
`iproyal` SOCKS exit as the default outbound, `domain:openrouter.ai → direct`).

It's built so the person who owns the server always knows what the agent is
about to do. Before every action it prints a card:

- what it's doing and why
- the transport: panel API over the SSH tunnel / SSH command / cloud CLI / local
- the exact endpoint or command
- which credential, **by name and source only**
- read-only or write
- the rollback

Writes are dry runs that print a plan id; they only run when re-invoked with
`--execute --plan <id>` after the user says go. If anything changed in the
meantime, the id no longer matches and the script refuses.

## What it does

- **status**: x-ui/Xray service, version, users vs caps, Reality camouflage
  (TLS handshake vs the donor), egress IP direct vs proxy, routing decisions
- **users**: list / add / set cap+expiry / disable / enable / remove (with
  same-UUID rollback) / reset traffic / link + QR
- **routing**: list, test, add/remove rules with a redacted diff; probe AI
  providers direct vs via the proxy
- **backup / restore**: `x-ui.db` over the API, sha256 + SQLite integrity
  check, pre-restore backup
- **upgrade**: pinned `update.sh` from the release tag, backup first (and a
  cloud disk snapshot if configured), verify after
- **rotate**: Reality keys / shortId / SNI, regenerates every link
- **drift**: the live server vs what the skills expect
- **cloud** (az / gcloud): preflight, disk snapshot, firewall open/close,
  restart, resize, IP rotation
- **connect / rebind-localhost**: tunnel, and take the panel off the public interface

## Requirements / Dependencies

- `python3` 3.9+ (stdlib only), `ssh`, and passwordless `sudo` on the VPS for
  the few host-level steps (otherwise you run those yourself)
- a 3x-ui v3.11.0 panel and its admin API token (`XUI_API_TOKEN`); optional
  monitor-scope token for status
- optional: `openssl` (camouflage check), `qrencode` (QR)
- **Cloud (optional)**: the `az` or `gcloud` CLI is the default. It's
  scriptable and dry-runnable: the card shows the exact argv. Alternatives:
  [Azure MCP Server](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server),
  Google's [gcloud MCP server](https://github.com/googleapis/gcloud-mcp), or
  the managed Compute Engine MCP server (`https://compute.googleapis.com/mcp`).
  - Used for: a disk snapshot before an upgrade, firewall port changes, VM
    restart/resize, and IP rotation if the IP is blocked.
  - Auth: `az login` (+ `az account set --subscription`) or `gcloud auth login`
    (+ `gcloud config set project`).
  - Least privilege: Azure Contributor scoped to the resource group (not
    Owner, not subscription-wide); GCP Compute Instance Admin (v1) + Compute
    Security Admin (+ Network Admin for IP rotation) on the project.
  - `scripts/cloud-preflight.sh` runs before every cloud step. It checks the
    CLI is installed, you're logged in, and the subscription/project is the
    expected one, and prints which identity and subscription/project will be
    used (names only).
  - Cloud ops follow the same card + dry-run + go rules. See
    [references/cloud.md](references/cloud.md).

## Quick start

```sh
mkdir -p ~/.config/vless-ops
cp .env.example ~/.config/vless-ops/.env && chmod 600 ~/.config/vless-ops/.env
$EDITOR ~/.config/vless-ops/.env          # values from /etc/x-ui/install-result.env
python3 scripts/ops.py connect --open
python3 scripts/ops.py status
python3 scripts/ops.py users add alex --cap 50G --expires 30d      # dry run, prints plan id
python3 scripts/ops.py users add alex --cap 50G --expires 30d --execute --plan <id>
```

## Layout

```
SKILL.md                 agent instructions (card protocol, ops table)
.env.example             every config key, secrets marked
scripts/ops.py           CLI entry point
scripts/vlessops/        card, env, api, routing, users, remote, cloud, commands
scripts/_vendor/xui_api.py   copy of the setup skill's panel client (test keeps them identical)
scripts/tunnel.sh        SSH tunnel check/open/close (POSIX sh)
scripts/remote-status.sh read-only host snapshot, runs on the VPS via `sh -s`
scripts/cloud-preflight.sh   read-only az/gcloud identity + subscription check
references/              api-endpoints, transport-matrix, credentials-and-env,
                         cloud, troubleshooting, runbook
tests/                   mock 3x-ui panel, fake ssh/az/gcloud, pytest suite
```

## Tests

```sh
python3 -m pytest -q tests      # 30+ tests, no network, no real server
shellcheck -s sh scripts/*.sh
```

The panel mock follows the v3.11.0 source (CSRF before login, Bearer scopes,
`/clients` endpoints, the string-wrapped `/xray/` response, `getDb`/`importDB`).
The tests also check that no secret value appears in any output, and that
proxy credentials never show up in an ssh argv.

## Status

Verified against the 3x-ui v3.11.0 **source** and offline mocks only. Not
yet run against a live panel or a real cloud account. See
[references/api-endpoints.md](references/api-endpoints.md) and
[references/cloud.md](references/cloud.md) for the exact list.

## Licence

MIT © snikidev. 3x-ui is GPL-3.0 by its authors; this skill only calls its API
and CLI.
