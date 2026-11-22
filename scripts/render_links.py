#!/usr/bin/env python3
"""Render a vless:// share link from configure-inbounds.py state JSON."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: render_links.py PUBLIC_IP STATE_FILE OUT_DIR VLESS_PORT SNI",
            file=sys.stderr,
        )
        return 2
    public_ip, state_file, out_dir, vless_port, sni = sys.argv[1:]
    state = json.loads(Path(state_file).read_text(encoding="utf-8"))

    vless = state.get("vless") or {}
    if not (vless.get("uuid") and vless.get("publicKey") and vless.get("shortId")):
        print("warning: no VLESS link generated from STATE_FILE", file=sys.stderr)
        return 1

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
    link = f"vless://{vless['uuid']}@{public_ip}:{vless_port}?{query}#VLESS-Reality"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "links.txt"
    dest.write_text(link + "\n", encoding="utf-8")
    os.chmod(dest, 0o600)
    print(link)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
