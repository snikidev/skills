"""Cloud-side operations (Azure `az` / Google Cloud `gcloud`) for the VPN VM.

Only argv lists are built here (no shell), so every command shown on a card is
exactly what runs. Reads use `run_ro`; writes go through commands.cmd_cloud,
which gates them with a plan id like every other write.

Names match the setup skill's .env: CLOUD_PROVIDER, VM_NAME,
AZURE_RESOURCE_GROUP, AZURE_NSG_NAME, AZURE_SUBSCRIPTION, GCP_PROJECT, GCP_ZONE,
GCP_NETWORK, GCP_NETWORK_TAG.
"""

from __future__ import annotations

import datetime as dt
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .env import Config

HERE = Path(__file__).resolve().parents[1]
PREFLIGHT = HERE / "cloud-preflight.sh"


class CloudError(RuntimeError):
    pass


def provider(cfg: Config) -> str:
    p = (cfg.get("CLOUD_PROVIDER") or "").lower()
    if p not in ("azure", "gcp"):
        raise SystemExit("ERROR: set CLOUD_PROVIDER=azure or gcp in the env file (see references/cloud.md)")
    return p


def vm(cfg: Config) -> str:
    return cfg.get("VM_NAME") or "vless-3xui"


def rg(cfg: Config) -> str:
    return cfg.get("AZURE_RESOURCE_GROUP") or "vless-3xui-rg"


def project(cfg: Config) -> str:
    return cfg.require("GCP_PROJECT")


def zone(cfg: Config) -> str:
    return cfg.get("GCP_ZONE") or "europe-west2-a"


def region(cfg: Config) -> str:
    return zone(cfg).rsplit("-", 1)[0]


def gtag(cfg: Config) -> str:
    return cfg.get("GCP_NETWORK_TAG") or "vless-3xui"


def show(argv: list[str]) -> str:
    return shlex.join(argv)


def run_ro(argv: list[str]) -> str:
    """Run a read-only cloud command and return stdout (stripped)."""
    if not shutil.which(argv[0]):
        raise CloudError(f"{argv[0]} not installed")
    p = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise CloudError(f"{show(argv)} failed: {(p.stderr or p.stdout).strip()[:400]}")
    return p.stdout.strip()


def run_write(argv: list[str]) -> tuple[bool, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    return p.returncode == 0, (p.stdout + p.stderr).strip()[:1500]


# --- preflight ---------------------------------------------------------------
def preflight(cfg: Config, require_vm: bool = True) -> dict[str, list[str]]:
    """Run cloud-preflight.sh with the config's (non-secret) cloud keys."""
    import os
    env = dict(os.environ)
    for k in ("CLOUD_PROVIDER", "VM_NAME", "AZURE_RESOURCE_GROUP", "AZURE_SUBSCRIPTION", "GCP_PROJECT", "GCP_ZONE"):
        v = cfg.get(k)
        if v:
            env[k] = v
    argv = ["sh", str(PREFLIGHT), provider(cfg)] + (["--require-vm"] if require_vm else [])
    p = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=300)
    out: dict[str, list[str]] = {}
    for line in p.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out.setdefault(k.strip(), []).append(v.strip())
    out.setdefault("PREFLIGHT", ["FAIL"])
    return out


def identity_line(pf: dict[str, list[str]], cfg: Config) -> str:
    """Credential line for a card: who and which subscription/project. No secrets."""
    who = pf.get("identity", ["?"])[0]
    if provider(cfg) == "azure":
        return (f"az CLI login (az login): {who}; subscription {pf.get('subscription', ['?'])[0]}; "
                f"resource group {rg(cfg)}")
    return f"gcloud CLI login (gcloud auth login): {who}; project {project(cfg)}; zone {zone(cfg)}"


def cli_transport(cfg: Config) -> str:
    return ("cloud control plane via Azure CLI (az, local)" if provider(cfg) == "azure"
            else "cloud control plane via Google Cloud CLI (gcloud, local)")


def today() -> str:
    return dt.datetime.now().strftime("%Y%m%d")


# --- discovery (read-only) -----------------------------------------------------
def az_vm(cfg: Config) -> dict:
    return json.loads(run_ro(["az", "vm", "show", "--resource-group", rg(cfg), "--name", vm(cfg), "-o", "json"]))


def az_nic(nic_id: str) -> dict:
    return json.loads(run_ro(["az", "network", "nic", "show", "--ids", nic_id, "-o", "json"]))


def az_nsg(cfg: Config) -> str:
    if cfg.get("AZURE_NSG_NAME"):
        return cfg.get("AZURE_NSG_NAME")  # type: ignore[return-value]
    nic = az_nic(az_vm(cfg)["networkProfile"]["networkInterfaces"][0]["id"])
    nsg = (nic.get("networkSecurityGroup") or {}).get("id", "")
    return nsg.rsplit("/", 1)[-1] if nsg else f"{vm(cfg)}-nsg"


