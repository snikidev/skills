import datetime as dt
import json

import pytest

from vlessops import card, routing, users
from mock_panel import TEMPLATE, INBOUND


def test_add_rule_idempotent_and_after_api_rule():
    new, msg = routing.add_rule(TEMPLATE, "domain:openrouter.ai", "direct")
    assert new["routing"]["rules"][1] == {"type": "field", "domain": ["domain:openrouter.ai"], "outboundTag": "direct"}
    assert new["routing"]["rules"][0]["inboundTag"] == ["api"]
    again, msg2 = routing.add_rule(new, "domain:openrouter.ai", "direct")
    assert again == new and "no change" in msg2
    assert TEMPLATE["routing"]["rules"][1]["ip"] == ["geoip:private"]  # input untouched


def test_add_rule_conflict_and_unknown_outbound():
    new, _ = routing.add_rule(TEMPLATE, "domain:openrouter.ai", "direct")
    with pytest.raises(ValueError, match="already routed"):
        routing.add_rule(new, "domain:openrouter.ai", "iproyal")
    with pytest.raises(ValueError, match="does not exist"):
        routing.add_rule(TEMPLATE, "domain:x.ai", "warp")


def test_remove_rule_and_protects_api():
    new, _ = routing.add_rule(TEMPLATE, "domain:openrouter.ai", "direct")
    back, msg = routing.remove_rule(new, "domain:openrouter.ai")
    assert back == TEMPLATE and "removed" in msg
    same, msg = routing.remove_rule(TEMPLATE, "domain:nope.example")
    assert same == TEMPLATE and "not found" in msg


def test_diff_redacts_proxy_credentials():
    new, _ = routing.add_rule(TEMPLATE, "domain:openrouter.ai", "direct")
    text = "\n".join(routing.diff(TEMPLATE, new))
    assert "openrouter.ai" in text
    assert "proxypass-secret" not in json.dumps(routing.redact_template(TEMPLATE))


def test_caps_and_expiry():
    assert users.parse_cap("50G") == 53687091200  # matches 3x-ui openapi example
    assert users.parse_cap("0") == 0 and users.parse_cap("unlimited") == 0
    assert users.parse_cap("500M") == 500 * 1024 ** 2
    now = dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc)
    assert users.parse_expiry("30d", now) == int((now + dt.timedelta(days=30)).timestamp() * 1000)
    assert users.parse_expiry("2027-01-31") == 1801353600000
    with pytest.raises(ValueError):
        users.parse_cap("lots")


def test_update_body_keeps_uuid():
    rec = {"uuid": "u-1", "email": "a", "flow": "xtls-rprx-vision", "totalGB": 5, "expiryTime": 0, "enable": True}
    body = users.record_to_update_body(rec)
    assert body["id"] == "u-1" and "uuid" not in body
    with pytest.raises(ValueError):
        users.record_to_update_body({"email": "a"})


def test_vless_link_from_string_stream_settings():
    ib = dict(INBOUND, streamSettings=json.loads(INBOUND["streamSettings"]))
    link = users.vless_link(ib, "u-1", "xtls-rprx-vision", "vpn.example.com", "alice")
    assert link.startswith("vless://u-1@vpn.example.com:443?")
    for part in ("security=reality", "pbk=PUB-old", "sid=abcd1234abcd1234", "sni=www.microsoft.com",
                 "flow=xtls-rprx-vision", "fp=chrome", "#alice"):
        assert part in link


def test_plan_gate():
    plan = {"op": "x", "v": 1}
    assert card.gate(plan, False, None) is False
    with pytest.raises(SystemExit):
        card.gate(plan, True, "wrong")
    assert card.gate(plan, True, card.plan_id(plan)) is True
