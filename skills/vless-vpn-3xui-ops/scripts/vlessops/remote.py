"""SSH helpers. Commands are shown in cards; secrets go over stdin only."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Optional

from .env import Config

SCRIPTS = Path(__file__).resolve().parent.parent


def ssh_argv(cfg: Config, remote_cmd: str) -> list[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    key = cfg.get("VPS_SSH_KEY")
    if key:
        argv += ["-i", str(Path(key).expanduser())]
    argv += [cfg.ssh_target(), remote_cmd]
    return argv


def show_cmd(cfg: Config, remote_cmd: str) -> str:
    return f"ssh {cfg.get('VPS_SSH') or '<VPS_SSH>'} {shlex.quote(remote_cmd)}"


def run(cfg: Config, remote_cmd: str, stdin: Optional[bytes] = None,
        timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ssh_argv(cfg, remote_cmd), input=stdin, capture_output=True, timeout=timeout
    )


def run_script(cfg: Config, script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return run(cfg, "sh -s", stdin=(SCRIPTS / script).read_bytes(), timeout=timeout)


def parse_kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def curl_config(url: str, proxy: Optional[dict] = None, max_time: int = 15) -> bytes:
    """A curl -K config. Proxy credentials live here, never in argv."""
    lines = [
        f'url = "{url}"',
        'silent', 'show-error',
        'output = "/dev/null"',
        f'max-time = {max_time}',
        'write-out = "%{http_code} %{time_total} %{remote_ip}\\n"',
    ]
    if proxy:
        lines.append(f'proxy = "socks5h://{proxy["address"]}:{proxy["port"]}"')
        if proxy.get("user"):
            lines.append(f'proxy-user = "{proxy["user"]}:{proxy.get("pass", "")}"')
    return ("\n".join(lines) + "\n").encode()


def curl_body_config(url: str, proxy: Optional[dict] = None, max_time: int = 15) -> bytes:
    cfg = curl_config(url, proxy, max_time).decode()
    cfg = cfg.replace('output = "/dev/null"\n', "").replace(
        'write-out = "%{http_code} %{time_total} %{remote_ip}\\n"\n', "")
    return cfg.encode()
