# Runbook

Each recipe is a sequence of `ops.py` calls. Before each one the script prints
its card; for writes, show the card and the plan id to the user, **wait for an
explicit go**, then re-run with `--execute --plan <id>`. Report the RESULT
and print the remaining steps before moving on.

`ops.py` = `python3 scripts/ops.py` from this skill's folder.

## First time on a server

1. Fill `~/.config/vless-ops/.env` from `.env.example`, then `chmod 600` it
   ([credentials-and-env.md](credentials-and-env.md)).
2. `ops.py connect --open`: opens the tunnel, then reads the panel's listen address.
3. If it says `0.0.0.0`: `ops.py rebind-localhost` (WRITE, SSH + sudo).
4. `ops.py status`: the baseline. Save the output.
5. `ops.py backup pull`: the first backup.
6. `ops.py drift`: compares the server with what this skill expects.
7. Optional, with a cloud: `ops.py cloud preflight`.

## Weekly health check (read-only)

`ops.py status` → `ops.py users list` → `ops.py drift` → `ops.py backup pull`.

## Add a user for a friend

1. `ops.py users add alex --cap 50G --expires 30d` → card → go → execute.
2. The link prints after the user is created. Send it to them yourself over a
   private channel; the agent doesn't send it anywhere.
3. QR: `ops.py users link alex --qr` (needs `qrencode`).

## Someone over their cap or expired

`ops.py users list` → `ops.py users set NAME --cap 100G` or `--expires 2027-01-31`,
or `ops.py users reset-traffic NAME`. Note that reset also re-enables the user.

## A link leaked

- One user's link: `users remove NAME` → `users add NAME` (gets a new UUID) → send the new link.
- The whole server is fingerprinted: `ops.py rotate --keys --short-id`. Every
  user must re-import; links are written to `$OPS_STATE_DIR/links-*.txt`.

## A site blocks the proxy IP (e.g. OpenRouter)

1. `ops.py routing probe` shows which providers answer direct vs via the proxy.
2. `ops.py routing add domain:openrouter.ai direct` → diff → go → execute.
3. `ops.py routing test openrouter.ai` should now say `direct`.

The setup skill doesn't add the `openrouter.ai` rule; `EXPECT_RULES` in
`.env.example` expects it, because the server this was written for has it.
Change `EXPECT_RULES` if yours shouldn't.

## Upgrade 3x-ui

1. Read the release notes of the target tag (Reality/Xray changes break clients).
2. `ops.py upgrade --to vX.Y.Z` → card. If `CLOUD_PROVIDER` is set it shows
   the preflight identity and adds a cloud disk snapshot as step 1.
3. Go → execute. The steps: [cloud snapshot] → DB backup (verified) →
   `update.sh` from the tag → wait → verify version, Xray, egress.
4. Update `XUI_VERSION` in the env file and in your notes.
5. Test from a real client.

## Restore after a bad change

- Routing/template: `ops.py rollback --snapshot <file printed by the change>`.
- User edit/removal: the same, with the user snapshot.
- Whole panel: `ops.py backup verify FILE` → `ops.py backup restore FILE`.
- Whole VM: restore from the cloud snapshot ([cloud.md](cloud.md)).

## The IP is blocked

1. `ops.py cloud preflight`.
2. GCP: make sure the current IP is reserved, or accept losing it.
3. `ops.py cloud rotate-ip` → go → execute.
4. Update `PUBLIC_HOST` (and `VPS_SSH` if it's an IP) → `ops.py status` → re-send every user's link.

## Port 443 is throttled

`ops.py cloud firewall-open 8443` adds a firewall rule. Adding a second
inbound on 8443 is a panel change that this skill doesn't automate: run the setup
skill's `configure-inbounds.py --vless-port 8443`, then set `INBOUND_ID` in the
env file (there are two Reality inbounds now) and send the new links.

## SSH dead, VPN dead

`ops.py cloud restart` (GCP: hard reset). Then `ops.py status`.
