# skills

Agent skills by [snikidev](https://github.com/snikidev). Each skill is a folder
with a `SKILL.md` plus the scripts and references that make it more than a
prompt. Works with OpenCode / OpenChamber, Claude Code, and anything else that
reads the `SKILL.md` format.

## Skills

| Skill | What it does | Ships |
|---|---|---|
| [`netis-nx62-openwrt-safe-flash`](skills/netis-nx62-openwrt-safe-flash/) | Step-by-step, extra-safe OpenWrt install on a Netis NX62 / Netcore N60 Pro: triple-checked backups, stop after every step, typed confirmation for every flash write | 9 POSIX sh scripts, 5 references |
| [`vless-vpn-3xui-skill`](skills/vless-vpn-3xui-skill/) | Personal VLESS Reality VPN on 3x-ui (Azure or GCP), configured through the panel API, with an optional static ISP SOCKS5 exit. Needs `az` or `gcloud` (preflight-checked) | 13 scripts (bash + Python), 3 references, Xray templates |
| [`vless-vpn-3xui-ops`](skills/vless-vpn-3xui-ops/) | Day-2 ops for that server: status, users (caps, expiry, links/QR), routing + provider probe, backup/restore, pinned upgrades, Reality rotation, drift, and cloud snapshot/firewall/resize/IP rotation. Every action is a card (transport, endpoint, credential by name, RO/write, rollback); writes are dry runs until you say go | Python CLI (stdlib), 3 POSIX sh scripts, 6 references, mock-panel test suite |

## Layout

```
skills/
  <skill-name>/
    SKILL.md          # frontmatter (name, description) + instructions
    README.md         # human overview, credits
    scripts/          # executable helpers the agent runs
    references/       # docs the agent reads on demand
```

`skills/<name>/SKILL.md` is the layout OpenChamber's catalog scans; a
`SKILL.md` at a repo root is skipped.

## Install

Pick a skill and put its folder where your agent looks for skills. The folder
name must match the `name:` in its frontmatter.

```sh
git clone https://github.com/snikidev/skills ~/src/snikidev-skills
SKILL=netis-nx62-openwrt-safe-flash
```

**OpenCode / OpenChamber** (global):

```sh
mkdir -p ~/.config/opencode/skills
ln -s ~/src/snikidev-skills/skills/$SKILL ~/.config/opencode/skills/$SKILL
```

Per project: `.opencode/skills/$SKILL/`. In OpenChamber you can also add this
repo as a skills source; it reads `skills/<name>/SKILL.md`.

**Claude Code** (global or per project):

```sh
mkdir -p ~/.claude/skills
ln -s ~/src/snikidev-skills/skills/$SKILL ~/.claude/skills/$SKILL
# or: <project>/.claude/skills/$SKILL
```

**skills CLI** (`npx skills`, from skills.sh):

```sh
npx skills add snikidev/skills
```

Use symlinks (as above) to get updates with `git pull`; copy the folder if you
want to pin a version.

## Conventions

- **Scripts or it doesn't ship.** A skill earns its place with code or data a
  model can't get from a web search: scripts, checklists with gates, verified
  references. Plain advice belongs in a blog post.
- **Safe by default.** Scripts are read-only unless given an explicit flag.
  Anything destructive is a dry run first and needs a human confirmation the
  agent can't fake.
- **Stop and report.** Long or risky procedures go step by step: say what's
  next, do it, show the evidence, wait.
- **Portable shell.** POSIX `sh`, `shellcheck`-clean. Scripts that run on
  devices (routers etc.) target BusyBox `ash`.
- **No secrets.** No tokens, passwords or personal data in skills, examples or
  logs. Interactive `sudo` only.
- **Cite sources.** References say where facts came from and flag anything
  unverified.
- **Credit** the work a skill builds on in its README, and respect licenses.

## Contributing

1. `skills/<kebab-case-name>/` with `SKILL.md` (frontmatter `name` = folder
   name, `description` says when to use it and when not to).
2. Add `scripts/` and `references/` as needed; `shellcheck -x -s sh scripts/*.sh`.
3. Add a row to the table above.

## License

[MIT](LICENSE) © snikidev
