"""Configuration loading with provenance, never exposing secret values.

Order: process environment wins over the env file. The env file defaults to
~/.config/vless-ops/.env and can be moved with VLESS_OPS_ENV. Every value
remembers where it came from so action cards can say "env XUI_API_TOKEN from
~/.config/vless-ops/.env" without ever printing the value.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_ENV_FILE = Path("~/.config/vless-ops/.env").expanduser()

SECRET_NAMES = {
    "XUI_API_TOKEN",
    "XUI_MONITOR_TOKEN",
    "XUI_PASSWORD",
    "PROXY_PASS",
}

DEFAULTS = {
    "PANEL_LOCAL_PORT": "2053",
    "PANEL_REMOTE_HOST": "127.0.0.1",
    "PROXY_TAG": "iproyal",
    "XUI_VERSION": "v3.11.0",
    "VLESS_PORT": "443",
    "OPS_STATE_DIR": "~/.local/state/vless-ops",
    "BACKUP_DIR": "~/vless-ops-backups",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        values[key] = val
    return values


@dataclass
class Config:
    env_file: Path
    env_file_exists: bool
    file_values: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, env_file: Optional[str] = None) -> "Config":
        path = Path(env_file or os.environ.get("VLESS_OPS_ENV") or DEFAULT_ENV_FILE).expanduser()
        cfg = cls(env_file=path, env_file_exists=path.is_file())
        if cfg.env_file_exists:
            cfg.file_values = _parse_env_file(path)
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                cfg.warnings.append(
                    f"{path} is mode {oct(mode)}; run: chmod 600 {path}"
                )
        return cfg

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
        if self.file_values.get(name, "").strip():
            return self.file_values[name].strip()
        if name in DEFAULTS:
            return DEFAULTS[name]
        return default

    def require(self, name: str) -> str:
        val = self.get(name)
        if not val:
            raise SystemExit(
                f"ERROR: {name} is not set (process env or {self.env_file}). "
                f"See references/credentials-and-env.md."
            )
        return val

    def source(self, name: str) -> str:
        """Human description of where a value comes from. Never the value."""
        if os.environ.get(name, "").strip():
            return f"env {name} (process environment)"
        if self.file_values.get(name, "").strip():
            return f"env {name} from {self._short(self.env_file)}"
        if name in DEFAULTS:
            return f"{name} (built-in default)"
        return f"{name} (NOT SET)"

    def path(self, name: str) -> Path:
        return Path(self.require(name)).expanduser()

    @staticmethod
    def _short(p: Path) -> str:
        home = str(Path.home())
        s = str(p)
        return "~" + s[len(home):] if s.startswith(home) else s

    # --- derived -----------------------------------------------------------
    def panel_base_url(self) -> str:
        explicit = self.get("PANEL_BASE_URL")
        if explicit:
            return explicit.rstrip("/")
        port = self.get("PANEL_LOCAL_PORT")
        base_path = (self.get("PANEL_BASE_PATH") or "").strip("/")
        url = f"http://127.0.0.1:{port}"
        return f"{url}/{base_path}" if base_path else url

    def ssh_target(self) -> str:
        return self.require("VPS_SSH")

    def ssh_description(self) -> str:
        target = self.get("VPS_SSH") or "(VPS_SSH not set)"
        key = self.get("VPS_SSH_KEY")
        if key:
            return f"SSH {target} with key {key} ({self.source('VPS_SSH_KEY')})"
        return f"SSH {target} ({self.source('VPS_SSH')}; key/user from ~/.ssh/config)"

    def api_credential(self, write: bool) -> str:
        """Which panel credential will be used, by name and source only."""
        if not write and self.get("XUI_MONITOR_TOKEN"):
            return f"Bearer token, monitor scope: {self.source('XUI_MONITOR_TOKEN')}"
        if self.get("XUI_API_TOKEN"):
            return f"Bearer token, admin scope: {self.source('XUI_API_TOKEN')}"
        if self.get("XUI_USERNAME") and self.get("XUI_PASSWORD"):
            return (
                f"panel login: {self.source('XUI_USERNAME')} + "
                f"{self.source('XUI_PASSWORD')} (cookie session + CSRF)"
            )
        return "NO PANEL CREDENTIAL SET (XUI_API_TOKEN or XUI_USERNAME/XUI_PASSWORD)"

    def state_dir(self) -> Path:
        p = Path(self.get("OPS_STATE_DIR") or DEFAULTS["OPS_STATE_DIR"]).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        os.chmod(p, 0o700)
        return p


def redact(text: str, cfg: Config) -> str:
    """Replace any known secret value appearing in text."""
    for name in SECRET_NAMES:
        val = cfg.get(name)
        if val and len(val) >= 4:
            text = text.replace(val, f"<{name}>")
    return text