def gcp_instance(cfg: Config) -> dict:
    return json.loads(run_ro(["gcloud", "compute", "instances", "describe", vm(cfg), "--project", project(cfg),
                              "--zone", zone(cfg), "--format=json"]))


# --- command builders -------------------------------------------------------------
def snapshot_cmds(cfg: Config, name: str) -> tuple[list[list[str]], str, str]:
    """(commands, disk, rollback text)."""
    if provider(cfg) == "azure":
        disk_id = az_vm(cfg)["storageProfile"]["osDisk"]["managedDisk"]["id"]
        cmd = ["az", "snapshot", "create", "--resource-group", rg(cfg), "--name", name,
               "--source", disk_id, "--incremental", "true", "-o", "none"]
        rb = (f"a snapshot changes nothing on the VM. To restore: az disk create -g {rg(cfg)} -n <new-disk> "
              f"--source {name}, then az vm update -g {rg(cfg)} -n {vm(cfg)} --os-disk <new-disk> (VM deallocated). "
              f"To discard: az snapshot delete -g {rg(cfg)} -n {name}")
        return [cmd], disk_id.rsplit("/", 1)[-1], rb
    inst = gcp_instance(cfg)
    boot = next((d for d in inst.get("disks", []) if d.get("boot")), inst.get("disks", [{}])[0])
    disk = boot.get("source", "").rsplit("/", 1)[-1]
    cmd = ["gcloud", "compute", "disks", "snapshot", disk, "--project", project(cfg), "--zone", zone(cfg),
           "--snapshot-names", name]
    rb = (f"a snapshot changes nothing on the VM. To restore: create a disk from snapshot {name} and swap it in "
          f"as the boot disk (VM stopped). To discard: gcloud compute snapshots delete {name} --project {project(cfg)}")
    return [cmd], disk, rb


def firewall_list_cmd(cfg: Config) -> list[str]:
    if provider(cfg) == "azure":
        return ["az", "network", "nsg", "rule", "list", "--resource-group", rg(cfg), "--nsg-name", az_nsg(cfg),
                "-o", "json"]
    return ["gcloud", "compute", "firewall-rules", "list", "--project", project(cfg), "--format=json"]


def firewall_open_cmd(cfg: Config, name: str, port: str, proto: str, source: str, priority: int) -> list[str]:
    if provider(cfg) == "azure":
        return ["az", "network", "nsg", "rule", "create", "--resource-group", rg(cfg), "--nsg-name", az_nsg(cfg),
                "--name", name, "--priority", str(priority), "--direction", "Inbound", "--access", "Allow",
                "--protocol", proto.capitalize(), "--source-address-prefixes", source,
                "--destination-port-ranges", port, "--description", "added by vless-vpn-3xui-ops", "-o", "none"]
    return ["gcloud", "compute", "firewall-rules", "create", name, "--project", project(cfg),
            "--network", cfg.get("GCP_NETWORK") or "default", "--direction", "INGRESS",
            f"--allow={proto.lower()}:{port}", f"--source-ranges={source}", f"--target-tags={gtag(cfg)}",
            "--description=added by vless-vpn-3xui-ops"]


def firewall_show_cmd(cfg: Config, name: str) -> list[str]:
    if provider(cfg) == "azure":
        return ["az", "network", "nsg", "rule", "show", "--resource-group", rg(cfg), "--nsg-name", az_nsg(cfg),
                "--name", name, "-o", "json"]
    return ["gcloud", "compute", "firewall-rules", "describe", name, "--project", project(cfg), "--format=json"]


def firewall_close_cmd(cfg: Config, name: str) -> list[str]:
    if provider(cfg) == "azure":
        return ["az", "network", "nsg", "rule", "delete", "--resource-group", rg(cfg), "--nsg-name", az_nsg(cfg),
                "--name", name]
    return ["gcloud", "compute", "firewall-rules", "delete", name, "--project", project(cfg), "--quiet"]


def rule_ports(rule: dict) -> set[str]:
    """Ports a rule (az or gcloud JSON) allows, as strings ('*' = all)."""
    ports: set[str] = set()
    if "destinationPortRange" in rule or "destinationPortRanges" in rule:
        for p in [rule.get("destinationPortRange")] + list(rule.get("destinationPortRanges") or []):
            if p:
                ports.add(str(p))
    for a in rule.get("allowed", []) or []:
        for p in a.get("ports", []) or ["*"]:
            ports.add(str(p))
    return ports


def covers(ports: set[str], port: int) -> bool:
    for p in ports:
        if p == "*":
            return True
        if "-" in p:
            lo, hi = p.split("-", 1)
            if lo.isdigit() and hi.isdigit() and int(lo) <= port <= int(hi):
                return True
        elif p.isdigit() and int(p) == port:
            return True
    return False


def az_next_priority(cfg: Config) -> int:
    used = run_ro(["az", "network", "nsg", "rule", "list", "--resource-group", rg(cfg), "--nsg-name", az_nsg(cfg),
                   "--query", "[].priority", "-o", "tsv"]).split()
    taken = {int(x) for x in used if x.isdigit()}
    p = 1200
    while p in taken:
        p += 10
    return p


