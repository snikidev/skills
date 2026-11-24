# Transport matrix: what goes over the API, what over SSH, and why

Rule one: **never hand-edit `/usr/local/x-ui/bin/config.json` or
`/etc/x-ui/x-ui.db`.** 3x-ui regenerates `config.json` from the database on
every Xray restart, so edits vanish; editing the SQLite file under a running
panel can corrupt it or be overwritten. Change state through the panel API
(which validates and restarts Xray itself) or, for the few settings the API
can't reach, the `x-ui` CLI.

| Operation | Transport | Endpoint / command | Credential | Mode |
|---|---|---|---|---|
| Tunnel check | local HTTP | `GET <base>/csrf-token` on 127.0.0.1 | none | local |
| Tunnel open/close | SSH | `ssh -f -N -M -S <sock> -L 127.0.0.1:L:127.0.0.1:R` | SSH key (`VPS_SSH`, `VPS_SSH_KEY` or `~/.ssh/config`) | local change only |
| Panel listen address | SSH | `x-ui setting -getListen true` | SSH + passwordless sudo | RO |
| Rebind panel to localhost | SSH | `x-ui setting -listenIP 127.0.0.1 && x-ui restart` | SSH + sudo | WRITE |
| Service snapshot | SSH | `sh -s < remote-status.sh` | SSH | RO |
| Xray state | API | `GET /panel/api/server/status` | monitor or admin token | RO |
| Users | API | `/panel/api/clients/*` | admin token or cookie+CSRF | RO/WRITE |
| Links / QR | local | built from inbound Reality params + `PUBLIC_HOST` | (API read first) | RO |
| Routing | API | `POST /panel/api/xray/` then `/xray/update` | admin | RO/WRITE |
| Route decision | API | `POST /panel/api/xray/routeTest` | admin | RO |
| Egress / provider probe | SSH | `curl -K -` on the VPS, config on stdin | SSH; proxy creds read from the template and put only in curl's stdin | RO |
| Reality camouflage | local TLS | `openssl s_client -connect PUBLIC_HOST:443 -servername SNI` | none | RO |
| Backup | API | `GET /panel/api/server/getDb` | admin | RO (writes a local file) |
| Restore | API | `POST /panel/api/server/importDB` | admin | WRITE |
| Upgrade | SSH | `curl -fsSL -o /tmp/x-ui-update-<tag>.sh <tag>/update.sh && sudo -n env XUI_UPDATE_TAG=<tag> XUI_NONINTERACTIVE=1 bash /tmp/x-ui-update-<tag>.sh` | SSH + sudo | WRITE |
| Rotate Reality | API | `getNewX25519Cert`, `scanRealityTarget`, `inbounds/update/{id}` | admin | WRITE |
| Drift | API | `POST /xray/`, `GET /server/getConfigJson` | admin | RO |

Why the API over the tunnel rather than SSH + `sqlite3`: the API is the
supported surface, it validates input, it restarts Xray in the right order,
and the panel never has to listen on a public interface.

Why SSH for some reads: the panel can't report its own systemd state, listen
address, or what the VPS's IP looks like from outside. Those come from the
host.

Why `curl -K -`: arguments on a command line are visible in `ps` to every
user on the VPS and end up in shell history. A curl config read from stdin is
not.

`sudo -n` (non-interactive) is used on purpose: if sudo needs a password the
command fails instead of hanging or asking the agent for it. The skill never
handles a sudo password. Run that step yourself in your own SSH session if you
don't have passwordless sudo.
