import os
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import mock_panel  # noqa: E402


@pytest.fixture()
def panel(tmp_path, monkeypatch):
    srv, state, port = mock_panel.start()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh = bindir / "ssh"
    ssh.write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_ssh.py'} \"$@\"\n")
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    for tool in ("az", "gcloud"):
        f = bindir / tool
        f.write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_cloud.py'} {tool} \"$@\"\n")
        f.chmod(0o755)
    monkeypatch.setenv("FAKE_CLOUD_LOG", str(tmp_path / "cloud.log"))
    monkeypatch.setenv("FAKE_CLOUD_STATE", str(tmp_path / "cloud.json"))
    monkeypatch.setenv("VLESS_OPS_WAIT", "0")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_LOG", str(tmp_path / "ssh.log"))
    env = tmp_path / "vless-ops.env"
    env.write_text(
        "VPS_SSH=vps\nPANEL_REMOTE_PORT=54321\n"
        f"PANEL_LOCAL_PORT={port}\nPANEL_BASE_PATH=/secretpath/\n"
        f"XUI_API_TOKEN={mock_panel.ADMIN}\nPUBLIC_HOST=vpn.example.com\n"
        f"OPS_STATE_DIR={tmp_path / 'state'}\nBACKUP_DIR={tmp_path / 'backups'}\n"
    )
    env.chmod(0o600)
    for k in ("XUI_API_TOKEN", "XUI_MONITOR_TOKEN", "XUI_USERNAME", "XUI_PASSWORD", "PANEL_BASE_URL", "INBOUND_ID",
              "CLOUD_PROVIDER", "AZURE_SUBSCRIPTION", "GCP_PROJECT", "VM_NAME", "AZURE_RESOURCE_GROUP"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VLESS_OPS_ENV", str(env))
    yield state, env, tmp_path
    srv.shutdown()
