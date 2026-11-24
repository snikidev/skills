"""Pure helpers for clients (users): payloads, units, links, tables."""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import uuid
from typing import Any, Optional

GIB = 1024 ** 3


def parse_cap(cap: Optional[str]) -> int:
    """'50G'/'50GB'/'0'/'unlimited' -> bytes. 3x-ui stores totalGB in BYTES
    (openapi example 53687091200 = 50 GiB); 0 means unlimited."""
    if cap is None:
        return 0
    s = cap.strip().lower()
    if s in ("", "0", "none", "unlimited"):
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|gb|gib|t|tb|tib|m|mb|mib)?", s)
    if not m:
        raise ValueError(f"bad cap {cap!r}; use e.g. 50G, 1T, 500M or 0")
    n = float(m.group(1))
    unit = (m.group(2) or "g")[0]
    mult = {"m": 1024 ** 2, "g": GIB, "t": 1024 ** 4}[unit]
    return int(n * mult)


def parse_expiry(expiry: Optional[str], now: Optional[dt.datetime] = None) -> int:
    """'30d' / '2027-01-31' / '0' -> epoch milliseconds (3x-ui expiryTime). 0 = never."""
    if expiry is None:
        return 0
    s = expiry.strip().lower()
    if s in ("", "0", "never", "none"):
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    m = re.fullmatch(r"(\d+)\s*d", s)
    if m:
        return int((now + dt.timedelta(days=int(m.group(1)))).timestamp() * 1000)
    try:
        d = dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise ValueError(f"bad expiry {expiry!r}; use 30d, 2027-01-31 or 0") from exc
    return int(d.timestamp() * 1000)


def fmt_bytes(n: Optional[int]) -> str:
    if not n:
        return "0"
    for unit, size in (("TiB", 1024 ** 4), ("GiB", GIB), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if n >= size:
            return f"{n / size:.2f} {unit}"
    return f"{n} B"


def fmt_cap(n: Optional[int]) -> str:
    return fmt_bytes(n) if n else "unlimited"


def fmt_expiry(ms: Optional[int]) -> str:
    if not ms:
        return "never"
    if ms < 0:
        return f"{-ms // 86400000}d after first use"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def valid_email(email: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._@+-]{1,64}", email or ""):
        raise ValueError("user name (3x-ui 'email') must be 1-64 chars of A-Z a-z 0-9 . _ @ + -")
    return email


def new_client(email: str, cap_bytes: int, expiry_ms: int, flow: str,
               limit_ip: int = 0, comment: str = "") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "email": valid_email(email),
        "flow": flow,
        "totalGB": cap_bytes,
        "expiryTime": expiry_ms,
        "limitIp": limit_ip,
        "enable": True,
        "tgId": 0,
        "subId": uuid.uuid4().hex[:16],
        "comment": comment,
    }


RECORD_TO_CLIENT = {
    # ClientRecord (GET /clients/get, /clients/list) -> model.Client (update body)
    "uuid": "id",
    "email": "email",
    "flow": "flow",
    "totalGB": "totalGB",
    "expiryTime": "expiryTime",
    "limitIp": "limitIp",
    "limitHwid": "limitHwid",
    "enable": "enable",
    "tgId": "tgId",
    "subId": "subId",
    "comment": "comment",
    "group": "group",
    "reset": "reset",
    "resetDay": "resetDay",
    "resetWeekday": "resetWeekday",
    "resetMax": "resetMax",
    "trafficReset": "trafficReset",
    "trafficResetDay": "trafficResetDay",
    "security": "security",
    "password": "password",
}


def record_to_update_body(record: dict[str, Any]) -> dict[str, Any]:
    """The update endpoint REPLACES the row, so send every field we know.
    Losing 'id' (uuid) would invalidate the user's link."""
    body = {}
    for src, dst in RECORD_TO_CLIENT.items():
        if src in record and record[src] not in (None, ""):
            body[dst] = record[src]
    if "id" not in body:
        raise ValueError("client record has no uuid; refusing to update (link would change)")
    return body


def client_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalise one /clients/list item ({...record, inboundIds, traffic})."""
    rec = entry.get("client", entry)
    traffic = entry.get("traffic") or {}
    used = int(traffic.get("up", 0) or 0) + int(traffic.get("down", 0) or 0)
    return {
        "email": rec.get("email", ""),
        "enable": bool(rec.get("enable", True)),
        "used": used,
        "cap": int(rec.get("totalGB", 0) or 0),
        "expiry": int(rec.get("expiryTime", 0) or 0),
        "inbounds": entry.get("inboundIds", []),
        "uuid": rec.get("uuid") or rec.get("id") or "",
    }


def table(rows: list[dict[str, Any]]) -> str:
    out = [f"{'USER':<24} {'ON':<3} {'USED':>12} {'CAP':>12}  {'EXPIRES':<22} INBOUNDS"]
    for r in rows:
        cap = fmt_bytes(r["cap"]) if r["cap"] else "unlimited"
        out.append(
            f"{r['email']:<24} {'yes' if r['enable'] else 'NO':<3} {fmt_bytes(r['used']):>12} "
            f"{cap:>12}  {fmt_expiry(r['expiry']):<22} {','.join(map(str, r['inbounds']))}"
        )
    return "\n".join(out)


def reality_params(inbound: dict[str, Any]) -> dict[str, str]:
    ss = inbound.get("streamSettings") or {}
    rs = ss.get("realitySettings") or {}
    inner = rs.get("settings") or {}
    names = rs.get("serverNames") or []
    sids = rs.get("shortIds") or []
    return {
        "network": ss.get("network", "tcp"),
        "security": ss.get("security", ""),
        "pbk": inner.get("publicKey", ""),
        "fp": inner.get("fingerprint", "chrome") or "chrome",
        "spx": inner.get("spiderX", "/") or "/",
        "sni": names[0] if names else "",
        "sid": sids[0] if sids else "",
        "target": rs.get("target") or rs.get("dest") or "",
    }


def vless_link(inbound: dict[str, Any], client_uuid: str, flow: str, host: str, name: str) -> str:
    p = reality_params(inbound)
    if p["security"] != "reality" or not p["pbk"]:
        raise ValueError("inbound is not a Reality inbound with a public key")
    query = {
        "type": p["network"],
        "encryption": "none",
        "security": "reality",
        "pbk": p["pbk"],
        "fp": p["fp"],
        "sni": p["sni"],
        "sid": p["sid"],
        "spx": p["spx"],
    }
    if flow:
        query["flow"] = flow
    q = urllib.parse.urlencode(query)
    return f"vless://{client_uuid}@{host}:{inbound.get('port')}?{q}#{urllib.parse.quote(name)}"
