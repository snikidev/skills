"""All operations. Each one prints an action card BEFORE doing anything,
then a RESULT line after. Writes are dry runs unless --execute --plan <id>."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import cloud, remote, routing, users
from .api import OpsClient, XUIError
from .card import LOCAL, RO, WRITE, Card, gate, result, show
from .env import Config, redact

API_TRANSPORT = "panel HTTP API via SSH tunnel -> 127.0.0.1 on the VPS ({url})"
SSH_TRANSPORT = "SSH command on the VPS ({target})"

DEFAULT_PROVIDERS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "xai": "https://api.x.ai/v1/models",
}


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp() -> str:
    return now_utc().strftime("%Y%m%dT%H%M%SZ")


def api_t(cfg: Config) -> str:
    return API_TRANSPORT.format(url=cfg.panel_base_url())


def ssh_t(cfg: Config) -> str:
    return SSH_TRANSPORT.format(target=cfg.ssh_description())


def client(cfg: Config, write: bool) -> OpsClient:
    try:
        return OpsClient.from_config(cfg, write=write)
    except XUIError as exc:
        raise SystemExit(
            f"ERROR: panel API not reachable or login failed: {redact(str(exc), cfg)}\n"
            "Is the tunnel up? Run: ops.py connect"
        ) from exc


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def snapshot(cfg: Config, kind: str, data: Any, meta: Optional[dict] = None) -> Path:
    p = cfg.state_dir() / "snapshots" / f"{stamp()}-{kind}.json"
    blob = {"kind": kind, "created": now_utc().isoformat(), "meta": meta or {}, "data": data}
    write_private(p, json.dumps(blob, indent=2).encode())
    return p


def pick_inbound(api: OpsClient, cfg: Config) -> dict[str, Any]:
    want = cfg.get("INBOUND_ID")
    ibs = api.inbounds()
    if want:
        for ib in ibs:
            if str(ib.get("id")) == str(want):
                return ib
        raise SystemExit(f"ERROR: INBOUND_ID={want} not found; have {[i.get('id') for i in ibs]}")
    reality = [i for i in ibs if i.get("protocol") == "vless"
               and (i.get("streamSettings") or {}).get("security") == "reality"]
    if len(reality) != 1:
        raise SystemExit(
            f"ERROR: found {len(reality)} VLESS Reality inbounds; set INBOUND_ID in the env file."
        )
    return reality[0]


def get_template(api: OpsClient) -> dict[str, Any]:
    return api.get_xray_template()


def iproyal_proxy(template: dict[str, Any], tag: str) -> Optional[dict[str, Any]]:
    for ob in template.get("outbounds", []):
        if ob.get("tag") == tag and ob.get("protocol") == "socks":
            srv = ((ob.get("settings") or {}).get("servers") or [{}])[0]
            u = (srv.get("users") or [{}])[0]
            return {"address": srv.get("address"), "port": srv.get("port"),
                    "user": u.get("user", ""), "pass": u.get("pass", "")}
    return None


def public_host(cfg: Config) -> str:
    return cfg.require("PUBLIC_HOST")


# --------------------------------------------------------------------------
# connect
# --------------------------------------------------------------------------
def tunnel_up(cfg: Config) -> tuple[bool, str]:
    url = cfg.panel_base_url() + "/csrf-token"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200, f"HTTP {r.status} from {url}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url} (wrong PANEL_BASE_PATH?)"
    except (urllib.error.URLError, OSError) as exc:
        return False, f"nothing answered at {url} ({exc})"


def cmd_connect(cfg: Config, args) -> int:
    steps = ["check local tunnel", "open tunnel if down" if args.open else "(open skipped: add --open)",
             "read panel listen address over SSH"]
    show(Card("Check SSH tunnel to the panel", "Every API call goes through this tunnel; the panel should never be public.",
              "local HTTP to 127.0.0.1 (no credentials)", f"GET {cfg.panel_base_url()}/csrf-token",
              "none", LOCAL, step="1/3", remaining=steps[1:]))
    up, why = tunnel_up(cfg)
    result(up, f"tunnel {'UP' if up else 'DOWN'}: {why}")
    if not up and args.open:
        cmd = (f"ssh -f -N -L 127.0.0.1:{cfg.get('PANEL_LOCAL_PORT')}:127.0.0.1:"
               f"{cfg.get('PANEL_REMOTE_PORT') or '<PANEL_REMOTE_PORT>'} {cfg.get('VPS_SSH') or '<VPS_SSH>'}")
        show(Card("Open SSH tunnel", "Forward a local port to the panel, which listens on the VPS only.",
                  "SSH port forward (no change on the server)", cmd, cfg.ssh_description(), LOCAL,
                  "scripts/tunnel.sh close", step="2/3", remaining=steps[2:]))
        rc = subprocess.run(["sh", str(remote.SCRIPTS / "tunnel.sh"), "open"]).returncode
        up, why = tunnel_up(cfg)
        result(up, why)
        if rc != 0 or not up:
            return 1
    show(Card("Read panel listen address", "If the panel listens on 0.0.0.0 it is exposed to the internet "
              "(only the cloud firewall protects it).", ssh_t(cfg),
              "ssh <VPS_SSH> 'sh -s' < scripts/remote-status.sh  (uses sudo -n for `x-ui setting -getListen`)",
              cfg.ssh_description(), RO, step="3/3"))
    proc = remote.run_script(cfg, "remote-status.sh")
    kv = remote.parse_kv(proc.stdout.decode(errors="replace"))
    listen = kv.get("panel_listen", "?")
    ok = listen in ("127.0.0.1", "localhost", "::1")
    result(proc.returncode == 0, f"panel_listen={listen or '(empty = all interfaces)'}")
    if not ok:
        print("RECOMMENDATION: bind the panel to 127.0.0.1 so only the tunnel can reach it:")
        print("  ops.py rebind-localhost            (dry run, prints the card)")
    return 0 if up else 1


def cmd_rebind(cfg: Config, args) -> int:
    up, why = tunnel_up(cfg)
    remote_cmd = "sudo -n /usr/local/x-ui/x-ui setting -listenIP 127.0.0.1 && sudo -n x-ui restart"
    plan = {"op": "rebind-localhost", "cmd": remote_cmd}
    show(Card("Bind the panel to 127.0.0.1", "Removes the panel from the public interface. After this the panel "
              "is reachable ONLY through the SSH tunnel.", ssh_t(cfg), remote.show_cmd(cfg, remote_cmd),
              cfg.ssh_description() + " (needs passwordless sudo)", WRITE,
              "ssh <VPS_SSH> 'sudo x-ui setting -listenIP 0.0.0.0 && sudo x-ui restart'  (this is what "
              "x-ui's own menu does to clear it)",
              changes=["panel listenIP: <current> -> 127.0.0.1", "x-ui restarts (VPN users drop for a few seconds)"]))
    if not up:
        print("PRECONDITION FAILED: the tunnel is not up. Prove the tunnel works BEFORE locking the panel to it.")
        return 1
    if not gate(plan, args.execute, args.plan):
        return 0
    proc = remote.run(cfg, remote_cmd)
    time.sleep(int(os.environ.get("VLESS_OPS_WAIT", "8")))
    up2, why2 = tunnel_up(cfg)
    result(proc.returncode == 0 and up2, f"rebind exit={proc.returncode}; tunnel after restart: {why2}",
           [proc.stderr.decode(errors="replace").strip()[:300]] if proc.returncode else None)
    return 0 if proc.returncode == 0 and up2 else 1


# --------------------------------------------------------------------------
# status / health
# --------------------------------------------------------------------------
def reality_camouflage(host: str, port: int, sni: str) -> tuple[bool, str]:
    """Without a client key, a Reality server must look exactly like the donor:
    the TLS handshake with SNI=<sni> should present the donor's certificate."""
    if not shutil.which("openssl"):
        return False, "openssl not installed locally (skipped)"
    try:
        proc = subprocess.run(
            ["openssl", "s_client", "-connect", f"{host}:{port}", "-servername", sni, "-brief"],
            input=b"", capture_output=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return False, "TLS handshake timed out"
    out = (proc.stdout + proc.stderr).decode(errors="replace")
    proto = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("Protocol version")), "?")
    subj = next((ln.split(":", 1)[1].strip() for ln in out.splitlines() if "Peer certificate" in ln), "?")
    ok = "TLSv1.3" in proto and sni.split(".")[-2] in subj.lower() if subj != "?" else False
    return ok, f"protocol={proto} peer_cert={subj}"


