#!/usr/bin/env python3
"""vless-vpn-3xui-ops - day-2 management of a 3x-ui VLESS Reality server.

Every command prints an ACTION card (what/why, transport, endpoint or command,
credential by name and source, read-only vs write, rollback) before it does
anything, and a RESULT line after. Writes are DRY RUNS until re-run with
`--execute --plan <id>` using the id the dry run printed.

  ops.py connect [--open]                 tunnel check/open + panel listen address
  ops.py rebind-localhost                 bind the panel to 127.0.0.1 (write, SSH)
  ops.py status [--domain D ...]          health: service, Xray, users, Reality, egress, routing
  ops.py users list
  ops.py users add NAME [--cap 50G] [--expires 30d|2027-01-31] [--flow F] [--comment C] [--qr]
  ops.py users set NAME [--cap ..] [--expires ..] [--comment ..]
  ops.py users disable|enable|remove|reset-traffic NAME [--keep-traffic]
  ops.py users link NAME [--qr]
  ops.py routing list | test DOMAIN | add MATCHER OUTBOUND | remove MATCHER
  ops.py routing probe [--providers openai,anthropic,...]
  ops.py backup pull | verify FILE | restore FILE
  ops.py upgrade [--to vX.Y.Z] [--no-cloud-snapshot]
  ops.py rotate [--keys] [--short-id] [--sni HOST [--target HOST:443]]
  ops.py drift [--export DIR]
  ops.py rollback --snapshot FILE
  ops.py cloud preflight | snapshot [--name N] | firewall-list
  ops.py cloud firewall-open PORT [--proto tcp|udp] [--source CIDR] | firewall-close NAME
  ops.py cloud restart | resize SIZE | rotate-ip      (az or gcloud, per CLOUD_PROVIDER)

Global: --env FILE (default ~/.config/vless-ops/.env or $VLESS_OPS_ENV)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vlessops import commands  # noqa: E402
from vlessops.env import Config  # noqa: E402


def write_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--execute", action="store_true", help="actually perform the write")
    p.add_argument("--plan", help="plan id printed by the dry run (required with --execute)")


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ops.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", help="env file path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("connect")
    p.add_argument("--open", action="store_true")
    p = sub.add_parser("rebind-localhost")
    write_flags(p)
    p = sub.add_parser("status")
    p.add_argument("--domain", dest="domains", action="append")

    p = sub.add_parser("users")
    p.add_argument("action", choices=["list", "add", "set", "disable", "enable", "remove", "reset-traffic", "link"])
    p.add_argument("name", nargs="?")
    p.add_argument("--cap")
    p.add_argument("--expires")
    p.add_argument("--flow")
    p.add_argument("--comment")
    p.add_argument("--keep-traffic", action="store_true")
    p.add_argument("--qr", action="store_true")
    write_flags(p)

    p = sub.add_parser("routing")
    p.add_argument("action", choices=["list", "test", "add", "remove", "probe"])
    p.add_argument("matcher", nargs="?")
    p.add_argument("outbound", nargs="?")
    p.add_argument("--providers")
    write_flags(p)

    p = sub.add_parser("backup")
    p.add_argument("action", choices=["pull", "verify", "restore"])
    p.add_argument("file", nargs="?")
    write_flags(p)

    p = sub.add_parser("upgrade")
    p.add_argument("--to")
    p.add_argument("--no-cloud-snapshot", action="store_true",
                   help="skip the cloud disk snapshot step (taken by default when CLOUD_PROVIDER is set)")
    write_flags(p)

    p = sub.add_parser("rotate")
    p.add_argument("--keys", action="store_true")
    p.add_argument("--short-id", action="store_true")
    p.add_argument("--sni")
    p.add_argument("--target")
    write_flags(p)

    p = sub.add_parser("drift")
    p.add_argument("--export")

    p = sub.add_parser("cloud", help="cloud-side ops via az/gcloud (preflight first, always)")
    p.add_argument("action", choices=["preflight", "snapshot", "firewall-list", "firewall-open", "firewall-close",
                                      "restart", "resize", "rotate-ip"])
    p.add_argument("arg", nargs="?", help="firewall-open: PORT; firewall-close: NAME; resize: SIZE")
    p.add_argument("--name", help="snapshot / rule / new IP resource name")
    p.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    p.add_argument("--source", help="CIDR allowed by firewall-open (default 0.0.0.0/0)")
    p.add_argument("--allow-lockout", action="store_true", help="firewall-close: allow closing a 22/443 rule")
    p.add_argument("--allow-ip-change", action="store_true", help="resize/rotate-ip on GCP with an ephemeral IP")
    write_flags(p)

    p = sub.add_parser("rollback")
    p.add_argument("--snapshot", required=True)
    write_flags(p)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build().parse_args(argv)
    cfg = Config.load(args.env)
    for w in cfg.warnings:
        print(f"WARNING: {w}")
    if args.cmd == "users" and args.action != "list" and not args.name:
        raise SystemExit("users: NAME is required")
    if args.cmd == "routing":
        if args.action in ("test", "add", "remove") and not args.matcher:
            raise SystemExit("routing: MATCHER is required")
        if args.action == "add" and not args.outbound:
            raise SystemExit("routing add: OUTBOUND is required (e.g. direct, iproyal)")
    if args.cmd == "backup" and args.action in ("verify", "restore") and not args.file:
        raise SystemExit("backup: FILE is required")
    if args.cmd == "cloud":
        a = args.action
        args.port = args.arg if a == "firewall-open" else None
        args.size = args.arg if a == "resize" else None
        if a == "firewall-close":
            args.name = args.arg or args.name
        if a == "firewall-open" and not (args.port or "").isdigit():
            raise SystemExit("cloud firewall-open PORT [--proto tcp|udp] [--source CIDR] [--name NAME]")
    handler = {
        "connect": commands.cmd_connect, "rebind-localhost": commands.cmd_rebind,
        "status": commands.cmd_status, "users": commands.cmd_users, "routing": commands.cmd_routing,
        "backup": commands.cmd_backup, "upgrade": commands.cmd_upgrade, "rotate": commands.cmd_rotate,
        "drift": commands.cmd_drift, "cloud": commands.cmd_cloud, "rollback": commands.cmd_rollback,
    }[args.cmd]
    return handler(cfg, args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
