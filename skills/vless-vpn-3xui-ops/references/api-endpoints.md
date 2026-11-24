# 3x-ui v3.11.0 endpoints used by this skill

Source: [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui) tag **v3.11.0**
(commit `c621ba9`). Read on 24 November 2026 from
`internal/web/controller/*.go`, `internal/web/service/*.go`, `main.go`, and
`docs/public/openapi.json`. Every path is served under the panel **web base
path**, e.g. `http://127.0.0.1:2053/<webBasePath>/panel/api/clients/list`.

"Source-verified" means the route, verb, and body shape were read from that
tag. **None of it has been run against a live v3.11.0 panel by this skill.**
The offline tests use a mock (`tests/mock_panel.py`) built from the same
reading, so they prove the scripts are self-consistent, not that the panel
agrees.

## Auth

| What | Detail | Where |
|---|---|---|
| `GET /csrf-token` | Creates the session cookie (`3x-ui`) and returns the token in `obj` | `controller/index.go:46` |
| `POST /login` | JSON `{username,password[,twoFactorCode]}`. **CSRF-protected**: send `X-CSRF-Token` from `/csrf-token` first, or you get 403 | `controller/index.go:50` |
| Cookie writes | Every unsafe call with a cookie needs `X-CSRF-Token` | `middleware/security.go` |
| `Authorization: Bearer <token>` | Skips CSRF. Scopes: `admin`, `monitor`, `node-sync`, `node-admin` | `controller/api.go:75-162` |
| `monitor` scope | GET only: `server/status`, `getXrayVersion`, `getPanelUpdateInfo`, history endpoints. Anything else returns 403 | `controller/api.go` |

The setup skill's `xui_api.py` before 24 Nov 2026 posted `/login` without
CSRF; that would be refused on v3.11.0. It is fixed in both copies.

## Clients (`/panel/api/clients`, `controller/client.go:54-84`)

| Verb | Path | Body / notes | Used by |
|---|---|---|---|
| GET | `/list` | Records with `uuid` (not `id`), `inboundIds`, `traffic{up,down}` | `users list`, `status` |
| GET | `/get/{email}` | `{client, inboundIds}` | every per-user op |
| GET | `/traffic/{email}` | usage | (not used) |
| GET | `/links/{email}` | share links; host = request `Host` (127.0.0.1 through a tunnel), so the skill builds links itself | (not used) |
| POST | `/add` | `{client:{email,id,flow,totalGB,expiryTime,limitIp,limitHwid,tgId,subId,comment,enable}, inboundIds:[..]}` | `users add`, rollback |
| POST | `/update/{email}` | **Replaces the row.** Send the full client including `id`=uuid, or the UUID is lost | `users set`, rollback |
| POST | `/del/{email}[?keepTraffic=1]` | removes from every inbound | `users remove` |
| POST | `/bulkEnable`, `/bulkDisable` | `{emails:[..]}` | `users enable/disable` |
| POST | `/resetTraffic/{email}` | zeroes counters **and re-enables a disabled client** (`service/client_traffic.go` ResetTraffic) | `users reset-traffic` |

Units: `totalGB` is **bytes** despite the name (openapi example
`53687091200` = 50 GiB); `0` = unlimited. `expiryTime` is epoch **ms**; `0` =
never; negative = "N days after first use".

## Inbounds (`/panel/api/inbounds`)

| Verb | Path | Notes |
|---|---|---|
| GET | `/list` | `settings`, `streamSettings`, `sniffing` are JSON **strings** |
| GET | `/get/{id}` | one inbound |
| POST | `/update/{id}` | full inbound; strings or objects accepted. `settings.clients` and `enable` are **ignored** here (clients are managed via `/clients`) |

## Xray template (`/panel/api/xray`, `controller/xray_setting.go:45-59`)

| Verb | Path | Notes |
|---|---|---|
| POST | `/` | Returns `obj` as a JSON **string** of `{xraySetting:<object>, inboundTags, ...}`. Parse twice |
| POST | `/update` | form field `xraySetting` (full template JSON). Restarts Xray itself if it is running |
| POST | `/routeTest` | form `domain`/`ip`/`port`/`network`/`inboundTag` -> `{matched,outboundTag}`. Empty tag = first outbound. Needs a running core |
| POST | `/testOutbound` | (not used) |

## Server (`/panel/api/server`, `controller/server.go:47-84`)

| Verb | Path | Notes | Used by |
|---|---|---|---|
| GET | `/status` | `obj.xray.{state,errorMsg,version}`, cpu, mem... | `status`, `upgrade` |
| GET | `/getConfigJson` | the config Xray is actually running | `drift` |
| GET | `/getDb` | binary `x-ui.db` attachment | `backup pull`, before restore/upgrade |
| POST | `/importDB` | multipart field `db`, plus `keepHostSettings` (default true). Panel restarts after | `backup restore` |
| GET | `/getNewX25519Cert` | `obj.privateKey`, `obj.publicKey` | `rotate --keys` |
| POST | `/scanRealityTarget` | form `target`, `sni` | `rotate --sni` |
| POST | `/restartXrayService` | | (setup skill) |
| GET | `/getPanelUpdateInfo` | latest release info | (informational) |
| POST | `/updatePanel` | updates to **latest only**, so it can't be pinned. **Not used** | — |

`POST /panel/api/setting/restartPanel` exists too (not used).

## CLI on the VPS (`main.go`, `x-ui.sh`)

| Command | Notes |
|---|---|
| `x-ui -v` | version |
| `/usr/local/x-ui/x-ui setting -getListen true` | prints `listenIP: X` (`main.go` GetListenIP) |
| `/usr/local/x-ui/x-ui setting -listenIP 127.0.0.1` | bind panel to localhost; `0.0.0.0` reverts (as x-ui's own menu does) |
| `x-ui restart` | restart panel + Xray |
| `x-ui setting -show` | **avoid**: prints the username/password |

Paths: binary `/usr/local/x-ui/x-ui`, DB `/etc/x-ui/x-ui.db`.

Pinned upgrade: `https://raw.githubusercontent.com/MHSanaei/3x-ui/<tag>/update.sh`
run with `XUI_UPDATE_TAG=<tag>`; it checks the release `.sha256` sidecar.

## Not verified (say so to the user)

1. **No live panel run.** Every call above is source-read and mock-tested only.
2. **`update.sh` without prompts.** `XUI_NONINTERACTIVE=1` is read by
   `install.sh`; whether `update.sh` honours it everywhere was not checked
   line by line on a real host. Run upgrades in an SSH session you watch.
3. **`routeTest`** needs a running core; on a stopped core it may error.
4. **403 vs 404 semantics.** Unauthenticated API calls 404 and wrong-scope
   tokens 403 in the source; a reverse proxy in front can change that.
5. **Provider probe interpretation** (`routing probe`): 401/403/451 bodies
   differ per provider; the classifier is a heuristic.
6. **Reality camouflage check** compares a plain TLS handshake to the donor
   site. It catches gross misconfiguration, not every fingerprint.
