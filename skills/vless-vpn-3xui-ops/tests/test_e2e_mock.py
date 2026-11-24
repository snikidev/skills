"""End-to-end: ops.py as a subprocess against the mock panel + fake ssh."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import mock_panel

OPS = Path(__file__).resolve().parents[1] / "scripts" / "ops.py"
SECRETS = [mock_panel.ADMIN, mock_panel.MONITOR, mock_panel.PASSWORD, "proxypass-secret", "PRIV-old", "PRIV-new"]


def run(*args, ok=True):
    p = subprocess.run([sys.executable, str(OPS), *args], capture_output=True, text=True, env=os.environ.copy(), timeout=60)
    out = p.stdout + p.stderr
    for s in SECRETS:
        assert s not in out, f"secret leaked in output of {args}"
    if ok:
        assert p.returncode == 0, out
    return p.returncode, out


def plan_of(out):
    return re.search(r"Plan id: ([0-9a-f]{10})", out).group(1)


def assert_card(out, mode):
    for field in ("ACTION", "What & why:", "Transport:", "Endpoint/cmd:", "Credential:", "Mode:", "Rollback:"):
        assert field in out
    assert f"Mode:        {mode}" in out


def ssh_log(tmp):
    f = tmp / "ssh.log"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def test_users_add_gate_and_lifecycle(panel):
    state, env, tmp = panel
    _, out = run("users", "add", "bob", "--cap", "50G", "--expires", "2027-01-31")
    assert_card(out, "WRITE")
    assert "XUI_API_TOKEN" in out and "DRY RUN" in out and "bob" not in state.clients
    pid = plan_of(out)
    rc, out = run("users", "add", "bob", "--cap", "50G", "--expires", "2027-01-31", "--execute", "--plan", "deadbeef00", ok=False)
    assert rc == 3 and "REFUSED" in out and "bob" not in state.clients
    _, out = run("users", "add", "bob", "--cap", "50G", "--expires", "2027-01-31", "--execute", "--plan", pid)
    assert "RESULT: OK" in out and "vless://" in out and "@vpn.example.com:443" in out
    rec = state.clients["bob"]["record"]
    assert rec["totalGB"] == 53687091200 and rec["expiryTime"] == 1801353600000 and rec["uuid"]
    uuid = rec["uuid"]

    _, out = run("users", "add", "dan", "--expires", "30d")
    pid = plan_of(out)
    import time
    time.sleep(1.1)  # relative expiry must not invalidate the plan
    run("users", "add", "dan", "--expires", "30d", "--execute", "--plan", pid)
    assert state.clients["dan"]["record"]["expiryTime"] > 0
    _, out = run("users", "set", "dan", "--expires", "60d")
    time.sleep(1.1)
    run("users", "set", "dan", "--expires", "60d", "--execute", "--plan", plan_of(out))

    _, out = run("users", "list")
    assert_card(out, "READ-ONLY")
    assert "bob" in out and "alice" in out

    _, out = run("users", "set", "bob", "--cap", "100G")
    _, out = run("users", "set", "bob", "--cap", "100G", "--execute", "--plan", plan_of(out))
    assert state.clients["bob"]["record"]["uuid"] == uuid  # full record sent back, uuid kept
    assert state.clients["bob"]["record"]["totalGB"] == 100 * 1024 ** 3

    _, out = run("users", "disable", "bob")
    run("users", "disable", "bob", "--execute", "--plan", plan_of(out))
    assert state.clients["bob"]["record"]["enable"] is False
    _, out = run("users", "disable", "bob")
    assert "no change" in out

    _, out = run("users", "reset-traffic", "alice")
    assert "Current usage for alice" in out and "3.00 GiB" in out
    run("users", "reset-traffic", "alice", "--execute", "--plan", plan_of(out))
    assert state.clients["alice"]["traffic"] == {"up": 0, "down": 0}

    _, out = run("users", "remove", "bob")
    _, out = run("users", "remove", "bob", "--execute", "--plan", plan_of(out))
    assert "bob" not in state.clients
    snap = re.search(r"Snapshot saved: (\S+)", out).group(1)
    assert oct(Path(snap).stat().st_mode & 0o777) == "0o600"
    _, out = run("rollback", "--snapshot", snap)
    run("rollback", "--snapshot", snap, "--execute", "--plan", plan_of(out))
    assert state.clients["bob"]["record"]["uuid"] == uuid  # old link works again


def test_routing_add_remove_and_stale_plan(panel):
    state, env, tmp = panel
    _, out = run("routing", "list")
    assert "default outbound" in out.lower() and "iproyal" in out
    _, out = run("routing", "add", "domain:openrouter.ai", "direct")
    assert_card(out, "WRITE")
    assert "+" in out and "openrouter.ai" in out
    pid = plan_of(out)
    # someone changes the template in between: the old plan id must be refused
    state.template["routing"]["rules"].append({"type": "field", "domain": ["domain:x.example"], "outboundTag": "blocked"})
    rc, out = run("routing", "add", "domain:openrouter.ai", "direct", "--execute", "--plan", pid, ok=False)
    assert rc == 3
    _, out = run("routing", "add", "domain:openrouter.ai", "direct")
    _, out = run("routing", "add", "domain:openrouter.ai", "direct", "--execute", "--plan", plan_of(out))
    assert any("domain:openrouter.ai" in r.get("domain", []) for r in state.template["routing"]["rules"])
    assert state.template["outbounds"][0]["settings"]["servers"][0]["users"][0]["pass"] == "proxypass-secret"
    _, out = run("routing", "test", "openrouter.ai")
    assert "direct" in out
    _, out = run("routing", "add", "domain:openrouter.ai", "direct")
    assert "no change" in out
    _, out = run("routing", "remove", "domain:openrouter.ai")
    run("routing", "remove", "domain:openrouter.ai", "--execute", "--plan", plan_of(out))
    assert not any("domain:openrouter.ai" in r.get("domain", []) for r in state.template["routing"]["rules"])


def test_probe_keeps_proxy_creds_off_argv(panel):
    state, env, tmp = panel
    _, out = run("routing", "probe", "--providers", "openai,anthropic")
    assert "anthropic" in out
    for entry in ssh_log(tmp):
        assert "proxypass-secret" not in " ".join(entry["argv"])
    assert any("proxypass-secret" in e["stdin"] for e in ssh_log(tmp))  # only via curl -K - on stdin


def test_status_with_cookie_login(panel):
    state, env, tmp = panel
    text = env.read_text().replace(f"XUI_API_TOKEN={mock_panel.ADMIN}\n", "")
    env.write_text(text + f"XUI_USERNAME={mock_panel.USER}\nXUI_PASSWORD={mock_panel.PASSWORD}\n")
    _, out = run("status")
    assert "XUI_PASSWORD" in out and "running" in out
    assert ("GET", "/secretpath/csrf-token") in state.calls
    assert state.calls.index(("GET", "/secretpath/csrf-token")) < state.calls.index(("POST", "/secretpath/login"))
    # a write via cookie auth must carry X-CSRF-Token (the mock 403s otherwise)
    _, out = run("users", "disable", "alice")
    run("users", "disable", "alice", "--execute", "--plan", plan_of(out))
    assert state.clients["alice"]["record"]["enable"] is False


def test_monitor_token_used_for_reads_only(panel):
    state, env, tmp = panel
    env.write_text(env.read_text() + f"XUI_MONITOR_TOKEN={mock_panel.MONITOR}\n")
    _, out = run("status")
    assert "XUI_MONITOR_TOKEN" in out


def test_backup_pull_verify_restore(panel):
    state, env, tmp = panel
    _, out = run("backup", "pull")
    files = sorted((tmp / "backups").glob("*.db"))
    assert len(files) == 1 and oct(files[0].stat().st_mode & 0o777) == "0o600"
    assert Path(str(files[0]) + ".sha256").exists()
    _, out = run("backup", "verify", str(files[0]))
    assert "integrity" in out.lower() and "ok" in out.lower()
    bad = tmp / "bad.db"
    bad.write_bytes(b"not a db")
    rc, out = run("backup", "verify", str(bad), ok=False)
    assert rc != 0
    _, out = run("backup", "restore", str(files[0]))
    assert_card(out, "WRITE")
    assert state.imported is None
    _, out = run("backup", "restore", str(files[0]), "--execute", "--plan", plan_of(out))
    assert state.imported == files[0].read_bytes()
    assert len(list((tmp / "backups").glob("*.db"))) == 2  # pre-restore safety backup


def test_rotate_keys(panel):
    state, env, tmp = panel
    _, out = run("rotate", "--keys")
    assert_card(out, "WRITE")
    _, out = run("rotate", "--keys", "--execute", "--plan", plan_of(out))
    ss = json.loads(state.inbound["streamSettings"])
    assert ss["realitySettings"]["privateKey"] == "PRIV-new"
    assert ss["realitySettings"]["settings"]["publicKey"] == "PUB-new"
    links = list((tmp / "state").glob("links-*.txt"))
    assert links and "pbk=PUB-new" in links[0].read_text()
    assert oct(links[0].stat().st_mode & 0o777) == "0o600"


def test_drift_flags_missing_rule(panel):
    state, env, tmp = panel
    rc, out = run("drift", ok=False)
    assert "openrouter.ai" in out


def test_connect_and_rebind(panel):
    state, env, tmp = panel
    _, out = run("connect")
    assert "0.0.0.0" in out
    _, out = run("rebind-localhost")
    assert_card(out, "WRITE")
    assert "listenIP 127.0.0.1" in out and "SSH" in out
    _, out = run("rebind-localhost", "--execute", "--plan", plan_of(out))
    assert any("listenIP 127.0.0.1" in e["argv"][-1] for e in ssh_log(tmp))


def test_upgrade_dry_run_is_pinned(panel):
    state, env, tmp = panel
    _, out = run("upgrade", "--to", "v3.11.1")
    assert "raw.githubusercontent.com/MHSanaei/3x-ui/v3.11.1/update.sh" in out
    assert "XUI_UPDATE_TAG=v3.11.1" in out and "DRY RUN" in out
    assert not any("update.sh" in e["argv"][-1] for e in ssh_log(tmp))