def restart_cmds(cfg: Config) -> tuple[list[list[str]], str]:
    if provider(cfg) == "azure":
        return [["az", "vm", "restart", "--resource-group", rg(cfg), "--name", vm(cfg)]], \
            "guest OS reboot; Standard static public IP is kept"
    return [["gcloud", "compute", "instances", "reset", vm(cfg), "--project", project(cfg), "--zone", zone(cfg)]], \
        "HARD reset (like pulling power; the VM stays allocated so even an ephemeral external IP is kept). " \
        "Softer alternative: ssh <VPS_SSH> 'sudo systemctl reboot'"


def current_size(cfg: Config) -> str:
    if provider(cfg) == "azure":
        return az_vm(cfg)["hardwareProfile"]["vmSize"]
    return gcp_instance(cfg).get("machineType", "").rsplit("/", 1)[-1]


def resize_cmds(cfg: Config, size: str) -> list[list[str]]:
    if provider(cfg) == "azure":
        return [["az", "vm", "resize", "--resource-group", rg(cfg), "--name", vm(cfg), "--size", size]]
    base = ["--project", project(cfg), "--zone", zone(cfg)]
    return [["gcloud", "compute", "instances", "stop", vm(cfg), *base],
            ["gcloud", "compute", "instances", "set-machine-type", vm(cfg), *base, "--machine-type", size],
            ["gcloud", "compute", "instances", "start", vm(cfg), *base]]


def gcp_access_config(inst: dict) -> tuple[str, str]:
    nic = (inst.get("networkInterfaces") or [{}])[0]
    ac = (nic.get("accessConfigs") or [{}])[0]
    return ac.get("name", "external-nat"), ac.get("natIP", "")


def gcp_ip_reserved(cfg: Config, ip: str) -> Optional[str]:
    if not ip:
        return None
    out = run_ro(["gcloud", "compute", "addresses", "list", "--project", project(cfg),
                  f"--filter=address={ip}", "--format=value(name)"])
    return out.splitlines()[0] if out else None


def rotate_ip_plan(cfg: Config, new_name: str) -> dict:
    """Discovery for IP rotation. Returns names/ids only (IPs are not secret)."""
    if provider(cfg) == "azure":
        v = az_vm(cfg)
        nic = az_nic(v["networkProfile"]["networkInterfaces"][0]["id"])
        ipc = nic["ipConfigurations"][0]
        old_pip = (ipc.get("publicIPAddress") or {}).get("id", "").rsplit("/", 1)[-1]
        cmds = [["az", "network", "public-ip", "create", "--resource-group", rg(cfg), "--name", new_name,
                 "--sku", "Standard", "--allocation-method", "Static", "--version", "IPv4", "-o", "none"],
                ["az", "network", "nic", "ip-config", "update", "--resource-group", rg(cfg), "--nic-name", nic["name"],
                 "--name", ipc["name"], "--public-ip-address", new_name, "-o", "none"]]
        rb = (f"old public IP resource {old_pip or '(none)'} is NOT deleted: re-attach it with az network nic ip-config "
              f"update -g {rg(cfg)} --nic-name {nic['name']} -n {ipc['name']} --public-ip-address {old_pip}. "
              f"Delete it yourself later (az network public-ip delete) once clients use the new IP.")
        get_ip = ["az", "network", "public-ip", "show", "--resource-group", rg(cfg), "--name", new_name,
                  "--query", "ipAddress", "-o", "tsv"]
        return {"cmds": cmds, "rollback": rb, "old": old_pip, "get_ip": get_ip, "ip_lost": False}
    inst = gcp_instance(cfg)
    ac_name, old_ip = gcp_access_config(inst)
    reserved = gcp_ip_reserved(cfg, old_ip)
    base = ["--project", project(cfg), "--zone", zone(cfg)]
    cmds = [["gcloud", "compute", "addresses", "create", new_name, "--project", project(cfg), "--region", region(cfg)],
            ["gcloud", "compute", "instances", "delete-access-config", vm(cfg), *base, f"--access-config-name={ac_name}"],
            ["gcloud", "compute", "instances", "add-access-config", vm(cfg), *base, f"--access-config-name={ac_name}",
             "--address=<new address from step 1>"]]
    rb = (f"old IP {old_ip} is reserved as {reserved}; re-attach it the same way." if reserved else
          f"old IP {old_ip} is EPHEMERAL and is released for good in step 2. It cannot be got back. "
          f"To keep it, first promote it: gcloud compute addresses create keep-old --addresses {old_ip} "
          f"--region {region(cfg)} --project {project(cfg)}")
    get_ip = ["gcloud", "compute", "addresses", "describe", new_name, "--project", project(cfg),
              "--region", region(cfg), "--format=value(address)"]
    return {"cmds": cmds, "rollback": rb, "old": old_ip, "get_ip": get_ip, "ip_lost": not reserved,
            "ac_name": ac_name}
