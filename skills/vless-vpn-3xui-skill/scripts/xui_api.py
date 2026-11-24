#!/usr/bin/env python3
"""Minimal 3x-ui HTTP API client (stdlib only).

Verified against MHSanaei/3x-ui v3.11.0 official docs and
frontend/src/pages/api-docs/endpoints.ts (read 2026-11-23):

  POST /login
  GET  /csrf-token          (cookie sessions; Bearer callers can skip CSRF)
  GET  /panel/api/inbounds/list
  POST /panel/api/inbounds/add
  GET  /panel/api/inbounds/allLinks
  POST /panel/api/xray/                    (read template)
  POST /panel/api/xray/update              (form: xraySetting, outboundTestUrl?)
  POST /panel/api/server/restartXrayService
  GET  /panel/api/server/getNewX25519Cert
  GET  /panel/api/xray/getXrayResult

All of these are served under the panel web base path, e.g.
http://127.0.0.1:2053/<webBasePath>/panel/api/inbounds/add

This client has not been run against a live panel. See
references/api-and-unverified.md.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any, Optional


class XUIError(RuntimeError):
    pass


def mask_secret(value: str, keep: int = 2) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


def join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


class XUIClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
        insecure_tls: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or None
        self.username = username
        self.password = password
        self.timeout = timeout
        self.cookie_jar = CookieJar()
        self._csrf: Optional[str] = None
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        if insecure_tls:
            ctx = ssl._create_unverified_context()
            self._opener.add_handler(urllib.request.HTTPSHandler(context=ctx))

    @classmethod
    def from_env(cls) -> "XUIClient":
        base = os.environ.get("PANEL_BASE_URL", "").strip()
        if not base:
            raise XUIError(
                "PANEL_BASE_URL is required, e.g. "
                "http://127.0.0.1:2053/<webBasePath>"
            )
        token = os.environ.get("XUI_API_TOKEN", "").strip() or None
        username = os.environ.get("XUI_USERNAME", "").strip() or None
        password = os.environ.get("XUI_PASSWORD", "").strip() or None
        insecure = os.environ.get("PANEL_INSECURE_TLS", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if not token and not (username and password):
            raise XUIError(
                "Set XUI_API_TOKEN, or both XUI_USERNAME and XUI_PASSWORD"
            )
        return cls(
            base,
            token=token,
            username=username,
            password=password,
            insecure_tls=insecure,
        )

    def login(self) -> None:
        if self.token:
            return
        body = {
            "username": self.username,
            "password": self.password,
        }
        data = self.request("POST", "/login", json_body=body, auth=False)
        if not data.get("success", False):
            raise XUIError(f"login failed: {data.get('msg', data)}")
        self._csrf = self._fetch_csrf()

    def _fetch_csrf(self) -> Optional[str]:
        try:
            data = self.request("GET", "/csrf-token", auth=False)
        except XUIError:
            return None
        obj = data.get("obj")
        if isinstance(obj, str) and obj:
            return obj
        return None

    def request(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        form: Optional[dict[str, str]] = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        url = join_url(self.base_url, path)
        headers = {"Accept": "application/json"}
        data: Optional[bytes] = None
        if json_body is not None:
            raw = json.dumps(json_body).encode("utf-8")
            data = raw
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif auth and self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                payload = resp.read()
                status = resp.getcode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise XUIError(f"{method} {path} HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise XUIError(f"{method} {path} failed: {exc}") from exc
        if not payload:
            if status and status < 300:
                return {"success": True, "obj": None}
            raise XUIError(f"{method} {path} empty response (HTTP {status})")
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            snippet = payload.decode("utf-8", errors="replace")[:400]
            raise XUIError(
                f"{method} {path} returned non-JSON: {snippet}"
            ) from exc
        if not isinstance(parsed, dict):
            return {"success": True, "obj": parsed}
        return parsed

    def require_success(self, data: dict[str, Any], action: str) -> dict[str, Any]:
        if data.get("success") is False:
            raise XUIError(f"{action} failed: {data.get('msg', data)}")
        return data

    def list_inbounds(self) -> list[dict[str, Any]]:
        data = self.require_success(
            self.request("GET", "/panel/api/inbounds/list"), "list inbounds"
        )
        obj = data.get("obj") or []
        if not isinstance(obj, list):
            raise XUIError(f"unexpected inbounds list shape: {type(obj)}")
        return obj

    def add_inbound(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.require_success(
            self.request("POST", "/panel/api/inbounds/add", json_body=payload),
            "add inbound",
        )

    def all_links(self) -> list[str]:
        data = self.require_success(
            self.request("GET", "/panel/api/inbounds/allLinks"), "allLinks"
        )
        obj = data.get("obj") or []
        if obj is None:
            return []
        if not isinstance(obj, list):
            raise XUIError(f"unexpected allLinks shape: {type(obj)}")
        return [str(item) for item in obj]

    def get_x25519(self) -> dict[str, str]:
        data = self.require_success(
            self.request("GET", "/panel/api/server/getNewX25519Cert"),
            "getNewX25519Cert",
        )
        obj = data.get("obj") or {}
        private_key = obj.get("privateKey") or obj.get("private_key")
        public_key = obj.get("publicKey") or obj.get("public_key") or obj.get(
            "password"
        )
        if not private_key or not public_key:
            raise XUIError(f"getNewX25519Cert missing keys: {list(obj)}")
        return {"privateKey": str(private_key), "publicKey": str(public_key)}

    def get_xray_template(self) -> dict[str, Any]:
        # Official docs: POST /panel/api/xray/ returns obj.xraySetting as a
        # JSON *string* of the raw Xray config template.
        data = self.require_success(
            self.request("POST", "/panel/api/xray/"), "get xray template"
        )
        obj = data.get("obj") or {}
        setting = obj.get("xraySetting", obj)
        if isinstance(setting, str):
            try:
                setting = json.loads(setting)
            except json.JSONDecodeError as exc:
                raise XUIError("xraySetting was not valid JSON") from exc
        if not isinstance(setting, dict):
            raise XUIError(f"unexpected xraySetting shape: {type(setting)}")
        # Some panel versions have wrapped the template in another object.
        if "outbounds" not in setting and isinstance(
            setting.get("xraySetting"), (str, dict)
        ):
            inner = setting["xraySetting"]
            if isinstance(inner, str):
                inner = json.loads(inner)
            setting = inner
        if "outbounds" not in setting:
            raise XUIError(
                "xraySetting has no outbounds array; inspect the panel response "
                "before merging. See references/api-and-unverified.md."
            )
        return setting

    def update_xray_template(
        self, template: dict[str, Any], outbound_test_url: Optional[str] = None
    ) -> dict[str, Any]:
        form = {"xraySetting": json.dumps(template, ensure_ascii=False)}
        if outbound_test_url:
            form["outboundTestUrl"] = outbound_test_url
        return self.require_success(
            self.request("POST", "/panel/api/xray/update", form=form),
            "update xray template",
        )

    def restart_xray(self) -> dict[str, Any]:
        return self.require_success(
            self.request("POST", "/panel/api/server/restartXrayService"),
            "restart Xray",
        )

    def xray_result(self) -> Any:
        data = self.require_success(
            self.request("GET", "/panel/api/xray/getXrayResult"), "getXrayResult"
        )
        return data.get("obj", data.get("msg"))


def find_inbound(
    inbounds: list[dict[str, Any]], *, protocol: str, port: int
) -> Optional[dict[str, Any]]:
    for item in inbounds:
        try:
            item_port = int(item.get("port"))
        except (TypeError, ValueError):
            continue
        if item.get("protocol") == protocol and item_port == port:
            return item
    return None
