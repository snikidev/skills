#!/usr/bin/env python3
"""Create VLESS Reality and/or Shadowsocks inbounds via the 3x-ui API.

Idempotent: if an inbound with the same protocol+port already exists, it is
left alone unless --force is passed (which is still non-destructive — --force
refuses to overwrite and tells you to delete the inbound in the panel first).

Does not store credentials. Reads PANEL_BASE_URL and XUI_API_TOKEN or
XUI_USERNAME / XUI_PASSWORD from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any

# Allow `python3 scripts/configure-inbounds.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from xui_api import XUIClient, XUIError, find_inbound  # noqa: E402


DEFAULT_DEST = "www.microsoft.com:443"
DEFAULT_SNI = "www.microsoft.com"
SS_METHOD = "chacha20-ietf-poly1305"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add VLESS Reality and/or Shadowsocks inbounds through the 3x-ui API."
    )
    parser.add_argument(
        "--protocols",
        default=_env("PROTOCOLS", "both"),
        choices=("vless-reality", "shadowsocks", "both"),
        help="Which inbounds to create (default: both, or $PROTOCOLS).",
    )
    parser.add_argument("--vless-port", type=int, default=int(_env("VLESS_PORT", "443")))
    parser.add_argument("--ss-port", type=int, default=int(_env("SS_PORT", "8388")))
    parser.add_argument(
        "--dest",
        default=_env("REALITY_DEST", DEFAULT_DEST),
        help="Reality target host:port (donor site). Default: www.microsoft.com:443",
    )
    parser.add_argument(
        "--sni",
        default=_env("REALITY_SNI", DEFAULT_SNI),
        help="Reality serverName / SNI. Default: www.microsoft.com",
    )
    parser.add_argument(
        "--ss-method",
        default=_env("SS_METHOD", SS_METHOD),
        help="Shadowsocks cipher. Outline clients need chacha20-ietf-poly1305.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Error out instead of skipping when a matching inbound already exists.",
    )
    parser.add_argument(
        "--state-out",
        default=_env("STATE_OUT", ""),
        help="Write generated ids/keys/passwords as JSON to this path (mode 600).",
    )
    return parser.parse_args()


def want_vless(protocols: str) -> bool:
    return protocols in {"vless-reality", "both"}


def want_ss(protocols: str) -> bool:
    return protocols in {"shadowsocks", "both"}


def random_short_id() -> str:
    # 8 bytes / 16 hex chars — accepted by Reality and common in clients.
    return secrets.token_hex(8)


def random_sub_id() -> str:
    return secrets.token_hex(8)


def random_ss_password() -> str:
    # URL-and-config-safe, 24 raw bytes ~ 32 chars base64 without padding issues.
    return secrets.token_urlsafe(24)


def vless_payload(
    *,
    port: int,
    dest: str,
    sni: str,
    uuid_str: str,
    private_key: str,
    public_key: str,
    short_id: str,
) -> dict[str, Any]:
    # Shape taken from 3x-ui v3.11.0 golden fixture
    # frontend/src/test/golden/fixtures/inbound-full/vless-tcp-reality.json
    # mldsa65 / minClientVer / maxClientVer left empty on purpose: populated
    # post-quantum fields break many current clients (see the sniki.dev guide).
    return {
        "enable": True,
        "remark": "VLESS-Reality-443",
        "listen": "",
        "port": port,
        "protocol": "vless",
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "clients": [
                {
                    "id": uuid_str,
                    "email": "vless-1",
                    "flow": "xtls-rprx-vision",
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": 0,
                    "subId": random_sub_id(),
                    "comment": "",
                    "reset": 0,
                }
            ],
            "decryption": "none",
            "encryption": "none",
        },
        "streamSettings": {
            "network": "tcp",
            "tcpSettings": {"header": {"type": "none"}},
            "security": "reality",
            "realitySettings": {
                "show": False,
                "xver": 0,
                "target": dest,
                "serverNames": [sni],
                "privateKey": private_key,
                "minClientVer": "",
                "maxClientVer": "",
                "maxTimediff": 0,
                "shortIds": [short_id],
                "mldsa65Seed": "",
                "settings": {
                    "publicKey": public_key,
                    "fingerprint": "chrome",
                    "serverName": "",
                    "spiderX": "/",
                    "mldsa65Verify": "",
                },
            },
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
            "metadataOnly": False,
            "routeOnly": False,
        },
    }


def ss_payload(*, port: int, method: str, password: str) -> dict[str, Any]:
    # Single-user AEAD-2018 inbound: inbound-level method+password are
    # authoritative (3x-ui inbound shadowsocks schema). Do not use
    # 2022-blake3-* — the official Outline client does not support them.
    return {
        "enable": True,
        "remark": "SS-Outline-8388",
        "listen": "",
        "port": port,
        "protocol": "shadowsocks",
        "expiryTime": 0,
        "total": 0,
        "settings": {
            "method": method,
            "password": password,
            "network": "tcp,udp",
            "clients": [
                {
                    "method": "",
                    "password": "",
                    "email": "outline-1",
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": 0,
                    "subId": random_sub_id(),
                    "comment": "Outline-compatible AEAD-2018",
                    "reset": 0,
                }
            ],
            "ivCheck": False,
        },
        "streamSettings": {
            "network": "tcp",
            "tcpSettings": {"header": {"type": "none"}},
            "security": "none",
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
            "metadataOnly": False,
            "routeOnly": False,
        },
    }


def extract_existing_vless(inbound: dict[str, Any]) -> dict[str, Any]:
    settings = inbound.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)
    stream = inbound.get("streamSettings") or {}
    if isinstance(stream, str):
        stream = json.loads(stream)
    clients = settings.get("clients") or []
    client = clients[0] if clients else {}
    reality = stream.get("realitySettings") or {}
    client_half = reality.get("settings") or {}
    short_ids = reality.get("shortIds") or []
    return {
        "uuid": client.get("id"),
        "privateKey": reality.get("privateKey"),
        "publicKey": client_half.get("publicKey"),
        "shortId": short_ids[0] if short_ids else None,
        "dest": reality.get("target") or reality.get("dest"),
        "sni": (reality.get("serverNames") or [None])[0],
        "inboundId": inbound.get("id"),
    }


def extract_existing_ss(inbound: dict[str, Any]) -> dict[str, Any]:
    settings = inbound.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)
    return {
        "method": settings.get("method"),
        "password": settings.get("password"),
        "inboundId": inbound.get("id"),
        "port": inbound.get("port"),
    }


def write_state(path: str, state: dict[str, Any]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    os.chmod(dest, 0o600)
    print(f"Wrote inbound state to {dest} (mode 600)", file=sys.stderr)


def main() -> int:
    args = parse_args()
    if args.ss_method.startswith("2022-blake3"):
        print(
            "Refusing Shadowsocks-2022 ciphers: the official Outline client "
            "does not support them. Use chacha20-ietf-poly1305.",
            file=sys.stderr,
        )
        return 2

    client = XUIClient.from_env()
    if not client.token:
        client.login()

    existing = client.list_inbounds()
    state: dict[str, Any] = {
        "dest": args.dest,
        "sni": args.sni,
        "vlessPort": args.vless_port,
        "ssPort": args.ss_port,
        "ssMethod": args.ss_method,
        "created": {},
        "reused": {},
    }

    if want_vless(args.protocols):
        found = find_inbound(existing, protocol="vless", port=args.vless_port)
        if found:
            if args.force:
                raise XUIError(
                    f"VLESS inbound already exists on port {args.vless_port} "
                    f"(id={found.get('id')}). Delete it in the panel or omit --force."
                )
            print(
                f"Reusing existing VLESS inbound id={found.get('id')} "
                f"on port {args.vless_port}",
                file=sys.stderr,
            )
            state["reused"]["vless"] = extract_existing_vless(found)
            state["vless"] = state["reused"]["vless"]
        else:
            keys = client.get_x25519()
            short_id = random_short_id()
            uuid_str = str(uuid.uuid4())
            payload = vless_payload(
                port=args.vless_port,
                dest=args.dest,
                sni=args.sni,
                uuid_str=uuid_str,
                private_key=keys["privateKey"],
                public_key=keys["publicKey"],
                short_id=short_id,
            )
            result = client.add_inbound(payload)
            inbound_id = (result.get("obj") or {}).get("id") if isinstance(
                result.get("obj"), dict
            ) else None
            print(f"Created VLESS Reality inbound id={inbound_id}", file=sys.stderr)
            state["created"]["vless"] = True
            state["vless"] = {
                "uuid": uuid_str,
                "privateKey": keys["privateKey"],
                "publicKey": keys["publicKey"],
                "shortId": short_id,
                "dest": args.dest,
                "sni": args.sni,
                "inboundId": inbound_id,
            }

    if want_ss(args.protocols):
        found = find_inbound(existing, protocol="shadowsocks", port=args.ss_port)
        if found:
            if args.force:
                raise XUIError(
                    f"Shadowsocks inbound already exists on port {args.ss_port} "
                    f"(id={found.get('id')}). Delete it in the panel or omit --force."
                )
            print(
                f"Reusing existing Shadowsocks inbound id={found.get('id')} "
                f"on port {args.ss_port}",
                file=sys.stderr,
            )
            state["reused"]["shadowsocks"] = extract_existing_ss(found)
            state["shadowsocks"] = state["reused"]["shadowsocks"]
        else:
            password = random_ss_password()
            payload = ss_payload(
                port=args.ss_port, method=args.ss_method, password=password
            )
            result = client.add_inbound(payload)
            inbound_id = (result.get("obj") or {}).get("id") if isinstance(
                result.get("obj"), dict
            ) else None
            print(
                f"Created Shadowsocks inbound id={inbound_id} "
                f"(method={args.ss_method})",
                file=sys.stderr,
            )
            state["created"]["shadowsocks"] = True
            state["shadowsocks"] = {
                "method": args.ss_method,
                "password": password,
                "inboundId": inbound_id,
                "port": args.ss_port,
            }

    # Adding an inbound usually reloads Xray, but a restart is cheap insurance
    # after a batch of creates.
    try:
        client.restart_xray()
        print("Restarted Xray", file=sys.stderr)
    except XUIError as exc:
        print(f"Warning: restartXrayService: {exc}", file=sys.stderr)

    if args.state_out:
        write_state(args.state_out, state)
    else:
        # Print state to stdout so make-links.sh can consume it. Callers
        # should redirect this to a mode-600 file, not to a chat log.
        json.dump(state, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except XUIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
