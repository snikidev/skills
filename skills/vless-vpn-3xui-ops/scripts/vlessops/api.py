"""Panel API access, built on the setup skill's shared stdlib client.

Import order:
  1. ../../vless-vpn-3xui-skill/scripts/xui_api.py (monorepo checkout), so the
     two skills share one client and one set of fixes;
  2. scripts/_vendor/xui_api.py, a byte-identical copy (tests enforce this),
     so this skill still works when copied on its own.

Every endpoint below was checked against MHSanaei/3x-ui tag v3.11.0
(internal/web/controller/*.go and docs/public/openapi.json). See
references/api-endpoints.md.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[2] / "vless-vpn-3xui-skill" / "scripts"
_VENDOR = _HERE.parent / "_vendor"
SHARED_SOURCE = ""
for _candidate in (_SHARED, _VENDOR):
    if (_candidate / "xui_api.py").is_file():
        sys.path.insert(0, str(_candidate))
        SHARED_SOURCE = str(_candidate / "xui_api.py")
        break

from xui_api import XUIClient, XUIError  # noqa: E402

from .env import Config  # noqa: E402


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return value
    return value


class OpsClient(XUIClient):
    @classmethod
    def from_config(cls, cfg: Config, write: bool) -> "OpsClient":
        base = cfg.panel_base_url()
        token = None
        if not write and cfg.get("XUI_MONITOR_TOKEN"):
            token = cfg.get("XUI_MONITOR_TOKEN")
        elif cfg.get("XUI_API_TOKEN"):
            token = cfg.get("XUI_API_TOKEN")
        user = cfg.get("XUI_USERNAME")
        pw = cfg.get("XUI_PASSWORD")
        if not token and not (user and pw):
            raise SystemExit(
                "ERROR: no panel credential. Set XUI_API_TOKEN (admin) or "
                "XUI_USERNAME + XUI_PASSWORD in the env file."
            )
        client = cls(base, token=token, username=user, password=pw, timeout=30)
        client.login()
        return client

    # --- raw helpers not in the shared client -----------------------------
    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        elif self._csrf:
            h["X-CSRF-Token"] = self._csrf
        return h

    def get_bytes(self, path: str) -> bytes:
        url = self.base_url + path
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with self._opener.open(req, timeout=120) as resp:
                ctype = resp.headers.get("Content-Type", "")
                data = resp.read()
        except urllib.error.HTTPError as exc:
            raise XUIError(f"GET {path} HTTP {exc.code}") from exc
        if "json" in ctype:
            raise XUIError(f"GET {path} returned JSON instead of a file: {data[:300]!r}")
        return data

    def post_multipart(self, path: str, field: str, filename: str, data: bytes,
                       extra: Optional[dict[str, str]] = None) -> dict[str, Any]:
        boundary = "----vlessops" + uuid.uuid4().hex
        parts: list[bytes] = []
        for k, v in (extra or {}).items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
            )
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
             f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
            + data + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(self.base_url + path, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(req, timeout=300) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            raise XUIError(f"POST {path} HTTP {exc.code}") from exc
        try:
            return json.loads(payload.decode() or "{}")
        except json.JSONDecodeError:
            return {"success": True, "obj": None}

    # --- typed wrappers ---------------------------------------------------
    def server_status(self) -> dict[str, Any]:
        return self.require_success(self.request("GET", "/panel/api/server/status"), "status").get("obj") or {}

    def inbounds(self) -> list[dict[str, Any]]:
        out = []
        for ib in self.list_inbounds():
            ib = dict(ib)
            for k in ("settings", "streamSettings", "sniffing"):
                ib[k] = _maybe_json(ib.get(k))
            out.append(ib)
        return out

    def inbound(self, inbound_id: int) -> dict[str, Any]:
        ib = self.require_success(
            self.request("GET", f"/panel/api/inbounds/get/{inbound_id}"), "get inbound"
        ).get("obj") or {}
        for k in ("settings", "streamSettings", "sniffing"):
            ib[k] = _maybe_json(ib.get(k))
        return ib

    def update_inbound(self, inbound_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return self.require_success(
            self.request("POST", f"/panel/api/inbounds/update/{inbound_id}", json_body=body),
            "update inbound",
        )

    def clients(self) -> list[dict[str, Any]]:
        obj = self.require_success(self.request("GET", "/panel/api/clients/list"), "clients list").get("obj")
        return list(obj or [])

    def client(self, email: str) -> dict[str, Any]:
        q = urllib.parse.quote(email, safe="")
        return self.require_success(
            self.request("GET", f"/panel/api/clients/get/{q}"), "get client"
        ).get("obj") or {}

    def client_add(self, client: dict[str, Any], inbound_ids: list[int]) -> dict[str, Any]:
        return self.require_success(
            self.request("POST", "/panel/api/clients/add",
                         json_body={"client": client, "inboundIds": inbound_ids}),
            "add client",
        )

    def client_update(self, email: str, client: dict[str, Any]) -> dict[str, Any]:
        q = urllib.parse.quote(email, safe="")
        return self.require_success(
            self.request("POST", f"/panel/api/clients/update/{q}", json_body=client),
            "update client",
        )

    def client_delete(self, email: str, keep_traffic: bool) -> dict[str, Any]:
        q = urllib.parse.quote(email, safe="")
        suffix = "?keepTraffic=1" if keep_traffic else ""
        return self.require_success(
            self.request("POST", f"/panel/api/clients/del/{q}{suffix}"), "delete client"
        )

    def clients_set_enable(self, emails: list[str], enable: bool) -> dict[str, Any]:
        path = "/panel/api/clients/bulkEnable" if enable else "/panel/api/clients/bulkDisable"
        return self.require_success(
            self.request("POST", path, json_body={"emails": emails}), "bulk enable/disable"
        )

    def client_reset_traffic(self, email: str) -> dict[str, Any]:
        q = urllib.parse.quote(email, safe="")
        return self.require_success(
            self.request("POST", f"/panel/api/clients/resetTraffic/{q}"), "reset traffic"
        )

    def route_test(self, domain: str, port: int = 443, inbound_tag: str = "") -> dict[str, Any]:
        form = {"domain": domain, "port": str(port), "network": "tcp"}
        if inbound_tag:
            form["inboundTag"] = inbound_tag
        return self.require_success(
            self.request("POST", "/panel/api/xray/routeTest", form=form), "routeTest"
        ).get("obj") or {}

    def running_config(self) -> dict[str, Any]:
        obj = self.require_success(
            self.request("GET", "/panel/api/server/getConfigJson"), "getConfigJson"
        ).get("obj")
        return _maybe_json(obj) or {}
