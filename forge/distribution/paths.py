"""Platform-specific path resolution for Forge distribution.

Program root is determined by:
  1. FORGE_PROGRAM env var, with FORGE_ALPHA_PROGRAM as a legacy alias
  2. OS-specific defaults (Linux: ~/.local/share/forge/program,
     macOS: ~/Library/Application Support/forge/program,
     Windows: %APPDATA%/forge/program)

Runtime data stays at FORGE_HOME, legacy FORGE_ALPHA_HOME, or ~/.forge/.

OpenCode global config root is determined by:
  1. Explicit --config-root argument
  2. OPENCODE_CONFIG_DIR env var
  3. OS-specific default
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RUNTIME_ROOT_ENV = "FORGE_HOME"
_LEGACY_RUNTIME_ROOT_ENV = "FORGE_ALPHA_HOME"
_PROGRAM_ROOT_ENV = "FORGE_PROGRAM"
_LEGACY_PROGRAM_ROOT_ENV = "FORGE_ALPHA_PROGRAM"
_PRODUCT_NAME = "Forge"
_EXECUTABLE_NAME = "forge"
_LEGACY_PLUGIN_DIR_NAME = "forge-alpha"
_PLUGIN_DIR_NAME = "forge"


def _env_path(name: str, legacy_name: str) -> Path | None:
    value = os.environ.get(name, "").strip() or os.environ.get(legacy_name, "").strip()
    return Path(value).expanduser() if value else None


def _platform_target() -> str:
    system = sys.platform
    machine = os.uname().machine if hasattr(os, "uname") else "x86_64"
    if system == "linux":
        arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
        return f"linux-{arch}"
    if system == "darwin":
        arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
        return f"macos-{arch}"
    if system == "win32":
        return "windows-x64"
    return f"{system}-x64"


def program_root() -> Path:
    env = _env_path(_PROGRAM_ROOT_ENV, _LEGACY_PROGRAM_ROOT_ENV)
    if env:
        return env
    home = Path.home()
    system = sys.platform
    if system == "darwin":
        return home / "Library" / "Application Support" / "forge" / "program"
    if system == "win32":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(appdata) / "forge" / "program"
    xdg = os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))
    return Path(xdg) / "forge" / "program"


def runtime_root() -> Path:
    env = _env_path(_RUNTIME_ROOT_ENV, _LEGACY_RUNTIME_ROOT_ENV)
    if env:
        return env
    return Path.home() / ".forge"


def _opencode_config_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "opencode"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(appdata) / "opencode"
    return home / ".config" / "opencode"


def _target_executable_name() -> str:
    return f"{_EXECUTABLE_NAME}.exe" if sys.platform == "win32" else _EXECUTABLE_NAME
