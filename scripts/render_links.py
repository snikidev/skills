#!/usr/bin/env python3
"""Render vless:// and ss:// share links from configure-inbounds.py state JSON."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 7:
        print(
            "usage: render_links.py PUBLIC_IP STATE_FILE OUT_DIR VLESS_PORT SS_PORT SNI",
            file=sys.stderr,
        )
        return 2
    public_ip, state_file, out_dir, vless_port, ss_port, sni = sys.argv[1:]
    state = json.loads(Path(state_file).read_text(encoding="utf-8"))

    links: list[str] = []
    vless = state.get("vless") or {}
    if vless.get("uuid") and vless.get("publicKey") and vless.get("shortId"):
        sni_value = vless.get("sni") or sni
        query = urllib.parse.urlencode(
            {
                "type": "tcp",
                "encryption": "none",
                "security": "reality",
                "pbk": vless["publicKey"],
                "fp": "chrome",
                "sni": sni_value,
                "sid": vless["shortId"],
                "spx": "/",
                "flow": "xtls-rprx-vision",
            }
        )
        links.append(
            f"vless://{vless['uuid']}@{public_ip}:{vless_port}?{query}#VLESS-Reality"
        )

    ss = state.get("shadowsocks") or {}
    if ss.get("password") and ss.get("method"):
        userinfo = f"{ss['method']}:{ss['password']}"
        token = base64.b64encode(userinfo.encode()).decode().rstrip("=")
        port = ss.get("port") or ss_port
        links.append(f"ss://{token}@{public_ip}:{port}#Outline-SS")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "links.txt"
    dest.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
    os.chmod(dest, 0o600)
    if links:
        print("\n".join(links))
    else:
        print("warning: no links generated from STATE_FILE", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
