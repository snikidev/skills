# 3x-ui API notes and unverified items

This skill talks to the panel over HTTP rather than clicking the web UI, so
the steps are repeatable. Endpoints below were read from the official docs
and from `frontend/src/pages/api-docs/endpoints.ts` in
[MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui) **v3.11.0** on 23 November
2026. They have **not** been executed against a live panel in this
repository.

## Verified from source / official docs (not live-tested)

| Method | Path | Role |
| --- | --- | --- |
| `POST` | `/login` | Session cookie auth (`username`, `password`, optional `twoFactorCode`). CSRF-protected: `GET /csrf-token` first |
| `GET` | `/csrf-token` | CSRF token for cookie sessions. Bearer callers can skip CSRF. |
| `GET` | `/panel/api/inbounds/list` | List inbounds |
| `POST` | `/panel/api/inbounds/add` | Create an inbound. `settings`, `streamSettings`, and `sniffing` may be nested JSON objects. |
| `GET` | `/panel/api/inbounds/allLinks` | Share links (this skill uses `vless://`). Host follows the request `Host` header unless a trusted proxy is configured. |
| `POST` | `/panel/api/xray/` | Read the Xray template. `obj` is a JSON **string** of `{xraySetting, inboundTags, ...}` (parse it, then read `xraySetting`). |
| `POST` | `/panel/api/xray/update` | Form fields: `xraySetting` (required), `outboundTestUrl` (optional). |
| `POST` | `/panel/api/server/restartXrayService` | Reload Xray |
| `GET` | `/panel/api/server/getNewX25519Cert` | Reality keypair: `obj.privateKey`, `obj.publicKey` |
| `GET` | `/panel/api/xray/getXrayResult` | Recent Xray stdout/stderr |
| Bearer | `Authorization: Bearer <token>` | Token from Settings → Security → API Token, also written to `/etc/x-ui/install-result.env` as `XUI_API_TOKEN` by the official installer |

All of the above are served under the panel **web base path**, for example
`http://127.0.0.1:2053/<webBasePath>/panel/api/inbounds/add`.

VLESS Reality inbound JSON follows the v3.11.0 golden fixture
`frontend/src/test/golden/fixtures/inbound-full/vless-tcp-reality.json`. The
panel writes Reality's donor as `target` (`dest` is accepted as an alias).
`mldsa65Seed`, `mldsa65Verify`, `minClientVer`, and `maxClientVer` are left
empty so current clients can handshake.

SOCKS outbounds use Xray's `settings.servers[].users[]` shape (see
`frontend/src/schemas/protocols/outbound/socks.ts`).

The default Xray template lives at `internal/web/service/config.json` in
v3.11.0: `direct` (freedom) first, then `blocked` (blackhole); routing sends
`api` → `api`, `geoip:private` → `blocked`, `bittorrent` → `blocked`. From
v3.6 onward the `direct` outbound also has `finalRules` that block
`geoip:private` (SSRF hardening). This skill rewrites that when it inserts
the `iproyal` outbound, so a `geoip:private` → `direct` rule actually works.

## Client fixes (24 November 2026, re-read against v3.11.0 controllers + `docs/public/openapi.json`)

- **`POST /login` is CSRF-protected** (`controller/index.go`: `middleware.CSRFMiddleware`).
  `xui_api.py` now calls `GET /csrf-token` first (it sets the session cookie)
  and sends `X-CSRF-Token` on `/login` and on every later POST. Before the
  fix, cookie login would have got 403. Bearer-token callers were unaffected.
- **`POST /panel/api/xray/` returns `obj` as a JSON string** of
  `{xraySetting, inboundTags, ...}`. `get_xray_template()` now parses it
  before reading `xraySetting`.
- **Clients have their own API** under `/panel/api/clients/` (`list`,
  `get/{email}`, `add`, `update/{email}`, `del/{email}`, `bulkEnable`,
  `bulkDisable`, `resetTraffic/{email}`). `update` replaces the whole row. The
  ops skill uses these; see
  [../../vless-vpn-3xui-ops/references/api-endpoints.md](../../vless-vpn-3xui-ops/references/api-endpoints.md).

## Installer (official script, pinned)

- Script is downloaded from the **tag**, not `master`:
  `https://raw.githubusercontent.com/MHSanaei/3x-ui/v3.11.0/install.sh`
- Then run as `XUI_NONINTERACTIVE=1 bash install.sh v3.11.0`
- Never `sudo bash <(curl ...)` — process substitution does not survive sudo
  (documented in [the sniki.dev guide](https://www.sniki.dev/posts/vless-vpn-gcp-setup/)).
- The official installer verifies the release archive against the published
  `.sha256` sidecar.
- Default pin: **v3.11.0** (25 October 2026), bundles **Xray-core v26.10.21**.
- This is the systemd install, not the Docker Compose flow used in that
  guide (which pinned `ghcr.io/mhsanaei/3x-ui:v2.9.4`).

## Unverified / not end-to-end tested

Be honest with the user about these:

1. **No live run** of "create VM → install 3x-ui v3.11.0 → API add inbounds →
   add SOCKS outbound → verify egress through a real IPRoyal proxy" has been
   performed for this repository.
2. **`POST /panel/api/xray/` response wrapping.** Source says `obj` is a JSON
   string wrapping `xraySetting` (handled since 24 Nov 2026). `scripts/xui_api.py` also accepts a parsed
   object and a nested `xraySetting` wrapper, but a live panel might return a
   slightly different envelope. If `update` fails, inspect the raw response
   before merging.
3. **`/panel/api/inbounds/add` return value.** The `id` of the new inbound is
   read from `obj.id` when present; some versions may return a different
   shape. Idempotency uses a subsequent `list` (protocol + port) as the
   source of truth on reruns.
4. **Azure Debian 12 URN** `Debian:debian-12:12-gen2:latest` may move or be
   renamed. Override with `AZURE_IMAGE`. GCP `debian-12` / `debian-cloud` is
   the usual current family.
5. **`www.microsoft.com` as a Reality donor** is a reasonable default (TLS
   1.3, no PQ handshake in the November 2026 sniki.dev notes) but this
   **changes**. Always run `xray tls ping www.microsoft.com` and
   `curl -I https://www.microsoft.com` on the VM before locking the inbound.
   Skip donors that 301/302 or that negotiate post-quantum TLS if clients
   cannot handshake.
6. **IPRoyal pricing and fair-use caps** change. Confirm on the
   provider site at purchase time.
7. **Through-the-tunnel egress** (VLESS client → ipinfo shows the
   proxy IP) cannot be fully proven by `curl --proxy socks5h://...` alone.
   That command only proves the proxy itself. The client checklist in
   `scripts/verify-egress.sh` is the real test and has not been run here.
8. **Panel allLinks Host header** behaviour is documented by 3x-ui and
   matches the export-URL gotcha in the sniki.dev guide, but was not
   re-tested on v3.11.0.

If you run this end to end, please note which of the items above you
confirmed and open a PR or issue on the repo.
