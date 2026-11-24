"""A tiny stand-in for the 3x-ui v3.11.0 panel API, for offline tests.

Mirrors the behaviour that matters to the ops scripts, as read from the v3.11.0
source: base path prefix, GET /csrf-token before CSRF-protected POST /login,
Bearer tokens skipping CSRF, monitor-scope allowlist, /clients/* endpoints with
uuid-in-record / id-in-body, update REPLACING the row, POST /panel/api/xray/
returning obj as a JSON string, getDb streaming a SQLite file, importDB multipart.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
import sqlite3
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = "/secretpath"
ADMIN = "admintok-0123456789"
MONITOR = "montok-0123456789"
USER, PASSWORD = "opsadmin", "pw-very-secret-1"

TEMPLATE = {
    "api": {"tag": "api", "services": ["HandlerService"]},
    "inbounds": [{"listen": "127.0.0.1", "port": 62789, "protocol": "tunnel", "tag": "api"}],
    "outbounds": [
        {"tag": "iproyal", "protocol": "socks", "settings": {"servers": [
            {"address": "1.2.3.4", "port": 12324, "users": [{"user": "proxyuser", "pass": "proxypass-secret"}]}]}},
        {"tag": "direct", "protocol": "freedom", "settings": {}},
        {"tag": "blocked", "protocol": "blackhole", "settings": {}},
    ],
    "routing": {"domainStrategy": "AsIs", "rules": [
        {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "blocked"},
    ]},
}

INBOUND = {
    "id": 1, "remark": "VLESS-Reality-443", "port": 443, "protocol": "vless", "enable": True,
    "tag": "inbound-443", "listen": "", "expiryTime": 0, "total": 0, "up": 0, "down": 0,
    "settings": json.dumps({"clients": [], "decryption": "none"}),
    "streamSettings": json.dumps({"network": "tcp", "security": "reality", "realitySettings": {
        "show": False, "target": "www.microsoft.com:443", "serverNames": ["www.microsoft.com"],
        "privateKey": "PRIV-old", "shortIds": ["abcd1234abcd1234"], "mldsa65Seed": "",
        "minClientVer": "", "maxClientVer": "",
        "settings": {"publicKey": "PUB-old", "fingerprint": "chrome", "spiderX": "/", "mldsa65Verify": ""}}}),
    "sniffing": json.dumps({"enabled": True}),
}


def make_db(path: Path, n_clients: int = 1) -> bytes:
    con = sqlite3.connect(path)
    con.execute("create table inbounds (id integer primary key, remark text)")
    con.execute("create table clients (id integer primary key, email text)")
    con.execute("create table settings (id integer primary key, key text, value text)")
    con.execute("create table users (id integer primary key, username text)")
    con.execute("insert into inbounds(remark) values ('VLESS-Reality-443')")
    for i in range(n_clients):
        con.execute("insert into clients(email) values (?)", (f"user{i}",))
    con.commit()
    con.close()
    return path.read_bytes()


class State:
    def __init__(self) -> None:
        self.template = copy.deepcopy(TEMPLATE)
        self.inbound = copy.deepcopy(INBOUND)
        self.clients: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        tmp = Path(tempfile.mkdtemp())
        self.db = make_db(tmp / "x.db", 2)
        self.imported: bytes | None = None
        self.add_client({"id": "11111111-1111-1111-1111-111111111111", "email": "alice",
                         "flow": "xtls-rprx-vision", "totalGB": 0, "expiryTime": 0, "enable": True,
                         "subId": "s1", "limitIp": 0, "tgId": 0, "comment": ""}, [1])

    def add_client(self, c: dict, inbound_ids: list[int]) -> None:
        rec = {k: v for k, v in c.items() if k != "id"}
        rec["uuid"] = c.get("id") or "generated-uuid"
        rec.setdefault("enable", True)
        self.clients[c["email"]] = {"record": rec, "inboundIds": inbound_ids,
                                    "traffic": {"up": 1024 ** 3, "down": 2 * 1024 ** 3}}


class Handler(BaseHTTPRequestHandler):
    state: State = None  # type: ignore[assignment]

    def log_message(self, *a):  # silence
        pass

    def _json(self, obj, code=200, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", f"3x-ui={cookie}; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session(self):
        m = re.search(r"3x-ui=([^;]+)", self.headers.get("Cookie", ""))
        return m.group(1) if m else None

    def _auth(self, method, rel):
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {ADMIN}":
            return "admin"
        if auth == f"Bearer {MONITOR}":
            return "monitor"
        sid = self._session()
        sess = self.state.sessions.get(sid or "")
        if not sess or not sess.get("user"):
            return None
        if method != "GET" and self.headers.get("X-CSRF-Token") != sess["csrf"]:
            return "csrf-fail"
        return "admin"

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        st = self.state
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        st.calls.append((method, path))
        if not path.startswith(BASE):
            return self._json({"success": False}, 404)
        rel = path[len(BASE):]
        raw = self._body()
        if rel == "/csrf-token" and method == "GET":
            sid = self._session()
            if not sid or sid not in st.sessions:
                sid = secrets.token_hex(8)
                st.sessions[sid] = {"csrf": secrets.token_urlsafe(16), "user": None}
                return self._json({"success": True, "obj": st.sessions[sid]["csrf"]}, cookie=sid)
            return self._json({"success": True, "obj": st.sessions[sid]["csrf"]})
        if rel == "/login" and method == "POST":
            sid = self._session()
            sess = st.sessions.get(sid or "")
            if not sess or self.headers.get("X-CSRF-Token") != sess["csrf"]:
                return self._json({"success": False}, 403)
            body = json.loads(raw or b"{}")
            if body.get("username") == USER and body.get("password") == PASSWORD:
                sess["user"] = USER
                return self._json({"success": True, "msg": "ok"})
            return self._json({"success": False, "msg": "wrong"})
        if not rel.startswith("/panel/api"):
            return self._json({"success": False}, 404)
        api = rel[len("/panel/api"):]
        who = self._auth(method, api)
        if who is None:
            return self._json({"success": False}, 404)
        if who == "csrf-fail":
            return self._json({"success": False}, 403)
        if who == "monitor" and not (method == "GET" and api == "/server/status"):
            return self._json({"success": False, "msg": "this API token is not permitted to access this endpoint"}, 403)
        form = dict(urllib.parse.parse_qsl(raw.decode(errors="replace"))) if \
            "x-www-form-urlencoded" in self.headers.get("Content-Type", "") else {}
        q = dict(urllib.parse.parse_qsl(parsed.query))

        if api == "/server/status":
            return self._json({"success": True, "obj": {"cpu": 3.5, "xray": {"state": "running", "version": "v26.10.21", "errorMsg": ""}}})
        if api == "/inbounds/list":
            return self._json({"success": True, "obj": [st.inbound]})
        if api == "/inbounds/get/1":
            return self._json({"success": True, "obj": st.inbound})
        if api == "/inbounds/update/1" and method == "POST":
            body = json.loads(raw)
            ss = body["streamSettings"]
            st.inbound["streamSettings"] = ss if isinstance(ss, str) else json.dumps(ss)
            return self._json({"success": True})
        if api == "/clients/list":
            out = []
            for v in st.clients.values():
                out.append(dict(v["record"], inboundIds=v["inboundIds"], traffic=v["traffic"]))
            return self._json({"success": True, "obj": out})
        m = re.fullmatch(r"/clients/get/(.+)", api)
        if m:
            email = urllib.parse.unquote(m.group(1))
            if email not in st.clients:
                return self._json({"success": False, "msg": "record not found"})
            v = st.clients[email]
            return self._json({"success": True, "obj": {"client": v["record"], "inboundIds": v["inboundIds"]}})
        if api == "/clients/add":
            body = json.loads(raw)
            if body["client"]["email"] in st.clients:
                return self._json({"success": False, "msg": "duplicate email"})
            st.add_client(body["client"], body["inboundIds"])
            return self._json({"success": True})
        m = re.fullmatch(r"/clients/update/(.+)", api)
        if m:
            email = urllib.parse.unquote(m.group(1))
            body = json.loads(raw)
            rec = {k: v for k, v in body.items() if k != "id"}
            rec["uuid"] = body.get("id", "")  # REPLACES: missing id would blank the uuid
            st.clients[email]["record"] = rec
            return self._json({"success": True})
        m = re.fullmatch(r"/clients/del/(.+)", api)
        if m:
            st.clients.pop(urllib.parse.unquote(m.group(1)), None)
            st.last_keep = q.get("keepTraffic")
            return self._json({"success": True})
        if api in ("/clients/bulkEnable", "/clients/bulkDisable"):
            for e in json.loads(raw)["emails"]:
                st.clients[e]["record"]["enable"] = api.endswith("Enable")
            return self._json({"success": True, "obj": {"changed": 1}})
        m = re.fullmatch(r"/clients/resetTraffic/(.+)", api)
        if m:
            st.clients[urllib.parse.unquote(m.group(1))]["traffic"] = {"up": 0, "down": 0}
            return self._json({"success": True})
        if api == "/xray/" and method == "POST":
            obj = {"xraySetting": st.template, "inboundTags": ["inbound-443"], "outboundTestUrl": "x"}
            return self._json({"success": True, "obj": json.dumps(obj)})
        if api == "/xray/update":
            st.template = json.loads(form["xraySetting"])
            return self._json({"success": True})
        if api == "/xray/routeTest":
            dom = form.get("domain", "")
            for r in st.template["routing"]["rules"]:
                for d in r.get("domain", []):
                    if d.startswith("domain:") and (dom == d[7:] or dom.endswith("." + d[7:])):
                        return self._json({"success": True, "obj": {"matched": True, "outboundTag": r["outboundTag"]}})
            return self._json({"success": True, "obj": {"matched": False, "outboundTag": ""}})
        if api == "/server/getConfigJson":
            return self._json({"success": True, "obj": st.template})
        if api == "/server/getNewX25519Cert":
            return self._json({"success": True, "obj": {"privateKey": "PRIV-new", "publicKey": "PUB-new"}})
        if api == "/server/scanRealityTarget":
            return self._json({"success": True, "obj": {"feasible": True, "target": form.get("target")}})
        if api == "/server/getDb":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", "attachment; filename=x-ui.db")
            self.send_header("Content-Length", str(len(st.db)))
            self.end_headers()
            self.wfile.write(st.db)
            return
        if api == "/server/importDB":
            ctype = self.headers.get("Content-Type", "")
            assert "multipart/form-data" in ctype
            assert b'name="db"' in raw and b'name="keepHostSettings"' in raw
            boundary = ("--" + ctype.split("boundary=", 1)[1].strip('"')).encode()
            for part in raw.split(boundary):
                if b'name="db"' in part:
                    body = part.split(b"\r\n\r\n", 1)[1]
                    st.imported = body[:-2] if body.endswith(b"\r\n") else body
            return self._json({"success": True, "msg": "imported"})
        return self._json({"success": False, "msg": f"mock: no route {method} {api}"}, 404)


def start() -> tuple[ThreadingHTTPServer, State, int]:
    state = State()
    handler = type("H", (Handler,), {"state": state})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state, srv.server_address[1]
