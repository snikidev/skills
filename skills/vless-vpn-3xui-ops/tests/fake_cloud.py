#!/usr/bin/env python3
"""Fake `az` and `gcloud` for tests: logs argv, keeps a little JSON state."""
import json
import os
import sys
from pathlib import Path


argv = sys.argv[1:]
tool, argv = argv[0], argv[1:]
line = " ".join(argv)
log = os.environ.get("FAKE_CLOUD_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps([tool] + argv) + "\n")
sf = Path(os.environ["FAKE_CLOUD_STATE"])
st = json.loads(sf.read_text()) if sf.exists() else {
    "nsg": [{"name": "allow-ssh-operator", "priority": 1000, "direction": "Inbound", "access": "Allow",
             "protocol": "Tcp", "destinationPortRange": "22", "sourceAddressPrefix": "198.51.100.7/32"},
            {"name": "allow-vless-443", "priority": 1100, "direction": "Inbound", "access": "Allow",
             "protocol": "Tcp", "destinationPortRange": "443", "sourceAddressPrefix": "*"}],
    "gfw": [{"name": "vless-3xui-ssh", "direction": "INGRESS", "priority": 1000, "sourceRanges": ["198.51.100.7/32"],
             "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}], "targetTags": ["vless-3xui"]},
            {"name": "vless-3xui-vless", "direction": "INGRESS", "priority": 1000, "sourceRanges": ["0.0.0.0/0"],
             "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}], "targetTags": ["vless-3xui"]}],
    "size": "Standard_B2s", "mtype": "e2-small", "pip": "vless-3xui-ip", "natip": "34.0.0.1"}


def save():
    sf.write_text(json.dumps(st))


def arg(flag):
    for i, a in enumerate(argv):
        if a == flag:
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def out(x):
    print(x if isinstance(x, str) else json.dumps(x))
    save()
    sys.exit(0)


if tool == "az":
    if argv[:1] == ["version"]:
        out("2.70.0")
    if argv[:2] == ["account", "show"]:
        if os.environ.get("FAKE_LOGGED_OUT"):
            print("Please run 'az login' to setup account.", file=sys.stderr)
            sys.exit(1)
        out("VPN Sub\n00000000-aaaa-bbbb-cccc-000000000001\nops@example.com\nuser\n11111111-0000-0000-0000-000000000000")
    if argv[:2] == ["group", "show"]:
        out("vless-3xui-rg")
    if argv[:2] == ["vm", "show"] and "powerState" in line:
        out("VM running")
    if argv[:3] == ["role", "assignment", "list"]:
        out(os.environ.get("FAKE_ROLE", "Contributor"))
    if argv[:2] == ["vm", "show"]:
        out({"hardwareProfile": {"vmSize": st["size"]},
             "storageProfile": {"osDisk": {"managedDisk": {"id": "/subscriptions/x/resourceGroups/vless-3xui-rg/providers/Microsoft.Compute/disks/vless-3xui_OsDisk_1"}}},
             "networkProfile": {"networkInterfaces": [{"id": "/subscriptions/x/nic/vless-3xuiVMNic"}]}})
    if argv[:3] == ["network", "nic", "show"]:
        out({"name": "vless-3xuiVMNic", "networkSecurityGroup": {"id": "/x/networkSecurityGroups/vless-3xui-nsg"},
             "ipConfigurations": [{"name": "ipconfigvless-3xui", "publicIPAddress": {"id": f"/x/publicIPAddresses/{st['pip']}"}}]})
    if argv[:4] == ["network", "nsg", "rule", "list"]:
        if "[].priority" in line:
            out("\n".join(str(r["priority"]) for r in st["nsg"]))
        out(st["nsg"])
    if argv[:4] == ["network", "nsg", "rule", "show"]:
        r = [x for x in st["nsg"] if x["name"] == arg("--name")]
        if not r:
            sys.exit(3)
        out(r[0])
    if argv[:4] == ["network", "nsg", "rule", "create"]:
        st["nsg"].append({"name": arg("--name"), "priority": int(arg("--priority")), "direction": "Inbound",
                          "access": "Allow", "protocol": arg("--protocol"),
                          "destinationPortRange": arg("--destination-port-ranges"),
                          "sourceAddressPrefix": arg("--source-address-prefixes")})
        out("")
    if argv[:4] == ["network", "nsg", "rule", "delete"]:
        st["nsg"] = [x for x in st["nsg"] if x["name"] != arg("--name")]
        out("")
    if argv[:2] == ["snapshot", "create"]:
        st["snapshot"] = arg("--name")
        out("")
    if argv[:2] == ["vm", "restart"]:
        out("")
    if argv[:2] == ["vm", "resize"]:
        st["size"] = arg("--size")
        out("")
    if argv[:3] == ["network", "public-ip", "create"]:
        st["newpip"] = arg("--name")
        out("")
    if argv[:3] == ["network", "public-ip", "show"]:
        out("51.0.0.2")
    if argv[:4] == ["network", "nic", "ip-config", "update"]:
        st["pip"] = arg("--public-ip-address")
        out("")

if tool == "gcloud":
    if argv[:1] == ["--version"]:
        out("Google Cloud SDK 500.0.0\nbq 2.1")
    if argv[:2] == ["auth", "list"]:
        out("" if os.environ.get("FAKE_LOGGED_OUT") else "ops@example.com")
    if argv[:2] == ["config", "get-value"]:
        out(os.environ.get("FAKE_GCP_ACTIVE", "proj-1"))
    if argv[:2] == ["projects", "describe"]:
        out(f"{argv[2]}\tVPN Project" if argv[2] == "proj-1" else "")
    if argv[:2] == ["projects", "get-iam-policy"]:
        out(os.environ.get("FAKE_ROLE", "roles/compute.instanceAdmin.v1"))
    if argv[:3] == ["compute", "instances", "describe"]:
        if "value(status)" in line:
            out("RUNNING")
        out({"machineType": f"zones/europe-west2-a/machineTypes/{st['mtype']}",
             "disks": [{"boot": True, "source": "projects/proj-1/zones/europe-west2-a/disks/vless-3xui"}],
             "networkInterfaces": [{"accessConfigs": [{"name": "external-nat", "natIP": st["natip"]}]}]})
    if argv[:3] == ["compute", "addresses", "list"]:
        out("vless-3xui-ip" if os.environ.get("FAKE_GCP_RESERVED") else "")
    if argv[:3] == ["compute", "addresses", "create"]:
        out("")
    if argv[:3] == ["compute", "addresses", "describe"]:
        out("35.0.0.9")
    if argv[:3] == ["compute", "instances", "delete-access-config"]:
        st["natip"] = ""
        out("")
    if argv[:3] == ["compute", "instances", "add-access-config"]:
        st["natip"] = arg("--address")
        out("")
    if argv[:3] == ["compute", "disks", "snapshot"]:
        st["snapshot"] = arg("--snapshot-names")
        out("")
    if argv[:3] == ["compute", "firewall-rules", "list"]:
        out(st["gfw"])
    if argv[:3] == ["compute", "firewall-rules", "describe"]:
        r = [x for x in st["gfw"] if x["name"] == argv[3]]
        if not r:
            sys.exit(1)
        out(r[0])
    if argv[:3] == ["compute", "firewall-rules", "create"]:
        proto, port = arg("--allow").split(":")
        st["gfw"].append({"name": argv[3], "direction": "INGRESS", "priority": 1000,
                          "sourceRanges": [arg("--source-ranges")],
                          "allowed": [{"IPProtocol": proto, "ports": [port]}], "targetTags": [arg("--target-tags")]})
        out("")
    if argv[:3] == ["compute", "firewall-rules", "delete"]:
        st["gfw"] = [x for x in st["gfw"] if x["name"] != argv[3]]
        out("")
    if argv[:2] == ["compute", "instances"] and argv[2] in ("reset", "stop", "start", "set-machine-type"):
        if argv[2] == "set-machine-type":
            st["mtype"] = arg("--machine-type")
        out("")

print(f"fake {tool}: unhandled {line}", file=sys.stderr)
sys.exit(9)
