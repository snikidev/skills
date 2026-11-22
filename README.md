# vless-vpn-3xui-skill

An [Agent Skill](https://agentskills.io/specification) that walks an agent
(Claude Code, Cursor, OpenCode, and anything else that reads `SKILL.md`)
through deploying a personal **VLESS Reality** and/or **Outline-compatible
Shadowsocks** VPN on [3x-ui](https://github.com/MHSanaei/3x-ui), on Azure or
GCP, with an optional **UK static ISP SOCKS5** egress proxy that you buy
yourself.

This repository is a starting point, not a battle-tested appliance. **It has
not been run end-to-end against a live VM and a real ISP proxy.** Read
[references/api-and-unverified.md](references/api-and-unverified.md) before
you treat the API scripts as proven. The setup is for personal use; you are
responsible for following the law and the terms of your cloud and proxy
providers.

The Reality / client-compatibility lessons (empty mldsa65 fields, donor
vetting, "export URL used the panel hostname", keys changing silently
invalidates old links) come from
[sniki.dev — Setting up a personal VLESS VPN on GCP with XTLS-Reality](https://www.sniki.dev/posts/vless-vpn-gcp-setup/).
That guide uses Docker-pinned 3x-ui `v2.9.4` plus Cloudflare WARP. This skill
uses the official **systemd** installer pinned to **3x-ui v3.11.0**
(Xray-core v26.10.21, released 25 October 2026) and an optional ISP proxy
instead of WARP.

## What you get

- A Debian 12 VM (or reuse of one you already have)
- Firewall: SSH from your IP, TCP 443, TCP+UDP 8388. The panel stays off the
  public internet (SSH tunnel).
- VLESS + XTLS-Reality on 443 (`xtls-rprx-vision`)
- Shadowsocks on 8388 with `chacha20-ietf-poly1305` (Outline does not support
  `2022-blake3-*`)
- Optional SOCKS5 outbound tagged `iproyal`, first in the outbound list, with
  `geoip:private` → `direct`
- `vless://` and `ss://` links plus QR codes
- A short client test checklist

## Install the skill

Clone this repo into the skills directory of the agent you use. The folder
name must stay `vless-vpn-3xui-skill` so it matches the `name` field in
`SKILL.md`.

```bash
# Claude Code (user-level)
git clone https://github.com/snikidev/vless-vpn-3xui-skill.git ~/.claude/skills/vless-vpn-3xui-skill

# Cursor (user-level)
git clone https://github.com/snikidev/vless-vpn-3xui-skill.git ~/.cursor/skills/vless-vpn-3xui-skill

# OpenCode (user-level)
git clone https://github.com/snikidev/vless-vpn-3xui-skill.git ~/.config/opencode/skills/vless-vpn-3xui-skill
```

Project-local copies also work: `.claude/skills/`, `.cursor/skills/`, or
`.opencode/skills/` in the repo you are working in. Cursor and OpenCode will
often also pick up skills from `~/.claude/skills/`.

Then ask the agent to deploy a VLESS / Outline VPN (and mention Azure or GCP,
and whether you have an ISP proxy). It should load this skill and follow
`SKILL.md`.

You can also run the scripts yourself; they do not require an agent.

## Human step: the proxy

The agent can do everything except pay for the proxy. If you want destination
sites to see a UK ISP IP rather than a cloud IP:

1. Buy a **static / dedicated ISP** proxy yourself (IPRoyal ISP Proxies, UK
   London, SOCKS5 with UDP, is the usual recommendation). A 24-hour trial is
   cheaper than guessing.
2. Do **not** buy rotating residential bandwidth billed per GB.
3. Do **not** use an ISP product that only allows destination ports 80, 443,
   563, 8443, and 43 (Decodo's ISP plans have been in that category).
4. Paste host, port, username, and password into the agent or a local `.env`.
   Never commit them.

Details: [references/human-proxy-step.md](references/human-proxy-step.md).

If you skip this, the VPN still works; `ipinfo.io` will show the VM IP.

## Scripted path (no agent)

```bash
cp .env.example .env          # edit locally, do not commit
./scripts/create-vm-azure.sh  # or ./scripts/create-vm-gcp.sh
./scripts/remote-setup.sh debian@VM_IP
./scripts/ssh-tunnel-panel.sh debian@VM_IP   # leave running

# another terminal, after sourcing credentials from the VM:
export PANEL_BASE_URL=http://127.0.0.1:2053/<webBasePath>
export XUI_API_TOKEN=...
mkdir -p out && chmod 700 out
python3 scripts/configure-inbounds.py --state-out out/state.json

# only if you have proxy details:
python3 scripts/add-proxy-outbound.py
./scripts/verify-egress.sh

PUBLIC_IP=VM_IP STATE_FILE=out/state.json ./scripts/make-links.sh
```

`scripts/lib.sh` is sourced by the bash scripts. Python helpers
(`xui_api.py`, `configure-inbounds.py`, `add-proxy-outbound.py`,
`render_links.py`) use the standard library only.

## Security notes

- Keep the 3x-ui panel off the public internet. Use
  `scripts/ssh-tunnel-panel.sh`. Credentials live in
  `/etc/x-ui/install-result.env` on the VM (mode 600).
- Do not commit `.env`, proxy credentials, `out/state.json`, or QR codes
  that encode live keys.
- Leave inbound listen IPs empty on Azure/GCP; the public address is typically
  NAT'd and Xray cannot bind it directly.
- Regenerating Reality keys or recreating an inbound invalidates old
  `vless://` links with no obvious error. Re-run `make-links.sh`.
- Provider terms (cloud and proxy) usually forbid resale, torrents, and
  sometimes use from particular jurisdictions. Read them. This is not legal
  advice.

## Layout

```
SKILL.md                         # agent instructions (this is the skill)
README.md
LICENSE                          # MIT
.env.example
scripts/                         # operator + VM scripts
templates/                       # SOCKS outbound / routing snippets
references/                      # proxy buying, API notes, Reality donors
```

## Licence

MIT. See [LICENSE](LICENSE).
