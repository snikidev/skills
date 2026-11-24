# Credentials and the env file

## Where things live

| Thing | Location | Mode | Contains secrets |
|---|---|---|---|
| Ops config | `~/.config/vless-ops/.env` (or `$VLESS_OPS_ENV`) | 600 | yes (tokens, password) |
| Template | `.env.example` in this skill | — | no |
| Panel facts on the VPS | `/etc/x-ui/install-result.env` (written by the setup skill) | 600, root | yes |
| Pre-write snapshots | `$OPS_STATE_DIR/snapshots/*.json` | 600 | user UUIDs, inbound incl. Reality private key |
| Regenerated links | `$OPS_STATE_DIR/links-<ts>.txt` | 600 | user UUIDs |
| DB backups | `$BACKUP_DIR/x-ui-<ts>.db` + `.sha256` | 600 | everything in the panel |
| Tunnel control socket | `$OPS_STATE_DIR/tunnel.sock` | 600 | no |

Process environment beats the file. The file is parsed as `KEY=value` lines
(`export` and quotes allowed); it is never `source`d, so nothing in it runs.
`tunnel.sh` reads only non-secret keys from it.

## Filling it in from the setup skill's output

On the VPS, `sudo cat /etc/x-ui/install-result.env` **in your own terminal**
(not via the agent: it would put the values in the chat). Copy:

| install-result.env | ops `.env` |
|---|---|
| `XUI_PANEL_PORT` | `PANEL_REMOTE_PORT` |
| `XUI_WEB_BASE_PATH` | `PANEL_BASE_PATH` |
| `XUI_API_TOKEN` | `XUI_API_TOKEN` |
| `XUI_USERNAME` / `XUI_PASSWORD` | same names (only if no token) |

`PUBLIC_HOST` is the VM's public IP (what the setup skill's `make-links.sh`
called `PUBLIC_IP`).

## Which credential each command uses

The action card names it, e.g. `Bearer token, admin scope: env XUI_API_TOKEN
from ~/.config/vless-ops/.env`.

- `status`: `XUI_MONITOR_TOKEN` if set (least privilege), otherwise the admin
  token, otherwise the cookie login. Steps that need more than `server/status`
  (users, routeTest, the template for egress) fall back to the admin credential
  and the card says so.
- Every write: `XUI_API_TOKEN`, otherwise `XUI_USERNAME` + `XUI_PASSWORD`
  (cookie session, `GET /csrf-token` first, `X-CSRF-Token` on every POST).
- SSH steps: your SSH key via `VPS_SSH` / `VPS_SSH_KEY` / `~/.ssh/config`.
  `BatchMode=yes`, so a passphrase prompt or unknown host key fails instead of
  waiting. Load the key into `ssh-agent` yourself.
- `sudo` on the VPS: `sudo -n` only. If it needs a password the step fails and
  you run it yourself.
- Proxy (SOCKS) user/password: never configured here. They are read from the
  live Xray template only when a probe needs them, and passed to curl on the
  VPS inside a stdin config. Diffs and exports mask them as `***`.

## Rules for the agent

1. Never print a secret value: not in cards, results, diffs, logs or chat.
   Refer to it by NAME and source.
2. Never `cat` the env file, `install-result.env`, a snapshot or a backup into
   the chat. If the user needs a value, tell them the file and let them open it.
3. Never run `x-ui setting -show` (prints the admin password).
4. Don't ask the user to paste a token into the chat. Ask them to put it in
   the env file and say "done".
5. If a secret was exposed anyway, say so plainly and suggest rotating it:
   new API token in Settings → Security, new panel password, or
   `ops.py rotate --keys` for the Reality key.
6. Links (`vless://...`) are credentials too: print one only when the user
   asked for that user's link.

## Rotating the panel credentials themselves

Not automated (the endpoints exist but a mistake locks you out). In the panel
UI over the tunnel: Settings → Security → regenerate the API token, then
update `XUI_API_TOKEN` in the env file and run `ops.py status`.