def egress_check(cfg: Config, proxy: Optional[dict]) -> list[str]:
    lines = []
    url = "https://api.ipify.org"
    for label, px in (("direct (VPS IP)", None), (f"via {cfg.get('PROXY_TAG')}", proxy)):
        if label.startswith("via") and not px:
            lines.append(f"{label}: no SOCKS outbound with that tag in the template")
            continue
        proc = remote.run(cfg, "curl -K -", stdin=remote.curl_body_config(url, px, 15), timeout=40)
        ip = proc.stdout.decode(errors="replace").strip() or f"FAILED ({proc.stderr.decode(errors='replace').strip()[:120]})"
        lines.append(f"{label}: {ip}")
    return lines


def cmd_status(cfg: Config, args) -> int:
    steps = [
        "tunnel check (local)", "service snapshot (SSH, read-only)", "panel + Xray status (API)",
        "per-user traffic (API)", "Reality camouflage check (local TLS)",
        "egress IP direct vs proxy (SSH)", "routing decisions for key domains (API)",
    ]
    failures = 0

    def step(i: int, card: Card) -> None:
        card.step = f"{i}/{len(steps)}"
        card.remaining = steps[i:]
        show(card)

    step(1, Card("Tunnel check", "API calls need it.", "local HTTP (no credentials)",
                 f"GET {cfg.panel_base_url()}/csrf-token", "none", LOCAL))
    up, why = tunnel_up(cfg)
    result(up, why)
    if not up:
        print("Stopping: open the tunnel first (ops.py connect --open).")
        return 1

    step(2, Card("Service snapshot", "Is x-ui active, Xray running, which version, what listens.", ssh_t(cfg),
                 "ssh <VPS_SSH> 'sh -s' < scripts/remote-status.sh", cfg.ssh_description(), RO))
    proc = remote.run_script(cfg, "remote-status.sh")
    kv = remote.parse_kv(proc.stdout.decode(errors="replace"))
    good = kv.get("xui_service") == "active" and kv.get("xray_process") == "running"
    failures += 0 if good else 1
    result(good, f"x-ui={kv.get('xui_service')} xray={kv.get('xray_process')} version={kv.get('xui_version')}",
           [f"{k}={v}" for k, v in kv.items() if k not in ("xui_service", "xray_process", "xui_version")])
    pin = cfg.get("XUI_VERSION")
    if pin and kv.get("xui_version") and pin.lstrip("v") not in kv.get("xui_version", ""):
        print(f"  NOTE: installed {kv.get('xui_version')} differs from pin {pin} (see ops.py upgrade).")

    api = client(cfg, write=False)
    step(3, Card("Panel and Xray status", "Xray state and version as the panel sees them.", api_t(cfg),
                 "GET /panel/api/server/status", cfg.api_credential(False), RO))
    st = api.server_status()
    xr = st.get("xray") or {}
    ok = xr.get("state") == "running"
    failures += 0 if ok else 1
    result(ok, f"xray state={xr.get('state')} version={xr.get('version')} cpu={st.get('cpu')}%",
           [f"error: {xr.get('errorMsg')}"] if xr.get("errorMsg") else None)

    step(4, Card("Per-user traffic", "Usage against caps and expiry.", api_t(cfg),
                 "GET /panel/api/clients/list", cfg.api_credential(True), RO))
    try:
        wapi = client(cfg, write=True)
        rows = [users.client_row(e) for e in wapi.clients()]
        print(users.table(rows))
        result(True, f"{len(rows)} users")
    except (XUIError, SystemExit) as exc:
        failures += 1
        result(False, f"could not list users: {redact(str(exc), cfg)}")
        wapi = None

    step(5, Card("Reality camouflage check", "Without a client key the server must look exactly like the donor "
                 "site (same TLS 1.3 certificate). A mismatch means probes can fingerprint it.",
                 "local TLS handshake to the VPS (no credentials)",
                 f"openssl s_client -connect {cfg.get('PUBLIC_HOST') or '<PUBLIC_HOST>'}:{cfg.get('VLESS_PORT')} -servername <inbound SNI>",
                 "none", LOCAL))
    if wapi and cfg.get("PUBLIC_HOST"):
        ib = pick_inbound(wapi, cfg)
        p = users.reality_params(ib)
        ok, msg = reality_camouflage(cfg.get("PUBLIC_HOST"), int(ib.get("port") or 443), p["sni"])
        result(ok, f"SNI {p['sni']}: {msg}")
        print("  Full handshake proof = connect a client with a user's link (ops.py users link NAME) "
              "and open https://ipinfo.io.")
    else:
        result(False, "skipped (needs PUBLIC_HOST and the user list)")

    step(6, Card("Egress IP: direct vs proxy", "Shows the IP sites see without and with the SOCKS outbound.",
                 ssh_t(cfg), "ssh <VPS_SSH> 'curl -K -'  (curl config on stdin, target https://api.ipify.org)",
                 f"{cfg.ssh_description()}; proxy credentials read from the live Xray template "
                 f"(POST /panel/api/xray/, {cfg.api_credential(True)}) and sent only inside curl's stdin config", RO))
    proxy = None
    if wapi:
        try:
            proxy = iproyal_proxy(get_template(wapi), cfg.get("PROXY_TAG"))
        except XUIError as exc:
            print(f"  could not read template: {redact(str(exc), cfg)}")
    lines = egress_check(cfg, proxy)
    same = len(lines) == 2 and lines[0].split(": ")[-1] == lines[1].split(": ")[-1]
    result(not same and not any("FAILED" in ln for ln in lines), "egress", lines)

    step(7, Card("Routing decisions", "Which outbound Xray's router picks for key domains (no traffic sent).",
                 api_t(cfg), "POST /panel/api/xray/routeTest (domain=..., port=443)", cfg.api_credential(True), RO))
    if wapi:
        for d in args.domains or ["openrouter.ai", "example.com"]:
            try:
                r = wapi.route_test(d)
                tag = r.get("outboundTag") or "(no rule matched -> default/first outbound)"
                print(f"  {d:<24} -> {tag}")
            except XUIError as exc:
                print(f"  {d:<24} -> error {redact(str(exc), cfg)}")
        result(True, "routing decisions listed")
    print(f"\nSUMMARY: {'healthy' if failures == 0 else f'{failures} problem(s) - see FAILED results above'}")
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------
def print_link(cfg: Config, link: str, qr: bool) -> None:
    print("\nvless:// link (treat like a password; anyone with it can use the VPN):")
    print(link)
    if qr:
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ANSIUTF8", link])
        else:
            print("(qrencode not installed: brew install qrencode / apt install qrencode)")


def find_record(api: OpsClient, email: str) -> dict[str, Any]:
    try:
        obj = api.client(email)
    except XUIError as exc:
        raise SystemExit(f"ERROR: user {email!r} not found: {exc}") from exc
    rec = obj.get("client") or {}
    if not rec:
        raise SystemExit(f"ERROR: user {email!r} not found")
    return {"record": rec, "inboundIds": obj.get("inboundIds") or []}


