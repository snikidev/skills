"""Cloud ops against fake az/gcloud: preflight, cards, gates, guards."""
import json
import os

from test_e2e_mock import assert_card, plan_of, run


def use(env, text):
    env.write_text(env.read_text() + text)


def cloud_log(tmp):
    f = tmp / "cloud.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def writes(tmp):
    verbs = {"create", "delete", "restart", "resize", "update", "snapshot", "reset", "stop", "start",
             "set-machine-type", "delete-access-config", "add-access-config"}
    return [c for c in cloud_log(tmp) if verbs & set(c[1:5]) and "describe" not in c and "show" not in c]


AZ = "CLOUD_PROVIDER=azure\nAZURE_SUBSCRIPTION=VPN Sub\n"
GCP = "CLOUD_PROVIDER=gcp\nGCP_PROJECT=proj-1\n"


def test_preflight_azure_ok_and_names_only(panel):
    state, env, tmp = panel
    use(env, AZ)
    _, out = run("cloud", "preflight")
    assert_card(out, "READ-ONLY")
    assert "identity: ops@example.com (user)" in out and "VPN Sub (00000000-aaaa" in out
    assert "subscription_match: yes" in out and "preflight passed" in out


def test_preflight_wrong_subscription_blocks_writes(panel):
    state, env, tmp = panel
    use(env, "CLOUD_PROVIDER=azure\nAZURE_SUBSCRIPTION=Prod Sub\n")
    rc, out = run("cloud", "snapshot", ok=False)
    assert rc == 1 and "preflight FAILED" in out and "az account set" in out
    assert not writes(tmp)


def test_preflight_logged_out(panel, monkeypatch):
    state, env, tmp = panel
    use(env, GCP)
    monkeypatch.setenv("FAKE_LOGGED_OUT", "1")
    rc, out = run("cloud", "preflight", ok=False)
    assert rc == 1 and "gcloud auth login" in out


def test_owner_role_warns(panel, monkeypatch):
    state, env, tmp = panel
    use(env, AZ)
    monkeypatch.setenv("FAKE_ROLE", "Owner")
    _, out = run("cloud", "preflight")
    assert "prefer Contributor" in out


def test_azure_snapshot_gate(panel):
    state, env, tmp = panel
    use(env, AZ)
    _, out = run("cloud", "snapshot")
    assert_card(out, "WRITE")
    assert "az snapshot create" in out and "vless-3xui_OsDisk_1" in out and "ops@example.com" in out
    assert not writes(tmp)
    _, out = run("cloud", "snapshot", "--execute", "--plan", plan_of(out))
    assert "created" in out and json.loads((tmp / "cloud.json").read_text())["snapshot"].startswith("vless-3xui-ops-")


def test_azure_firewall_open_close_and_lockout_guard(panel):
    state, env, tmp = panel
    use(env, AZ)
    _, out = run("cloud", "firewall-list")
    assert "allow-vless-443" in out
    _, out = run("cloud", "firewall-open", "8443", "--source", "203.0.113.5/32")
    assert "--priority 1200" in out and "8443" in out
    run("cloud", "firewall-open", "8443", "--source", "203.0.113.5/32", "--execute", "--plan", plan_of(out))
    names = [r["name"] for r in json.loads((tmp / "cloud.json").read_text())["nsg"]]
    assert "vless-ops-tcp-8443" in names
    rc, out = run("cloud", "firewall-close", "allow-ssh-operator", ok=False)
    assert rc == 3 and "REFUSED" in out
    _, out = run("cloud", "firewall-close", "vless-ops-tcp-8443")
    _, out = run("cloud", "firewall-close", "vless-ops-tcp-8443", "--execute", "--plan", plan_of(out))
    assert "Snapshot saved" in out
    names = [r["name"] for r in json.loads((tmp / "cloud.json").read_text())["nsg"]]
    assert "vless-ops-tcp-8443" not in names


def test_azure_resize_and_rotate_ip(panel):
    state, env, tmp = panel
    use(env, AZ)
    _, out = run("cloud", "resize", "Standard_B1ms")
    assert "Standard_B2s -> Standard_B1ms" in out and "ops.py cloud resize Standard_B2s" in out
    run("cloud", "resize", "Standard_B1ms", "--execute", "--plan", plan_of(out))
    assert json.loads((tmp / "cloud.json").read_text())["size"] == "Standard_B1ms"
    _, out = run("cloud", "rotate-ip")
    assert "NOT deleted" in out
    _, out = run("cloud", "rotate-ip", "--execute", "--plan", plan_of(out))
    assert "new public IP 51.0.0.2" in out and "PUBLIC_HOST" in out


def test_gcp_ephemeral_ip_guards(panel):
    state, env, tmp = panel
    use(env, GCP)
    rc, out = run("cloud", "resize", "e2-medium", ok=False)
    assert rc == 3 and "EPHEMERAL" in out
    rc, out = run("cloud", "rotate-ip", ok=False)
    assert rc == 3 and "cannot be got back" in out
    assert not writes(tmp)
    _, out = run("cloud", "resize", "e2-medium", "--allow-ip-change")
    assert "instances stop" in out and "set-machine-type" in out and "instances start" in out


def test_gcp_rotate_ip_reserved(panel, monkeypatch):
    state, env, tmp = panel
    use(env, GCP)
    monkeypatch.setenv("FAKE_GCP_RESERVED", "1")
    _, out = run("cloud", "rotate-ip")
    _, out = run("cloud", "rotate-ip", "--execute", "--plan", plan_of(out))
    assert "new public IP 35.0.0.9" in out
    assert json.loads((tmp / "cloud.json").read_text())["natip"] == "35.0.0.9"


def test_gcp_firewall_and_restart(panel):
    state, env, tmp = panel
    use(env, GCP)
    _, out = run("cloud", "firewall-open", "8443")
    assert "--target-tags=vless-3xui" in out and "whole internet" in out
    run("cloud", "firewall-open", "8443", "--execute", "--plan", plan_of(out))
    rc, out = run("cloud", "firewall-close", "vless-3xui-vless", ok=False)
    assert rc == 3
    _, out = run("cloud", "restart")
    assert "HARD reset" in out
    run("cloud", "restart", "--execute", "--plan", plan_of(out))
    assert any(c[1:4] == ["compute", "instances", "reset"] for c in cloud_log(tmp))


def test_upgrade_takes_cloud_snapshot_first(panel):
    state, env, tmp = panel
    use(env, GCP)
    _, out = run("upgrade", "--to", "v3.11.1")
    assert "gcloud compute disks snapshot vless-3xui" in out and "vless-3xui-pre-v3-11-1-" in out
    _, out = run("upgrade", "--to", "v3.11.1", "--execute", "--plan", plan_of(out), ok=False)
    log = [c for c in cloud_log(tmp) if c[1:4] == ["compute", "disks", "snapshot"]]
    assert log, out
    assert "[1/5]" in out and "[2/5] backup" in out
    # no-cloud-snapshot path skips it
    _, out = run("upgrade", "--to", "v3.11.1", "--no-cloud-snapshot")
    assert "disks snapshot" not in out


def test_no_cloud_provider_is_clear(panel):
    state, env, tmp = panel
    rc, out = run("cloud", "preflight", ok=False)
    assert "CLOUD_PROVIDER" in out
    assert os.environ.get("CLOUD_PROVIDER") is None
