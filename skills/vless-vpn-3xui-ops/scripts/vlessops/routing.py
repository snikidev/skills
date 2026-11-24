"""Pure functions over the Xray config template (no I/O): rules and outbounds."""

from __future__ import annotations

import copy
import difflib
import json
from typing import Any

MATCH_KEYS = ("domain", "ip", "port", "network", "protocol", "inboundTag", "source", "user")
PROTECTED_TAGS = {"api"}  # never touch the panel's own API rule


def parse_matcher(matcher: str) -> tuple[str, str]:
    """'domain:openrouter.ai' -> ('domain', 'domain:openrouter.ai').
    'geosite:openai' -> ('domain', ...). 'ip:1.2.3.0/24' / 'geoip:xx' -> ('ip', ...)."""
    m = matcher.strip()
    if not m:
        raise ValueError("empty matcher")
    lower = m.lower()
    if lower.startswith(("domain:", "full:", "regexp:", "keyword:", "geosite:")):
        return "domain", m
    if lower.startswith("geoip:"):
        return "ip", m
    if lower.startswith("ip:"):
        return "ip", m[3:]
    raise ValueError(
        f"unsupported matcher {matcher!r}; use domain:/full:/keyword:/regexp:/geosite:/geoip:/ip:"
    )


def outbound_tags(template: dict[str, Any]) -> list[str]:
    return [o.get("tag", "") for o in template.get("outbounds", [])]


def default_outbound(template: dict[str, Any]) -> str:
    tags = outbound_tags(template)
    return tags[0] if tags else ""


def rules(template: dict[str, Any]) -> list[dict[str, Any]]:
    return list(template.get("routing", {}).get("rules", []))


def describe_rule(rule: dict[str, Any]) -> str:
    parts = []
    for k in MATCH_KEYS:
        if k in rule:
            v = rule[k]
            parts.append(f"{k}={','.join(map(str, v)) if isinstance(v, list) else v}")
    target = rule.get("outboundTag") or (f"balancer:{rule['balancerTag']}" if rule.get("balancerTag") else "?")
    return f"{' '.join(parts) or '(match-all)'} -> {target}"


def find_rule(template: dict[str, Any], matcher: str) -> list[int]:
    key, value = parse_matcher(matcher)
    hits = []
    for i, r in enumerate(rules(template)):
        if value in (r.get(key) or []):
            hits.append(i)
    return hits


def add_rule(template: dict[str, Any], matcher: str, outbound: str,
             position: str = "before-catchall") -> tuple[dict[str, Any], str]:
    """Return (new_template, message). Idempotent: if the matcher already routes
    to `outbound`, returns an unchanged copy. If it routes elsewhere, raises."""
    if outbound not in outbound_tags(template):
        raise ValueError(f"outbound {outbound!r} does not exist; have {outbound_tags(template)}")
    key, value = parse_matcher(matcher)
    new = copy.deepcopy(template)
    rl = new.setdefault("routing", {}).setdefault("rules", [])
    for r in rl:
        if value in (r.get(key) or []):
            if r.get("outboundTag") == outbound:
                return new, f"already present: {describe_rule(r)} (no change)"
            raise ValueError(
                f"{value} is already routed by: {describe_rule(r)}. Remove it first."
            )
    rule = {"type": "field", key: [value], "outboundTag": outbound}
    # Insert after the panel's api rule(s) so the api rule keeps priority.
    idx = 0
    for i, r in enumerate(rl):
        if set(r.get("inboundTag") or []) & PROTECTED_TAGS:
            idx = i + 1
    if position == "end":
        idx = len(rl)
    rl.insert(idx, rule)
    return new, f"added at index {idx}: {describe_rule(rule)}"


def remove_rule(template: dict[str, Any], matcher: str) -> tuple[dict[str, Any], str]:
    key, value = parse_matcher(matcher)
    new = copy.deepcopy(template)
    rl = new.get("routing", {}).get("rules", [])
    msgs = []
    keep = []
    for r in rl:
        vals = r.get(key) or []
        if value in vals and not (set(r.get("inboundTag") or []) & PROTECTED_TAGS):
            if len(vals) == 1:
                msgs.append(f"removed rule: {describe_rule(r)}")
                continue
            r = dict(r)
            r[key] = [v for v in vals if v != value]
            msgs.append(f"removed {value} from rule, now: {describe_rule(r)}")
        keep.append(r)
    if not msgs:
        return new, f"{value} not found (no change)"
    new["routing"]["rules"] = keep
    return new, "; ".join(msgs)


def redact_template(template: dict[str, Any]) -> dict[str, Any]:
    """Copy with outbound credentials masked, safe to print or diff."""
    t = copy.deepcopy(template)
    for ob in t.get("outbounds", []):
        settings = ob.get("settings") or {}
        for srv in settings.get("servers", []) or []:
            for u in srv.get("users", []) or []:
                if "pass" in u:
                    u["pass"] = "<redacted>"
                if "user" in u:
                    u["user"] = "<redacted>"
            if "password" in srv:
                srv["password"] = "<redacted>"
        for v in settings.get("vnext", []) or []:
            for u in v.get("users", []) or []:
                if "id" in u:
                    u["id"] = "<redacted>"
    return t


def diff(old: dict[str, Any], new: dict[str, Any], label: str = "xray template") -> list[str]:
    a = json.dumps(redact_template(old), indent=2, sort_keys=True).splitlines()
    b = json.dumps(redact_template(new), indent=2, sort_keys=True).splitlines()
    return list(difflib.unified_diff(a, b, f"live {label}", f"proposed {label}", lineterm="", n=2))