def cmd_users(cfg: Config, args) -> int:
    action = args.action
    if action == "list":
        show(Card("List users", "Usage, caps, expiry, enabled flag.", api_t(cfg),
                  "GET /panel/api/clients/list", cfg.api_credential(True), RO))
        api = client(cfg, write=True)
        rows = [users.client_row(e) for e in api.clients()]
        print(users.table(rows))
        result(True, f"{len(rows)} users")
        return 0

    email = users.valid_email(args.name)
    api = client(cfg, write=True)

    if action == "link":
        show(Card(f"Show link for {email}", "Rebuild the share link from the inbound's Reality settings and the "
                  "user's UUID (not from allLinks, which uses the tunnel's 127.0.0.1 as host).", api_t(cfg),
                  "GET /panel/api/clients/get/{email}, GET /panel/api/inbounds/list",
                  f"{cfg.api_credential(True)}; host from {cfg.source('PUBLIC_HOST')}", RO))
        found = find_record(api, email)
        ib = pick_inbound(api, cfg)
        rec = found["record"]
        link = users.vless_link(ib, rec.get("uuid") or rec.get("id"), rec.get("flow", ""),
                                public_host(cfg), email)
        print_link(cfg, link, args.qr)
        result(True, "link printed (not saved anywhere)")
        return 0

    if action == "add":
        ib = pick_inbound(api, cfg)
        cap = users.parse_cap(args.cap)
        exp = users.parse_expiry(args.expires)
        flow = args.flow if args.flow is not None else "xtls-rprx-vision"
        existing = {users.client_row(e)["email"] for e in api.clients()}
        if email in existing:
            print(f"User {email} already exists (no change). Use `users set` to change caps/expiry.")
            return 0
        # relative expiry ("30d") is planned by its text, so a dry run and a later execute match
        plan = {"op": "users.add", "email": email, "cap": cap, "expires": args.expires or "0", "flow": flow,
                "inbound": ib.get("id"), "comment": args.comment or ""}
        show(Card(f"Add user {email}", "Create a VPN user with its own UUID, cap and expiry.", api_t(cfg),
                  "POST /panel/api/clients/add  {client:{email,id(uuid),flow,totalGB,expiryTime,...}, inboundIds}",
                  cfg.api_credential(True), WRITE, f"ops.py users remove {email}",
                  changes=[f"inbound {ib.get('id')} ({ib.get('remark')}): + {email}",
                           f"cap {users.fmt_bytes(cap) if cap else 'unlimited'}, expires {users.fmt_expiry(exp)}, flow {flow or '(none)'}",
                           "UUID generated at execute time; link printed afterwards"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        body = users.new_client(email, cap, exp, flow, comment=args.comment or "")
        api.client_add(body, [int(ib["id"])])
        rec = find_record(api, email)["record"]
        ok = (rec.get("uuid") or rec.get("id")) == body["id"]
        result(ok, f"user {email} created" + ("" if ok else " (UUID differs from requested; using panel's)"))
        link = users.vless_link(ib, rec.get("uuid") or body["id"], flow, public_host(cfg), email)
        print_link(cfg, link, args.qr)
        return 0

    found = find_record(api, email)
    rec = found["record"]

    if action in ("disable", "enable"):
        enable = action == "enable"
        if bool(rec.get("enable", True)) == enable:
            print(f"{email} is already {'enabled' if enable else 'disabled'} (no change).")
            return 0
        plan = {"op": f"users.{action}", "email": email}
        show(Card(f"{action.title()} user {email}", "Toggle access without deleting the user or its link.",
                  api_t(cfg), f"POST /panel/api/clients/bulk{action.title()}  {{emails:[{email}]}}",
                  cfg.api_credential(True), WRITE,
                  f"ops.py users {'disable' if enable else 'enable'} {email}",
                  changes=[f"{email}: enable {not enable} -> {enable}"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        api.clients_set_enable([email], enable)
        now = find_record(api, email)["record"]
        ok = bool(now.get("enable")) == enable
        result(ok, f"{email} enable={now.get('enable')}")
        if enable and not ok:
            print("  An exhausted or expired user stays off: raise the cap/expiry (users set) or reset traffic.")
        return 0 if ok else 1

    if action == "remove":
        plan = {"op": "users.remove", "email": email, "uuid": rec.get("uuid"), "keep": args.keep_traffic}
        show(Card(f"Remove user {email}", "Delete the user from every inbound. Their link stops working.",
                  api_t(cfg), f"POST /panel/api/clients/del/{email}{'?keepTraffic=1' if args.keep_traffic else ''}",
                  cfg.api_credential(True), WRITE,
                  "a snapshot of the user (incl. UUID) is saved first; `ops.py rollback --snapshot <file>` "
                  "re-creates it with the SAME UUID, so the old link works again (traffic counters are lost "
                  "unless --keep-traffic)",
                  changes=[f"- {email} (inbounds {found['inboundIds']})"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        snap = snapshot(cfg, "client", found, {"email": email})
        print(f"Snapshot saved: {snap} (mode 600, contains the user's UUID)")
        api.client_delete(email, args.keep_traffic)
        gone = email not in {users.client_row(e)["email"] for e in api.clients()}
        result(gone, f"{email} {'removed' if gone else 'STILL PRESENT'}", [f"rollback: ops.py rollback --snapshot {snap}"])
        return 0 if gone else 1

    if action == "set":
        body = users.record_to_update_body(rec)
        changes = []
        if args.cap is not None:
            body["totalGB"] = users.parse_cap(args.cap)
            changes.append(f"cap {users.fmt_cap(rec.get('totalGB'))} -> {users.fmt_cap(body['totalGB'])}")
        if args.expires is not None:
            body["expiryTime"] = users.parse_expiry(args.expires)
            changes.append(f"expiry {users.fmt_expiry(rec.get('expiryTime'))} -> {users.fmt_expiry(body['expiryTime'])}")
        if args.comment is not None:
            body["comment"] = args.comment
            changes.append("comment updated")
        if not changes:
            print("Nothing to change: pass --cap and/or --expires and/or --comment.")
            return 2
        planned = dict(body)
        if args.expires is not None:
            planned["expiryTime"] = args.expires  # text, not ms: "30d" must plan the same twice
        plan = {"op": "users.set", "email": email, "body": planned}
        show(Card(f"Change limits for {email}", "Update cap/expiry. The endpoint REPLACES the user row, so the "
                  "full record (incl. UUID) is sent back unchanged apart from these fields.", api_t(cfg),
                  f"POST /panel/api/clients/update/{email}", cfg.api_credential(True), WRITE,
                  "snapshot saved first; `ops.py rollback --snapshot <file>` restores the old values",
                  changes=changes))
        if not gate(plan, args.execute, args.plan):
            return 0
        snap = snapshot(cfg, "client", found, {"email": email})
        api.client_update(email, body)
        now = find_record(api, email)["record"]
        ok = now.get("uuid") == rec.get("uuid") and now.get("totalGB") == body["totalGB"] \
            and now.get("expiryTime") == body["expiryTime"]
        result(ok, f"{email}: cap={users.fmt_cap(now.get('totalGB'))} "
                   f"expiry={users.fmt_expiry(now.get('expiryTime'))} uuid {'unchanged' if now.get('uuid') == rec.get('uuid') else 'CHANGED!'}",
               [f"rollback: ops.py rollback --snapshot {snap}"])
        return 0 if ok else 1

    if action == "reset-traffic":
        row = next((users.client_row(e) for e in api.clients() if users.client_row(e)["email"] == email), {})
        print(f"Current usage for {email} (record it; it cannot be restored): {users.fmt_bytes(row.get('used', 0))}"
              f" of cap {users.fmt_cap(row.get('cap'))}")
        plan = {"op": "users.reset-traffic", "email": email}
        show(Card(f"Reset traffic for {email}", "Zero the up/down counters. 3x-ui v3.11.0 also re-enables the user if it was disabled "
                  "(client_traffic.go ResetTraffic), including one you disabled by hand.",
                  api_t(cfg), f"POST /panel/api/clients/resetTraffic/{email}", cfg.api_credential(True), WRITE,
                  "NONE - old counters cannot be restored (usage printed above). If the user was disabled on purpose, "
                  f"run `ops.py users disable {email}` afterwards.",
                  changes=[f"{email}: used traffic -> 0"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        api.client_reset_traffic(email)
        result(True, f"{email} traffic reset")
        return 0

    raise SystemExit(f"unknown users action {action}")


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------
def classify(code: str) -> str:
    return {
        "000": "UNREACHABLE (network/TLS failure)",
        "200": "reachable",
        "401": "reachable (auth required - works with a key)",
        "403": "FORBIDDEN (often an IP/region block)",
        "404": "reachable (path not found)",
        "451": "BLOCKED (unavailable for legal reasons)",
    }.get(code, "reachable" if code.startswith(("2", "3", "4")) else "error")


def cmd_routing(cfg: Config, args) -> int:
    action = args.action
    api = client(cfg, write=True)
    cred = cfg.api_credential(True)

    if action == "list":
        show(Card("List routing rules", "Rules are checked top to bottom; unmatched traffic uses the FIRST outbound.",
                  api_t(cfg), "POST /panel/api/xray/  (template)", cred, RO))
        t = get_template(api)
        print(f"Outbounds (first = default): {', '.join(routing.outbound_tags(t))}")
        for i, r in enumerate(routing.rules(t)):
            print(f"  [{i}] {routing.describe_rule(r)}")
        result(True, f"{len(routing.rules(t))} rules; default outbound = {routing.default_outbound(t)}")
        return 0

    if action == "test":
        show(Card(f"Route test {args.matcher}", "Ask the running Xray which outbound it would pick (no traffic sent).",
                  api_t(cfg), f"POST /panel/api/xray/routeTest domain={args.matcher}", cred, RO))
        r = api.route_test(args.matcher)
        result(True, f"{args.matcher} -> {r.get('outboundTag') or '(no rule matched: default outbound)'}")
        return 0

    if action in ("add", "remove"):
        t = get_template(api)
        try:
            if action == "add":
                new, msg = routing.add_rule(t, args.matcher, args.outbound)
            else:
                new, msg = routing.remove_rule(t, args.matcher)
        except ValueError as exc:
            result(False, str(exc))
            return 2
        d = routing.diff(t, new)
        if not d:
            print(msg)
            result(True, "no change needed (idempotent)")
            return 0
        plan = {"op": f"routing.{action}", "matcher": args.matcher, "outbound": getattr(args, "outbound", None),
                "before": hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()}
        show(Card(f"Routing {action}: {args.matcher}" + (f" -> {args.outbound}" if action == "add" else ""),
                  msg, api_t(cfg),
                  "POST /panel/api/xray/update (form xraySetting=<full template>); the panel restarts a running Xray itself",
                  cred, WRITE,
                  "the full current template is snapshotted first; `ops.py rollback --snapshot <file>` puts it back",
                  changes=d))
        if not gate(plan, args.execute, args.plan):
            return 0
        snap = snapshot(cfg, "xray-template", t)
        api.update_xray_template(new)
        after = get_template(api)
        ok = not routing.diff(new, after)
        details = [f"snapshot: {snap}", f"rollback: ops.py rollback --snapshot {snap}"]
        if action == "add" and args.matcher.lower().startswith("domain:"):
            dom = args.matcher.split(":", 1)[1]
            try:
                details.append(f"routeTest {dom} -> {api.route_test(dom).get('outboundTag') or '(default)'}")
            except XUIError as exc:
                details.append(f"routeTest failed: {exc}")
        result(ok, msg, details)
        return 0 if ok else 1

    if action == "probe":
        names = args.providers.split(",") if args.providers else list(DEFAULT_PROVIDERS)
        bad = [n for n in names if n not in DEFAULT_PROVIDERS]
        if bad:
            raise SystemExit(f"unknown providers {bad}; known: {', '.join(DEFAULT_PROVIDERS)}")
        tag = cfg.get("PROXY_TAG")
        show(Card("AI provider probe: direct vs proxy", "Unauthenticated GET to each provider API from the VPS, "
                  f"once directly and once through the '{tag}' SOCKS proxy, plus what Xray's router would pick. "
                  "401 = reachable; 403/451/000 = blocked or broken from that IP.", ssh_t(cfg),
                  "ssh <VPS_SSH> 'curl -K -' per provider and path (config on stdin); POST /panel/api/xray/routeTest",
                  f"{cfg.ssh_description()}; proxy credentials from the live Xray template via {cred}, "
                  "sent only inside curl's stdin config; no provider API keys are used", RO,
                  remaining=[f"{n}: {DEFAULT_PROVIDERS[n]}" for n in names]))
        proxy = iproyal_proxy(get_template(api), tag)
        print(f"\n{'PROVIDER':<11} {'ROUTER PICKS':<14} {'DIRECT':<36} {'VIA ' + tag:<36}")
        for n in names:
            url = DEFAULT_PROVIDERS[n]
            host = url.split("/")[2]
            try:
                pick = api.route_test(host).get("outboundTag") or "(default)"
            except XUIError:
                pick = "?"
            cols = []
            for px in (None, proxy):
                if px is None and cols:
                    cols.append("no proxy outbound")
                    continue
                proc = remote.run(cfg, "curl -K -", stdin=remote.curl_config(url, px), timeout=40)
                code = (proc.stdout.decode(errors="replace").split() or ["000"])[0]
                cols.append(f"{code} {classify(code)}"[:35])
            print(f"{n:<11} {pick:<14} {cols[0]:<36} {cols[1]:<36}")
        print("\nTo send a provider direct (VPS IP) instead of the proxy: "
              "ops.py routing add domain:<host> direct")
        result(True, "probe finished (read-only)")
        return 0
    raise SystemExit(f"unknown routing action {action}")


# --------------------------------------------------------------------------
# backup / verify / restore
# --------------------------------------------------------------------------
def verify_db(path: Path) -> tuple[bool, list[str]]:
    notes = []
    data = path.read_bytes()
    if not data.startswith(b"SQLite format 3\x00"):
        return False, ["not a SQLite database (header mismatch)"]
    sha = hashlib.sha256(data).hexdigest()
    side = path.with_suffix(path.suffix + ".sha256")
    if side.exists():
        rec = side.read_text().split()[0]
        if rec != sha:
            return False, [f"sha256 mismatch: file {sha} vs recorded {rec}"]
        notes.append(f"sha256 matches {side.name}")
    else:
        notes.append(f"no {side.name} sidecar; sha256={sha}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ic = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        counts = {}
        for t in ("inbounds", "clients", "settings", "users"):
            if t in tables:
                counts[t] = con.execute(f"select count(*) from {t}").fetchone()[0]  # noqa: S608
    finally:
        con.close()
    notes.append(f"integrity_check={ic}")
    notes.append("rows: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    missing = {"inbounds", "settings"} - set(counts)
    if missing:
        return False, notes + [f"missing tables {sorted(missing)} - not a 3x-ui database?"]
    return ic == "ok", notes


def do_backup(cfg: Config, api: OpsClient, label: str = "") -> Path:
    data = api.get_bytes("/panel/api/server/getDb")
    out_dir = cfg.path("BACKUP_DIR")
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    p = out_dir / f"x-ui-{stamp()}{('-' + label) if label else ''}.db"
    write_private(p, data)
    sha = hashlib.sha256(data).hexdigest()
    write_private(p.with_suffix(".db.sha256"), f"{sha}  {p.name}\n".encode())
    return p


def cmd_backup(cfg: Config, args) -> int:
    if args.action == "verify":
        p = Path(args.file).expanduser().resolve()
        show(Card(f"Verify backup {p.name}", "Check the file is an intact 3x-ui SQLite database with the recorded sha256.",
                  "local only", f"read {p}", "none", LOCAL))
        ok, notes = verify_db(p)
        result(ok, str(p), notes)
        return 0 if ok else 1

    api = client(cfg, write=True)
    if args.action == "pull":
        show(Card("Back up the panel database", "Full copy of users, inbounds, settings and the Xray template "
                  "(x-ui.db). Contains secrets: stored mode 600.", api_t(cfg), "GET /panel/api/server/getDb",
                  cfg.api_credential(True), RO + " on the server; writes a local file",
                  changes=[f"new file in {cfg.get('BACKUP_DIR')} (+ .sha256 sidecar)"]))
        p = do_backup(cfg, api)
        ok, notes = verify_db(p)
        result(ok, f"saved {p} ({p.stat().st_size} bytes)", notes + [
            "Copy it somewhere off this laptop too (encrypted drive / password manager attachment)."])
        return 0 if ok else 1

    if args.action == "restore":
        p = Path(args.file).expanduser().resolve()
        ok, notes = verify_db(p)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        plan = {"op": "backup.restore", "file": str(p), "sha256": sha}
        show(Card(f"Restore panel database from {p.name}", "Replace ALL panel data (users, inbounds, settings, "
                  "Xray template) with this backup. The panel restarts.", api_t(cfg),
                  "1) GET /panel/api/server/getDb (pre-restore backup)  2) POST /panel/api/server/importDB "
                  "(multipart field 'db', keepHostSettings=true)", cfg.api_credential(True), WRITE,
                  "a pre-restore backup is taken first; restore that file the same way to undo",
                  changes=[f"file sha256 {sha}"] + notes,
                  remaining=["pre-restore backup", "upload + panel restart", "wait for panel", "verify status and users"]))
        if not ok:
            result(False, "backup failed verification - refusing to restore")
            return 1
        if not gate(plan, args.execute, args.plan):
            return 0
        pre = do_backup(cfg, api, "pre-restore")
        pre_ok, pre_notes = verify_db(pre)
        print(f"Pre-restore backup: {pre} ({'verified' if pre_ok else 'FAILED VERIFY'})")
        if not pre_ok:
            result(False, "pre-restore backup did not verify - aborting before any change", pre_notes)
            return 1
        resp = api.post_multipart("/panel/api/server/importDB", "db", p.name, p.read_bytes(),
                                  {"keepHostSettings": "true"})
        print(f"importDB response: success={resp.get('success')} msg={redact(str(resp.get('msg', '')), cfg)}")
        for _ in range(12):
            time.sleep(int(os.environ.get("VLESS_OPS_WAIT", "5")))
            up, _why = tunnel_up(cfg)
            if up:
                break
        try:
            api2 = client(cfg, write=True)
            st = api2.server_status()
            n = len(api2.clients())
            result(True, f"panel back; xray={st.get('xray', {}).get('state')}; {n} users",
                   [f"undo: ops.py backup restore {pre}"])
            return 0
        except SystemExit as exc:
            result(False, f"panel not back yet: {exc}", [f"undo when it is: ops.py backup restore {pre}"])
            return 1
    raise SystemExit("unknown backup action")


# --------------------------------------------------------------------------
# upgrade
# --------------------------------------------------------------------------
def cmd_upgrade(cfg: Config, args) -> int:
    target = args.to or cfg.get("XUI_VERSION")
    if not target or not target.startswith("v"):
        raise SystemExit("ERROR: give an explicit tag, e.g. --to v3.11.0")
    proc = remote.run_script(cfg, "remote-status.sh")
    kv = remote.parse_kv(proc.stdout.decode(errors="replace"))
    current = kv.get("xui_version", "?")
    url = f"https://raw.githubusercontent.com/MHSanaei/3x-ui/{target}/update.sh"
    remote_cmd = (f"curl -fsSL -o /tmp/x-ui-update-{target}.sh {url} && "
                  f"sudo -n env XUI_UPDATE_TAG={target} XUI_NONINTERACTIVE=1 bash /tmp/x-ui-update-{target}.sh")
    if target.lstrip("v") in current:
        result(True, f"already on {target} (no change)")
        return 0

    # optional cloud disk snapshot first (default when CLOUD_PROVIDER is set)
    snap_cmds: list[list[str]] = []
    snap_name = disk = ""
    cloud_cred = ""
    if cfg.get("CLOUD_PROVIDER") and not getattr(args, "no_cloud_snapshot", False):
        pf = cloud_preflight_card(cfg, "0", ["upgrade plan card"])
        if pf is None:
            print("Cloud preflight failed: fix it (references/cloud.md) or re-run with --no-cloud-snapshot "
                  "to rely on the panel DB backup alone.")
            return 1
        cloud_cred = cloud.identity_line(pf, cfg)
        snap_name = snapshot_name(cfg, f"pre-{target}")
        snap_cmds, disk, _ = cloud.snapshot_cmds(cfg, snap_name)

    steps = (["cloud disk snapshot " + snap_name + " of " + disk] if snap_cmds else []) + [
        "backup x-ui.db over the API (verified)", f"run the official update.sh from tag {target} with "
        f"XUI_UPDATE_TAG={target} (verifies the release .sha256)", "wait for the panel",
        "verify: version, Xray running, egress"]
    n = len(steps)
    plan = {"op": "upgrade", "from": current, "to": target, "cloud_snapshot": snap_name, "disk": disk}
    target_line = remote.show_cmd(cfg, remote_cmd)
    if snap_cmds:
        target_line = cloud.show(snap_cmds[0]) + "  THEN  " + target_line
    show(Card(f"Upgrade 3x-ui {current} -> {target}", "Move the panel and bundled Xray to a pinned release. "
              "Read the release notes first: newer Xray can enable Reality features older clients cannot handshake.",
              (cloud.cli_transport(cfg) + " + " if snap_cmds else "") + f"{api_t(cfg)} + {ssh_t(cfg)}", target_line,
              (cloud_cred + "; " if cloud_cred else "") +
              f"{cfg.api_credential(True)}; {cfg.ssh_description()} (needs passwordless sudo)", WRITE,
              f"re-run `ops.py upgrade --to {current if current.startswith('v') else '<previous tag>'}` and, if the "
              "database schema moved on, `ops.py backup restore <the backup>`. Downgrades across DB "
              "migrations are not guaranteed - the backups are the real safety net"
              + (f"; worst case restore the VM disk from cloud snapshot {snap_name}" if snap_cmds else "") + ".",
              changes=[f"x-ui {current} -> {target}"] + ([f"+ cloud snapshot {snap_name} (billed storage)"] if snap_cmds else []),
              remaining=steps))
    if not gate(plan, args.execute, args.plan):
        return 0
    i = 0
    if snap_cmds:
        i += 1
        print(f"\n[{i}/{n}] {steps[0]}  ({cloud.show(snap_cmds[0])})")
        ok, out = cloud.run_write(snap_cmds[0])
        result(ok, f"cloud snapshot {snap_name}", out.splitlines()[-5:])
        if not ok:
            print("Stopped before touching the server. Fix the snapshot or re-run with --no-cloud-snapshot.")
            return 1
    api = client(cfg, write=True)
    i += 1
    print(f"\n[{i}/{n}] {steps[i - 1]}")
    bk = do_backup(cfg, api, f"pre-upgrade-{target}")
    ok, notes = verify_db(bk)
    result(ok, f"backup {bk}", notes)
    if not ok:
        return 1
    i += 1
    print(f"\n[{i}/{n}] {steps[i - 1]}")
    up = remote.run(cfg, remote_cmd, timeout=900)
    tail = up.stdout.decode(errors="replace").strip().splitlines()[-15:]
    result(up.returncode == 0, f"update.sh exit {up.returncode}", tail)
    if up.returncode != 0:
        print(f"ROLLBACK: ops.py backup restore {bk}  (and re-run upgrade --to the previous tag)")
        return 1
    i += 1
    print(f"\n[{i}/{n}] {steps[i - 1]}")
    for _ in range(12):
        time.sleep(int(os.environ.get("VLESS_OPS_WAIT", "5")))
        if tunnel_up(cfg)[0]:
            break
    i += 1
    print(f"\n[{i}/{n}] {steps[i - 1]}")
    kv2 = remote.parse_kv(remote.run_script(cfg, "remote-status.sh").stdout.decode(errors="replace"))
    good = target.lstrip("v") in kv2.get("xui_version", "") and kv2.get("xray_process") == "running"
    try:
        lines = egress_check(cfg, iproyal_proxy(get_template(client(cfg, write=True)), cfg.get("PROXY_TAG")))
    except SystemExit as exc:
        lines = [f"egress check failed: {exc}"]
    result(good, f"x-ui {kv2.get('xui_version')} xray={kv2.get('xray_process')}",
           lines + [f"if clients fail: ops.py backup restore {bk}"])
    return 0 if good else 1


# --------------------------------------------------------------------------
# rotate Reality keys / shortId / SNI
# --------------------------------------------------------------------------
INBOUND_DROP = {"id", "clientStats", "up", "down", "allTime", "lastTrafficResetTime"}


def cmd_rotate(cfg: Config, args) -> int:
    api = client(cfg, write=True)
    ib = pick_inbound(api, cfg)
    ss = ib.get("streamSettings") or {}
    rs = dict(ss.get("realitySettings") or {})
    old = users.reality_params(ib)
    new_sni = args.sni or old["sni"]
    new_target = args.target or (f"{args.sni}:443" if args.sni else old["target"])
    changes = [f"inbound {ib.get('id')} ({ib.get('remark')})"]
    if args.keys:
        changes.append("Reality x25519 keypair: NEW (public key changes -> every link changes)")
    if args.short_id:
        changes.append("shortIds: NEW random 8-byte id (old one removed)")
    if args.sni:
        changes.append(f"serverNames {rs.get('serverNames')} -> [{new_sni}], target {old['target']} -> {new_target}")
    if len(changes) == 1:
        print("Nothing to rotate: pass --keys and/or --short-id and/or --sni HOST [--target HOST:443].")
        return 2
    steps = []
    if args.sni:
        steps.append(f"probe the new donor {new_target} (POST /panel/api/server/scanRealityTarget, read-only)")
    steps += ["snapshot the inbound (contains the private key, mode 600)",
              "generate new values" + (" (GET /panel/api/server/getNewX25519Cert)" if args.keys else ""),
              "POST /panel/api/inbounds/update/{id}", "regenerate every user's link"]
    plan = {"op": "rotate", "inbound": ib.get("id"), "keys": args.keys, "sid": args.short_id,
            "sni": new_sni, "target": new_target, "pbk": old["pbk"], "oldsid": old["sid"]}
    show(Card("Rotate Reality parameters", "Fresh keys/shortId/SNI if a link leaked or the donor stopped working. "
              "EVERY user must re-import their link afterwards.", api_t(cfg),
              "POST /panel/api/inbounds/update/{id} (clients and enable flag are kept by the server)",
              cfg.api_credential(True), WRITE,
              "`ops.py rollback --snapshot <inbound snapshot>` restores the old keys/SNI (old links work again)",
              changes=changes, remaining=steps))
    if args.sni:
        scan = api.require_success(api.request("POST", "/panel/api/server/scanRealityTarget",
                                               form={"target": new_target, "sni": new_sni}), "scanRealityTarget")
        print(f"Donor scan: {json.dumps(scan.get('obj'), default=str)[:400]}")
    if not gate(plan, args.execute, args.plan):
        return 0
    snap = snapshot(cfg, "inbound", ib, {"inbound": ib.get("id")})
    print(f"Snapshot: {snap}")
    if args.keys:
        kp = api.get_x25519()
        rs["privateKey"] = kp["privateKey"]
        inner = dict(rs.get("settings") or {})
        inner["publicKey"] = kp["publicKey"]
        rs["settings"] = inner
    if args.short_id:
        rs["shortIds"] = [secrets.token_hex(8)]
    if args.sni:
        rs["serverNames"] = [new_sni]
        rs["target"] = new_target
        rs.pop("dest", None)
    body = {k: v for k, v in ib.items() if k not in INBOUND_DROP}
    body["streamSettings"] = dict(ss, realitySettings=rs)
    api.update_inbound(int(ib["id"]), body)
    after = api.inbound(int(ib["id"]))
    p = users.reality_params(after)
    ok = (not args.keys or p["pbk"] != old["pbk"]) and (not args.short_id or p["sid"] != old["sid"]) \
        and (not args.sni or p["sni"] == new_sni)
    links = []
    for e in api.clients():
        row = users.client_row(e)
        if int(ib["id"]) in row["inbounds"]:
            rec = e.get("client", e)
            links.append(users.vless_link(after, row["uuid"], rec.get("flow", ""), public_host(cfg), row["email"]))
    lf = cfg.state_dir() / f"links-{stamp()}.txt"
    write_private(lf, ("\n".join(links) + "\n").encode())
    result(ok, f"rotated; {len(links)} links regenerated -> {lf} (mode 600)",
           [f"new public key ...{p['pbk'][-6:]} sid ...{p['sid'][-4:]} sni {p['sni']}",
            f"rollback: ops.py rollback --snapshot {snap}",
            "show one: ops.py users link <name> --qr"])
    return 0 if ok else 1


# --------------------------------------------------------------------------
# drift
# --------------------------------------------------------------------------
def setup_templates() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3] / "vless-vpn-3xui-skill" / "templates"


def drift_findings(t: dict[str, Any], ib: Optional[dict[str, Any]], tag: str,
                   expect_proxy: bool, expect_rules: list[str]) -> list[tuple[str, str]]:
    f: list[tuple[str, str]] = []
    tags = routing.outbound_tags(t)
    if expect_proxy:
        if tag not in tags:
            f.append(("FAIL", f"outbound '{tag}' missing (setup skill adds it first)"))
        elif tags[0] != tag:
            f.append(("FAIL", f"default (first) outbound is '{tags[0]}', expected '{tag}' -> unmatched traffic skips the proxy"))
        else:
            f.append(("OK", f"'{tag}' is the first/default outbound"))
        ob = next((o for o in t.get("outbounds", []) if o.get("tag") == tag), {})
        srv = ((ob.get("settings") or {}).get("servers") or [{}])[0]
        if ob and not (srv.get("address") and srv.get("port")):
            f.append(("FAIL", f"'{tag}' has no servers[0].address/port (template shape: templates/xray-socks-outbound.json)"))
    direct = next((o for o in t.get("outbounds", []) if o.get("tag") == "direct"), None)
    if not direct:
        f.append(("FAIL", "no 'direct' (freedom) outbound"))
    else:
        fr = (direct.get("settings") or {}).get("finalRules") or []
        if any(r.get("action") == "block" and "geoip:private" in (r.get("ip") or []) for r in fr):
            f.append(("WARN", "direct.finalRules still blocks geoip:private (panel default); the setup skill loosens this"))
    for m in expect_rules:
        key, value = routing.parse_matcher(m.split("->")[0].strip())
        want = m.split("->")[1].strip()
        hit = [r for r in routing.rules(t) if value in (r.get(key) or [])]
        if not hit:
            f.append(("FAIL", f"rule missing: {value} -> {want}"))
        elif hit[0].get("outboundTag") != want:
            f.append(("FAIL", f"{value} routes to {hit[0].get('outboundTag')}, expected {want}"))
        else:
            f.append(("OK", f"rule {value} -> {want}"))
    if ib:
        rs = (ib.get("streamSettings") or {}).get("realitySettings") or {}
        for k in ("mldsa65Seed", "minClientVer", "maxClientVer"):
            if rs.get(k):
                f.append(("WARN", f"inbound realitySettings.{k} is set; many clients cannot handshake with it"))
        if (rs.get("settings") or {}).get("mldsa65Verify"):
            f.append(("WARN", "inbound realitySettings.settings.mldsa65Verify is set"))
        if ib.get("port") != 443:
            f.append(("WARN", f"inbound port {ib.get('port')} (setup default 443)"))
    return f


def cmd_drift(cfg: Config, args) -> int:
    tag = cfg.get("PROXY_TAG")
    expect_proxy = (cfg.get("EXPECT_PROXY") or "1") not in ("0", "false", "no")
    expect_rules = [r.strip() for r in (cfg.get("EXPECT_RULES") or "geoip:private->direct,domain:openrouter.ai->direct").split(",") if r.strip()]
    show(Card("Drift check", "Compare the live Xray template and inbound with what the setup skill and this "
              "skill expect (repo templates + EXPECT_RULES). Read-only; prints a redacted diff.", api_t(cfg),
              "POST /panel/api/xray/, GET /panel/api/inbounds/list, GET /panel/api/server/getConfigJson",
              cfg.api_credential(True), RO,
              changes=[f"expected rules: {', '.join(expect_rules)}", f"expect '{tag}' first: {expect_proxy}",
                       f"repo templates: {setup_templates()}"]))
    api = client(cfg, write=True)
    t = get_template(api)
    try:
        ib = pick_inbound(api, cfg)
    except SystemExit as exc:
        print(f"  inbound: {exc}")
        ib = None
    fs = drift_findings(t, ib, tag, expect_proxy, expect_rules)
    for level, msg in fs:
        print(f"  [{level}] {msg}")
    # desired = live + expected rules applied, shown as a diff
    desired = t
    for m in expect_rules:
        try:
            desired, _ = routing.add_rule(desired, m.split("->")[0].strip(), m.split("->")[1].strip())
        except ValueError:
            pass
    d = routing.diff(t, desired, "template")
    if d:
        print("\nWhat `routing add` would change to match (redacted):")
        print("\n".join(d))
    try:
        running = api.running_config()
        live_rules = (running.get("routing") or {}).get("rules") or []
        if len(live_rules) < len(routing.rules(t)):
            print(f"  [WARN] running Xray has {len(live_rules)} rules, template has {len(routing.rules(t))}: "
                  "template saved but not applied? (POST /panel/api/server/restartXrayService)")
    except XUIError:
        pass
    if args.export:
        out = Path(args.export).expanduser()
        write_private(out / f"template-{stamp()}.redacted.json",
                      json.dumps(routing.redact_template(t), indent=2).encode())
        print(f"Exported redacted template to {out}")
    fails = sum(1 for lv, _ in fs if lv == "FAIL")
    result(fails == 0, f"{fails} FAIL, {sum(1 for lv, _ in fs if lv == 'WARN')} WARN")
    return 0 if fails == 0 else 1


# --------------------------------------------------------------------------
# rollback from a snapshot
# --------------------------------------------------------------------------
def cmd_rollback(cfg: Config, args) -> int:
    p = Path(args.snapshot).expanduser()
    snap = json.loads(p.read_text())
    kind = snap.get("kind")
    data = snap.get("data")
    api = client(cfg, write=True)
    plan = {"op": "rollback", "file": str(p.resolve()), "sha": hashlib.sha256(p.read_bytes()).hexdigest()}
    if kind == "xray-template":
        cur = get_template(api)
        show(Card(f"Rollback Xray template to {snap['created']}", "Put back the template saved before a routing change.",
                  api_t(cfg), "POST /panel/api/xray/update", cfg.api_credential(True), WRITE,
                  "the current template is snapshotted first, so this rollback can itself be undone",
                  changes=routing.diff(cur, data) or ["(identical to live)"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        s2 = snapshot(cfg, "xray-template", cur)
        api.update_xray_template(data)
        result(not routing.diff(data, get_template(api)), "template restored", [f"undo: ops.py rollback --snapshot {s2}"])
        return 0
    if kind == "inbound":
        iid = int(data["id"])
        cur = api.inbound(iid)
        show(Card(f"Rollback inbound {iid} to {snap['created']}", "Restore Reality keys/shortIds/SNI from the snapshot.",
                  api_t(cfg), f"POST /panel/api/inbounds/update/{iid}", cfg.api_credential(True), WRITE,
                  "the current inbound is snapshotted first",
                  changes=[f"pbk ...{users.reality_params(cur)['pbk'][-6:]} -> ...{users.reality_params(data)['pbk'][-6:]}",
                           f"sni {users.reality_params(cur)['sni']} -> {users.reality_params(data)['sni']}"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        s2 = snapshot(cfg, "inbound", cur)
        api.update_inbound(iid, {k: v for k, v in data.items() if k not in INBOUND_DROP})
        result(True, "inbound restored", [f"undo: ops.py rollback --snapshot {s2}"])
        return 0
    if kind == "client":
        rec = data["record"]
        email = rec["email"]
        exists = email in {users.client_row(e)["email"] for e in api.clients()}
        body = users.record_to_update_body(rec)
        how = f"POST /panel/api/clients/update/{email}" if exists else "POST /panel/api/clients/add (same UUID)"
        show(Card(f"Rollback user {email} to {snap['created']}", "Restore the user's saved record (UUID, cap, expiry).",
                  api_t(cfg), how, cfg.api_credential(True), WRITE,
                  f"ops.py users remove {email}" if not exists else "snapshot of the current record is saved first",
                  changes=[f"{email}: {'update' if exists else 're-create'} with uuid ...{body['id'][-6:]}"]))
        if not gate(plan, args.execute, args.plan):
            return 0
        if exists:
            snapshot(cfg, "client", find_record(api, email), {"email": email})
            api.client_update(email, body)
        else:
            api.client_add(body, data.get("inboundIds") or [int(pick_inbound(api, cfg)["id"])])
        result(True, f"{email} restored")
        return 0
    raise SystemExit(f"unknown snapshot kind {kind!r}")


# --------------------------------------------------------------------------
# cloud (az / gcloud): preflight, snapshot, firewall, restart, resize, rotate-ip
# --------------------------------------------------------------------------
PROTECTED_PORTS = (22, 443)


def snapshot_name(cfg: Config, label: str) -> str:
    raw = f"{cloud.vm(cfg)}-{label}-{cloud.today()}".lower()
    clean = "".join(c if c.isalnum() or c == "-" else "-" for c in raw).strip("-")
    if not clean[:1].isalpha():
        clean = "s-" + clean
    return clean[:63]


def cloud_preflight_card(cfg: Config, step: Optional[str], remaining: list[str]) -> Optional[dict]:
    """Show + run the read-only preflight. Returns parsed output or None on failure."""
    prov = cloud.provider(cfg)
    show(Card("Cloud preflight", "Prove the CLI is installed and logged in, and that the subscription/project is "
              "the expected one, before any cloud call. Prints names only.", "local only (runs the cloud CLI read-only)",
              f"scripts/cloud-preflight.sh {prov} --require-vm",
              "your existing az/gcloud CLI login (az login / gcloud auth login); no tokens read or printed",
              RO, step=step, remaining=remaining))
    pf = cloud.preflight(cfg, require_vm=True)
    lines = [f"{k}: {v}" for k, vs in pf.items() if k != "PREFLIGHT" for v in vs]
    ok = pf["PREFLIGHT"][-1] == "OK"
    result(ok, "preflight " + ("passed" if ok else "FAILED"), lines)
    if ok and any(k == "warning" for k in pf):
        print("  Read the warnings above to the user before any cloud write.")
    return pf if ok else None


def _fw_rows(cfg: Config) -> list[dict[str, str]]:
    raw = json.loads(cloud.run_ro(cloud.firewall_list_cmd(cfg)) or "[]")
    rows = []
    for r in raw:
        if cloud.provider(cfg) == "azure":
            rows.append({"name": r.get("name", ""), "prio": str(r.get("priority", "")),
                         "dir": r.get("direction", ""), "access": r.get("access", ""),
                         "ports": ",".join(sorted(cloud.rule_ports(r))) or "*",
                         "src": ",".join(filter(None, [r.get("sourceAddressPrefix")] + list(r.get("sourceAddressPrefixes") or [])))})
        else:
            rows.append({"name": r.get("name", ""), "prio": str(r.get("priority", "")),
                         "dir": r.get("direction", ""), "access": "Deny" if r.get("denied") else "Allow",
                         "ports": ",".join(f"{a.get('IPProtocol')}:{p}" for a in r.get("allowed", []) for p in (a.get("ports") or ["*"])),
                         "src": ",".join(r.get("sourceRanges", [])) + (f" tags={','.join(r.get('targetTags', []))}" if r.get("targetTags") else "")})
    return rows


def cmd_cloud(cfg: Config, args) -> int:
    prov = cloud.provider(cfg)
    action = args.action
    tr = cloud.cli_transport(cfg)

    if action == "preflight":
        return 0 if cloud_preflight_card(cfg, None, []) else 1

    if action == "firewall-list":
        pf = cloud_preflight_card(cfg, "1/2", ["list firewall rules (read-only)"])
        if not pf:
            return 1
        show(Card("List firewall rules", "What the cloud firewall lets in to the VM.", tr,
                  cloud.show(cloud.firewall_list_cmd(cfg)), cloud.identity_line(pf, cfg), RO, step="2/2"))
        rows = _fw_rows(cfg)
        print(f"{'NAME':32} {'PRIO':>5} {'DIR':8} {'ACCESS':6} {'PORTS':18} SOURCE")
        for r in rows:
            print(f"{r['name'][:32]:32} {r['prio']:>5} {r['dir'][:8]:8} {r['access'][:6]:6} {r['ports'][:18]:18} {r['src']}")
        result(True, f"{len(rows)} rules")
        return 0

    pf = cloud_preflight_card(cfg, "1/2", [f"cloud {action} (card, then dry run / execute)"])
    if not pf:
        return 1
    cred = cloud.identity_line(pf, cfg)

    if action == "snapshot":
        name = args.name or snapshot_name(cfg, "ops")
        cmds, disk, rb = cloud.snapshot_cmds(cfg, name)
        plan = {"op": "cloud.snapshot", "prov": prov, "name": name, "disk": disk}
        show(Card(f"Snapshot VM disk {disk} -> {name}", "Point-in-time copy of the whole VM disk (OS, x-ui, DB) "
                  "before risky work. Costs storage until deleted.", tr, cloud.show(cmds[0]), cred, WRITE, rb,
                  changes=[f"+ snapshot {name} of disk {disk} (VM keeps running; crash-consistent)"], step="2/2"))
        if not gate(plan, args.execute, args.plan):
            return 0
        ok, out = cloud.run_write(cmds[0])
        result(ok, f"snapshot {name} {'created' if ok else 'FAILED'}", out.splitlines()[-8:])
        return 0 if ok else 1

    if action == "firewall-open":
        port = int(args.port)
        proto = (args.proto or "tcp").lower()
        source = args.source or "0.0.0.0/0"
        if source in ("0.0.0.0/0", "*", "Internet", "any") and port not in (443,):
            print(f"NOTE: opening {proto}/{port} to the whole internet. Prefer --source <your-ip>/32.")
        name = args.name or f"vless-ops-{proto}-{port}"
        prio = cloud.az_next_priority(cfg) if prov == "azure" else 1000
        cmd = cloud.firewall_open_cmd(cfg, name, str(port), proto, source, prio)
        plan = {"op": "cloud.firewall-open", "prov": prov, "name": name, "port": port, "proto": proto,
                "source": source, "prio": prio}
        show(Card(f"Open {proto}/{port} from {source}", "Allow new inbound traffic to the VM (e.g. a second VLESS "
                  "port if 443 is throttled). Never use this for the panel port: use the SSH tunnel.", tr,
                  cloud.show(cmd), cred, WRITE, f"ops.py cloud firewall-close {name}",
                  changes=[f"+ rule {name}: allow {proto}/{port} from {source}" +
                           (f" (priority {prio})" if prov == "azure" else f" (target tag {cloud.gtag(cfg)})")],
                  step="2/2"))
        if not gate(plan, args.execute, args.plan):
            return 0
        ok, out = cloud.run_write(cmd)
        result(ok, f"rule {name} {'created' if ok else 'FAILED'}", out.splitlines()[-8:])
        return 0 if ok else 1

    if action == "firewall-close":
        name = args.name
        if not name:
            raise SystemExit("cloud firewall-close NAME (see: ops.py cloud firewall-list)")
        rule = json.loads(cloud.run_ro(cloud.firewall_show_cmd(cfg, name)))
        ports = cloud.rule_ports(rule)
        hits = [p for p in PROTECTED_PORTS if cloud.covers(ports, p)]
        if hits and not args.allow_lockout:
            print(f"REFUSED: rule {name} allows port(s) {hits}. Closing it can lock you out of SSH (22) or cut "
                  "every VPN client (443). If that is really intended, re-run with --allow-lockout.")
            return 3
        cmd = cloud.firewall_close_cmd(cfg, name)
        plan = {"op": "cloud.firewall-close", "prov": prov, "name": name, "rule": rule}
        show(Card(f"Close firewall rule {name}", "Remove an inbound allow rule.", tr, cloud.show(cmd), cred, WRITE,
                  "the rule JSON is snapshotted first; re-create it from that file "
                  "(ops.py cloud firewall-open with the same port/source/name)",
                  changes=[f"- rule {name} (ports {','.join(sorted(ports)) or '*'})"] +
                  ([f"WARNING: covers protected port(s) {hits}"] if hits else []), step="2/2"))
        if not gate(plan, args.execute, args.plan):
            return 0
        snap = snapshot(cfg, "cloud-firewall-rule", rule, {"name": name, "provider": prov})
        print(f"Snapshot saved: {snap}")
        ok, out = cloud.run_write(cmd)
        result(ok, f"rule {name} {'deleted' if ok else 'FAILED'}", out.splitlines()[-8:])
        return 0 if ok else 1

    if action == "restart":
        cmds, note = cloud.restart_cmds(cfg)
        plan = {"op": "cloud.restart", "prov": prov, "vm": cloud.vm(cfg)}
        show(Card(f"Restart VM {cloud.vm(cfg)}", f"Reboot the VM from the cloud side (use when SSH is dead). {note}.",
                  tr, cloud.show(cmds[0]), cred, WRITE,
                  "none needed; x-ui is enabled at boot. Check with ops.py status afterwards",
                  changes=["VPN down for ~1-3 minutes for every user"], step="2/2"))
        if not gate(plan, args.execute, args.plan):
            return 0
        ok, out = cloud.run_write(cmds[0])
        result(ok, f"restart {'issued' if ok else 'FAILED'}", out.splitlines()[-5:] + ["next: ops.py status"])
        return 0 if ok else 1

    if action == "resize":
        size = args.size
        if not size:
            raise SystemExit("cloud resize SIZE (Azure e.g. Standard_B2s, GCP e.g. e2-small)")
        cur = cloud.current_size(cfg)
        if cur == size:
            result(True, f"already {size} (no change)")
            return 0
        cmds = cloud.resize_cmds(cfg, size)
        extra: list[str] = []
        if prov == "gcp":
            _, ip = cloud.gcp_access_config(cloud.gcp_instance(cfg))
            reserved = cloud.gcp_ip_reserved(cfg, ip)
            if not reserved:
                extra.append(f"external IP {ip} is EPHEMERAL: stopping the VM releases it and every link breaks")
                if not args.allow_ip_change:
                    print(f"REFUSED: {extra[0]}.\nPromote it first (cloud write, run it yourself or ask me):\n"
                          f"  gcloud compute addresses create {cloud.vm(cfg)}-ip --addresses {ip} "
                          f"--region {cloud.region(cfg)} --project {cloud.project(cfg)}\n"
                          "or re-run with --allow-ip-change and then fix PUBLIC_HOST and re-send links.")
                    return 3
        plan = {"op": "cloud.resize", "prov": prov, "from": cur, "to": size}
        show(Card(f"Resize VM {cloud.vm(cfg)}: {cur} -> {size}", "Change CPU/RAM. The VM restarts (GCP: stop, "
                  "change, start).", tr, "  THEN  ".join(cloud.show(c) for c in cmds), cred, WRITE,
                  f"ops.py cloud resize {cur}", changes=[f"size {cur} -> {size}", "VPN down for a few minutes"] + extra,
                  step="2/2", remaining=[cloud.show(c) for c in cmds]))
        if not gate(plan, args.execute, args.plan):
            return 0
        for i, c in enumerate(cmds, 1):
            print(f"\n[{i}/{len(cmds)}] {cloud.show(c)}")
            ok, out = cloud.run_write(c)
            result(ok, "done" if ok else "FAILED", out.splitlines()[-5:])
            if not ok:
                if prov == "gcp" and i >= 2:
                    print("VM may be stopped: gcloud compute instances start "
                          f"{cloud.vm(cfg)} --project {cloud.project(cfg)} --zone {cloud.zone(cfg)}")
                return 1
        print("next: ops.py status")
        return 0

    if action == "rotate-ip":
        new_name = args.name or f"{cloud.vm(cfg)}-ip-{cloud.today()}"
        rp = cloud.rotate_ip_plan(cfg, new_name)
        if rp["ip_lost"] and not args.allow_ip_change:
            print(f"REFUSED: {rp['rollback']}\nRe-run with --allow-ip-change once the user accepts losing it.")
            return 3
        steps = [cloud.show(c) for c in rp["cmds"]] + ["read the new IP", "update PUBLIC_HOST + DNS, regenerate links"]
        plan = {"op": "cloud.rotate-ip", "prov": prov, "new": new_name, "old": rp["old"]}
        show(Card("Rotate the VM's public IP", "New IP when the current one is blocked/throttled. Every client link "
                  "uses the IP, so all users must re-import (or update your DNS record).", tr,
                  "  THEN  ".join(steps[:len(rp['cmds'])]), cred, WRITE, rp["rollback"],
                  changes=[f"public IP {rp['old'] or '?'} -> new static address {new_name}", "VPN down ~1 minute",
                           "new static IP is billed; old one too until you delete it (Azure)"],
                  step="2/2", remaining=steps))
        if not gate(plan, args.execute, args.plan):
            return 0
        ok, out = cloud.run_write(rp["cmds"][0])
        result(ok, f"[1/{len(steps)}] {steps[0]}", out.splitlines()[-5:])
        if not ok:
            return 1
        new_ip = cloud.run_ro(rp["get_ip"])
        cmds = rp["cmds"][1:]
        if prov == "gcp":
            cmds[-1] = [a if a != "--address=<new address from step 1>" else f"--address={new_ip}" for a in cmds[-1]]
        for i, c in enumerate(cmds, 2):
            ok, out = cloud.run_write(c)
            result(ok, f"[{i}/{len(steps)}] {cloud.show(c)}", out.splitlines()[-5:])
            if not ok:
                print(f"ROLLBACK: {rp['rollback']}")
                return 1
        result(True, f"new public IP {new_ip}", [
            f"set PUBLIC_HOST={new_ip} in {cfg.env_file} (or point your DNS name at it)",
            "update VPS_SSH if it uses the IP; ssh will warn about a new host key entry",
            "regenerate links: ops.py users link NAME (each user must re-import)"])
        return 0

    raise SystemExit(f"unknown cloud action {action}")
