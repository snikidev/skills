# Troubleshooting

| Symptom | Likely cause | Check (read-only first) | Fix |
|---|---|---|---|
| `TUNNEL=DOWN` | no tunnel, wrong local port | `scripts/tunnel.sh check` | `ops.py connect --open`, or the setup skill's `ssh-tunnel-panel.sh` |
| tunnel up, every call 404 | wrong `PANEL_BASE_PATH`, or not logged in (3x-ui hides the API with 404) | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:2053/<path>/csrf-token` should be 200 | fix the path from `install-result.env`; check the token |
| `403` on `/login` | CSRF token missing | client version | use this skill's client (fetches `/csrf-token` first) |
| `403 ... not permitted` | monitor token used for a write | card's Credential line | set `XUI_API_TOKEN` (admin scope) |
| ssh `Permission denied (publickey)` / `Host key verification failed` | BatchMode, key not loaded / unknown host | `ssh -o BatchMode=yes $VPS_SSH true` | `ssh-add`, connect once by hand to accept the host key |
| `panel_listen=needs-sudo` / `sudo: a password is required` | no passwordless sudo | — | run the printed command yourself in an SSH session |
| `panel_listen=0.0.0.0` (or empty) | panel listens on all interfaces | `ops.py connect` | `ops.py rebind-localhost` (dry run first) |
| xray `state=error` after a routing change | bad template | `ops.py status`, panel → Xray logs (`GET /panel/api/xray/getXrayResult`) | `ops.py rollback --snapshot <the snapshot the change printed>` |
| clients connect but nothing loads, no error | stale link after rotate/inbound edit (Reality forwards bad clients to the donor) | `ops.py users link NAME` and compare `pbk`/`sid`/`sni` | re-import the new link |
| user can't connect, others can | disabled, over cap, expired | `ops.py users list` | `users set --cap/--expires`, or `users reset-traffic` |
| `users enable` says still off | exhausted or expired users stay disabled | `users list` | raise cap/expiry first |
| egress via proxy same as direct | proxy outbound not first, or rule sends it `direct` | `ops.py routing list`, `ops.py drift` | setup skill's `add-proxy-outbound.py` |
| egress via proxy fails | proxy down / creds wrong / provider IP blocked | `ops.py status` step 6 | check with the provider; temporary: remove the proxy outbound in the panel UI |
| `openrouter.ai` blocked over the proxy | provider blocks the ISP IP | `ops.py routing probe` | `ops.py routing add domain:openrouter.ai direct` |
| `routeTest` errors | Xray core not running | `status` | fix Xray first |
| camouflage check: certificate mismatch | wrong SNI/target, donor changed | `openssl s_client` line in the card | `ops.py rotate --sni <new donor>` (scans it first) |
| plan id mismatch (exit 3) | state or args changed since the dry run | — | re-run the dry run, show the new card, get a new go |
| upgrade: panel doesn't come back | update.sh failed midway | `ssh $VPS_SSH 'sudo systemctl status x-ui; sudo journalctl -u x-ui -n 50'` | re-run `update.sh` for the OLD tag, then `backup restore` the pre-upgrade backup |

Never "fix" anything by editing `config.json` or `x-ui.db` directly; see
[transport-matrix.md](transport-matrix.md).
