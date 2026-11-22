#!/usr/bin/env python3
"""Insert a SOCKS5 ISP-proxy outbound into the 3x-ui Xray template.

Places the outbound (default tag: iproyal) first in `outbounds`, so unmatched
traffic uses it as Xray's default outbound. Rewrites the template's
`geoip:private` routing rule to the `direct` freedom outbound, and loosens
that outbound's `finalRules` so the rule actually works (3x-ui v3.6+ blocks
private destinations inside freedom as SSRF hardening).

Idempotent: an existing outbound with the same tag is updated and moved to
index 0 rather than duplicated.

Reads PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, and optional PROXY_TAG
from the environment. Never prints the password.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xui_api import XUIClient, XUIError, mask_secret  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add or update a SOCKS5 outbound in the 3x-ui Xray template."
    )
    parser.add_argument("--host", default=_env("PROXY_HOST"))
    parser.add_argument("--port", type=int, default=int(_env("PROXY_PORT", "12324") or "12324"))
    parser.add_argument("--user", default=_env("PROXY_USER"))
    parser.add_argument("--password", default=_env("PROXY_PASS"))
    parser.add_argument("--tag", default=_env("PROXY_TAG", "iproyal") or "iproyal")
    parser.add_argument(
        "--no-doh",
        action="store_true",
        help="Do not add a DNS section that sends DoH through the default outbound.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the merged template (secrets redacted) and do not save.",
    )
    return parser.parse_args()


def socks_outbound(tag: str, host: str, port: int, user: str, password: str) -> dict[str, Any]:
    server: dict[str, Any] = {"address": host, "port": port}
    if user or password:
        server["users"] = [{"user": user, "pass": password}]
    # Official Xray + 3x-ui v3.11 socks outbound shape (servers[].users[]).
    return {
        "tag": tag,
        "protocol": "socks",
        "settings": {"servers": [server]},
    }


def ensure_private_goes_direct(template: dict[str, Any]) -> None:
    routing = template.setdefault("routing", {})
    rules = list(routing.get("rules") or [])
    updated = False
    for rule in rules:
        ips = rule.get("ip") or []
        if not isinstance(ips, list):
            continue
        if "geoip:private" in ips and len(ips) == 1:
            rule["outboundTag"] = "direct"
            rule["type"] = rule.get("type") or "field"
            updated = True
            break
    if not updated:
        # Keep the panel's api rule first; insert private->direct just after
        # any inboundTag=api rule, otherwise at the front.
        insert_at = 0
        for idx, rule in enumerate(rules):
            if rule.get("outboundTag") == "api" or "api" in (rule.get("inboundTag") or []):
                insert_at = idx + 1
        rules.insert(
            insert_at,
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
        )
    routing["rules"] = rules


def allow_private_on_direct(template: dict[str, Any]) -> None:
    """3x-ui v3.6+ ships freedom finalRules that block geoip:private.

    If we route private destinations to `direct` without changing that, the
    rule is a no-op and those connections still die in the freedom outbound.
    This replaces a default block-then-allow pair with allow-all for the
    `direct` tag only. BitTorrent and anything you still want dropped stays
    on the `blocked` blackhole rule.
    """
    for outbound in template.get("outbounds") or []:
        if outbound.get("tag") != "direct" or outbound.get("protocol") != "freedom":
            continue
        settings = outbound.setdefault("settings", {})
        settings["finalRules"] = [{"action": "allow"}]
        return


def ensure_doh(template: dict[str, Any], proxy_tag: str) -> None:
    if "dns" in template and template["dns"]:
        return
    # Queries tagged this way re-enter routing; with the SOCKS outbound as
    # the default (index 0), they egress through the ISP proxy instead of
    # leaking the VPS datacentre IP to a resolver.
    template["dns"] = {
        "tag": "dns-internal",
        "queryStrategy": "UseIPv4",
        "servers": [
            "https://1.1.1.1/dns-query",
            "https://8.8.8.8/dns-query",
        ],
    }
    routing = template.setdefault("routing", {})
    rules = list(routing.get("rules") or [])
    already = any(
        "dns-internal" in (rule.get("inboundTag") or []) for rule in rules
    )
    if not already:
        rules.append(
            {
                "type": "field",
                "inboundTag": ["dns-internal"],
                "outboundTag": proxy_tag,
            }
        )
        routing["rules"] = rules


def place_outbound_first(template: dict[str, Any], outbound: dict[str, Any]) -> None:
    tag = outbound["tag"]
    others = [item for item in (template.get("outbounds") or []) if item.get("tag") != tag]
    template["outbounds"] = [outbound] + others


def redact(template: dict[str, Any]) -> dict[str, Any]:
    import copy

    redacted = copy.deepcopy(template)
    for outbound in redacted.get("outbounds") or []:
        servers = (outbound.get("settings") or {}).get("servers") or []
        for server in servers:
            for user in server.get("users") or []:
                if "pass" in user:
                    user["pass"] = mask_secret(str(user["pass"]))
    return redacted


def main() -> int:
    args = parse_args()
    missing = [name for name, val in (("host", args.host), ("user", args.user), ("password", args.password)) if not val]
    # Password-less / IP-whitelisted proxies are allowed if user and password
    # are both empty, but host is always required.
    if not args.host:
        print(
            "error: PROXY_HOST / --host is required. This is the human step: "
            "buy a static ISP proxy and paste the details. See references/human-proxy-step.md.",
            file=sys.stderr,
        )
        return 2
    if bool(args.user) != bool(args.password):
        print("error: provide both --user and --password, or neither (IP whitelist).", file=sys.stderr)
        return 2

    client = XUIClient.from_env()
    if not client.token:
        client.login()

    template = client.get_xray_template()
    outbound = socks_outbound(args.tag, args.host, args.port, args.user, args.password)
    place_outbound_first(template, outbound)
    ensure_private_goes_direct(template)
    allow_private_on_direct(template)
    if not args.no_doh:
        ensure_doh(template, args.tag)

    print(
        f"Prepared SOCKS outbound tag={args.tag} host={args.host} port={args.port} "
        f"user={args.user or '(none)'} pass={mask_secret(args.password)}",
        file=sys.stderr,
    )

    if args.dry_run:
        import json

        json.dump(redact(template), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    client.update_xray_template(template)
    print("Saved Xray template", file=sys.stderr)
    client.restart_xray()
    print("Restarted Xray", file=sys.stderr)
    try:
        result = client.xray_result()
        if result:
            print(f"Xray result: {result}", file=sys.stderr)
    except XUIError as exc:
        print(f"Warning: getXrayResult: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except XUIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
