#!/usr/bin/env python3
"""Fake `ssh` for tests: logs argv + stdin, answers like a VPS would."""
import json
import os
import sys

argv = sys.argv[1:]
cmd = argv[-1]
stdin = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""
log = os.environ.get("FAKE_SSH_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": argv, "stdin": stdin.decode(errors="replace")}) + "\n")

if cmd == "sh -s":
    ver = os.environ.get("FAKE_XUI_VERSION", "v3.11.0")
    print(f"xui_service=active\nxui_enabled=enabled\nxui_version={ver}\nxray_process=running\n"
          f"panel_listen={os.environ.get('FAKE_LISTEN', '0.0.0.0')}\nlistening=0.0.0.0:443 127.0.0.1:2053")
elif cmd == "curl -K -":
    cfg = stdin.decode()
    via_proxy = "proxy = " in cfg
    if "write-out" in cfg:
        if "anthropic" in cfg and via_proxy:
            print("403 0.3 1.2.3.4")
        else:
            print("401 0.2 9.9.9.9")
    else:
        print("1.2.3.4" if via_proxy else "20.0.0.10")
elif "x-ui setting -listenIP" in cmd or "update.sh" in cmd:
    print("ok")
else:
    print(f"fake ssh: unknown command {cmd}", file=sys.stderr)
    sys.exit(1)
