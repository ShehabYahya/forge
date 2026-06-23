"""Transactional install, upgrade, doctor, uninstall, and purge for Forge.

Platform program root is determined by:
  1. FORGE_PROGRAM env var, with FORGE_ALPHA_PROGRAM as a legacy alias
  2. OS-specific defaults (Linux: ~/.local/share/forge/program,
     macOS: ~/Library/Application Support/forge/program,
     Windows: %APPDATA%/forge/program)

Runtime data stays at FORGE_HOME, legacy FORGE_ALPHA_HOME, or ~/.forge/.

OpenCode global config root is determined by:
  1. Explicit --config-root argument
  2. OPENCODE_CONFIG_DIR env var
  3. OS-specific default

No OpenCode JSON/JSONC files are mutated; MCP registration is
plugin-owned via the config hook. Only the stable plugin loader and
skill entry are placed in OpenCode's global discovery directories.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__

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


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    chunk_size = 65536
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError(f"{path} is not a JSON object")
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + ".forge-backup")
    shutil.copy2(path, backup)
    return backup


def _restore_backup(backup: Path | None, target: Path) -> None:
    if backup is None or not backup.exists():
        return
    shutil.copy2(backup, target)
    backup.unlink(missing_ok=True)


def _target_executable_name() -> str:
    return f"{_EXECUTABLE_NAME}.exe" if sys.platform == "win32" else _EXECUTABLE_NAME


class DistributionService:
    def __init__(self, config_root: str | None = None) -> None:
        self._config_root = config_root

    @property
    def config_root(self) -> Path:
        return _opencode_config_root(self._config_root)

    def _version_dir(self, version: str) -> Path:
        return program_root() / "versions" / version

    def _active_manifest_path(self) -> Path:
        return program_root() / "active.json"

    def _read_active_manifest(self) -> dict[str, Any] | None:
        path = self._active_manifest_path()
        if not path.exists():
            return None
        return _read_json(path)

    def _install_global_shims(self) -> None:
        """Write the version-tolerant plugin loader and skill entry into
        OpenCode's global discovery directories.  These never embed a
        version-specific path; they resolve through the active manifest."""
        plugin_dir = self.config_root / "plugins" / _PLUGIN_DIR_NAME
        plugin_dir.mkdir(parents=True, exist_ok=True)
        legacy_plugin_dir = self.config_root / "plugins" / _LEGACY_PLUGIN_DIR_NAME
        if legacy_plugin_dir != plugin_dir and legacy_plugin_dir.exists():
            shutil.rmtree(legacy_plugin_dir, ignore_errors=True)
        skill_dir = self.config_root / "skills" / "review-memory"
        skill_dir.mkdir(parents=True, exist_ok=True)

        program = program_root()
        loader_src = program / "global" / "loader.js"
        skill_src = program / "global" / "review-memory" / "SKILL.md"

        if not loader_src.exists() or not skill_src.exists():
            return

        shutil.copy2(loader_src, plugin_dir / "loader.js")
        shutil.copy2(skill_src, skill_dir / "SKILL.md")

    def _remove_global_shims(self) -> None:
        plugin_dir = self.config_root / "plugins" / _PLUGIN_DIR_NAME
        legacy_plugin_dir = self.config_root / "plugins" / _LEGACY_PLUGIN_DIR_NAME
        skill_dir = self.config_root / "skills" / "review-memory"
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)
        if legacy_plugin_dir.exists():
            shutil.rmtree(legacy_plugin_dir, ignore_errors=True)
        if skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)

    def install(self, version: str | None = None,
                release_base: str | None = None) -> bool:
        """Download / stage / activate a Forge version.

        Returns True on success, False when validation prevents activation.
        """
        target_version = version or __version__
        target = _platform_target()

        print(f"{_PRODUCT_NAME} installer - {target_version} ({target})")

        program = program_root()
        version_path = self._version_dir(target_version)

        # ---------------------------------------------------------------
        # Download + verify (stub for local source-based install; real
        # download is implemented in U5 build_release bootstrap).
        # ---------------------------------------------------------------
        if release_base:
            self._download_and_verify(release_base, target_version, target, version_path)
        else:
            print("Building from source (no release base configured).")
            self._stage_from_source(target_version, target, version_path)

        # ---------------------------------------------------------------
        # Stage immutable version directory.
        # ---------------------------------------------------------------
        print(f"Staging version {target_version}...")
        self._write_global_assets(program)

        # ---------------------------------------------------------------
        # Atomic activation: backup old manifest, write new one, verify.
        # ---------------------------------------------------------------
        manifest_backup = _backup(self._active_manifest_path())
        bin_name = _target_executable_name()
        active_data: dict[str, Any] = {
            "version": target_version,
            "platform": target,
            "executable": f"versions/{target_version}/bin/{bin_name}",
            "plugin": f"versions/{target_version}/plugin/index.js",
            "skill": f"versions/{target_version}/skills/review-memory",
        }
        try:
            _write_json(self._active_manifest_path(), active_data)
            self._install_global_shims()

            if not self.doctor(quiet=True):
                _restore_backup(manifest_backup, self._active_manifest_path())
                print("Activation failed: doctor check did not pass. "
                      "Previous version (if any) has been restored.")
                return False
        except Exception:
            _restore_backup(manifest_backup, self._active_manifest_path())
            raise

        if manifest_backup:
            manifest_backup.unlink(missing_ok=True)

        print(f"{_PRODUCT_NAME} {target_version} installed successfully.")
        return True

    def _download_and_verify(self, release_base: str, version: str,
                              target: str, version_path: Path) -> None:
        import urllib.request
        import urllib.error

        base = release_base.rstrip("/")
        archive_name = f"forge-{version}-{target}.tar.gz"
        checksum_name = f"forge-{version}-{target}.sha256"
        archive_url = f"{base}/{archive_name}"
        checksum_url = f"{base}/{checksum_name}"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / archive_name
            checksum_path = tmp_path / checksum_name

            print(f"Downloading {archive_url}...")
            try:
                urllib.request.urlretrieve(archive_url, str(archive_path))
            except urllib.error.URLError as e:
                raise RuntimeError(f"download failed: {e}")

            print(f"Downloading {checksum_url}...")
            try:
                urllib.request.urlretrieve(checksum_url, str(checksum_path))
            except urllib.error.URLError as e:
                raise RuntimeError(f"checksum download failed: {e}")

            actual = _sha256_file(archive_path)
            expected = checksum_path.read_text(encoding="utf-8").strip().split()[0]
            if actual != expected:
                raise RuntimeError(
                    f"Checksum mismatch: expected {expected}, got {actual}"
                )
            print("Checksum verified.")

            version_path.parent.mkdir(parents=True, exist_ok=True)
            if version_path.exists():
                shutil.rmtree(version_path, ignore_errors=True)
            shutil.unpack_archive(str(archive_path), str(version_path.parent))
            extracted = version_path.parent / archive_name.replace(".tar.gz", "")
            if extracted.exists() and extracted != version_path:
                extracted.rename(version_path)

    def _stage_from_source(self, version: str, target: str,
                            version_path: Path) -> None:
        """Stage assets from the local source checkout."""
        repo = Path(__file__).resolve().parents[1]
        bin_name = _target_executable_name()

        version_path.parent.mkdir(parents=True, exist_ok=True)
        if version_path.exists():
            shutil.rmtree(version_path, ignore_errors=True)

        bin_dir = version_path / "bin"
        bin_dir.mkdir(parents=True)
        plugin_dst = version_path / "plugin"
        plugin_dst.mkdir(parents=True)
        skills_dst = version_path / "skills" / "review-memory"
        skills_dst.mkdir(parents=True)

        src_plugin = repo / "forge" / "plugin" / "opencode" / "dist"
        src_skill = repo / "forge" / "skills" / "review-memory" / "SKILL.md"

        for f in src_plugin.iterdir():
            if f.is_file():
                shutil.copy2(f, plugin_dst / f.name)

        shutil.copy2(src_skill, skills_dst / "SKILL.md")

        executable = bin_dir / bin_name
        if not executable.exists():
            python = sys.executable
            executable.write_text(
                f"#!{python}\n"
                f'import sys; sys.path.insert(0, "{repo}"); sys.argv[0] = "{executable}"\n'
                f"from forge.cli import main\n"
                f"main()\n"
            )
            executable.chmod(0o755)

        manifest_data = {
            "version": version,
            "platform": target,
            "assets": {
                "executable": f"bin/{bin_name}",
                "plugin": "plugin/index.js",
                "skill": "skills/review-memory/SKILL.md",
            },
        }
        _write_json(version_path / "manifest.json", manifest_data)

    def _write_global_assets(self, program: Path) -> None:
        """Write the stable global loader and skill entry into the
        program directory so _install_global_shims can copy them."""
        repo = Path(__file__).resolve().parents[1]

        global_dir = program / "global"
        global_dir.mkdir(parents=True, exist_ok=True)

        loader_src = repo / "forge" / "plugin" / "opencode" / "loader.js"
        if loader_src.exists():
            shutil.copy2(loader_src, global_dir / "loader.js")

        skill_src = repo / "forge" / "skills" / "review-memory" / "SKILL.md"
        skill_dst = global_dir / "review-memory"
        skill_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, skill_dst / "SKILL.md")

    def doctor(self, quiet: bool = False) -> bool:
        """Verify the active installation. Returns True when healthy."""
        ok = True

        def _check(condition: bool, message: str) -> None:
            nonlocal ok
            if not condition:
                if not quiet:
                    print(f"FAIL: {message}")
                ok = False

        active = self._read_active_manifest()
        if active is None:
            _check(False, "no active manifest found")
            return False

        version = active.get("version", "unknown")
        if not quiet:
            print(f"{_PRODUCT_NAME} Doctor - version {version}")

        executable_rel = active.get("executable", "")
        exe_path = program_root() / executable_rel
        _check(exe_path.exists(), f"executable missing: {exe_path}")
        _check(os.access(exe_path, os.X_OK),
               f"executable not executable: {exe_path}")

        plugin_rel = active.get("plugin", "")
        plugin_path = program_root() / plugin_rel
        _check(plugin_path.exists(), f"plugin missing: {plugin_path}")

        skill_rel = active.get("skill", "")
        skill_path = program_root() / skill_rel / "SKILL.md"
        _check(skill_path.exists(), f"skill missing: {skill_path}")

        config_root = self.config_root
        loader = config_root / "plugins" / _PLUGIN_DIR_NAME / "loader.js"
        _check(loader.exists(), f"global loader missing: {loader}")

        global_skill = config_root / "skills" / "review-memory" / "SKILL.md"
        _check(global_skill.exists(), f"global skill missing: {global_skill}")

        if exe_path.exists() and os.access(exe_path, os.X_OK):
            try:
                result = subprocess.run(
                    [str(exe_path), "version"],
                    capture_output=True, text=True, timeout=10,
                )
                _check(result.returncode == 0,
                       f"executable version check failed: {result.stderr.strip()}")
                _check(version in result.stdout,
                       f"version mismatch: expected {version}, got {result.stdout.strip()}")
            except Exception as exc:
                _check(False, f"executable startup failed: {exc}")

        if not quiet:
            print("Doctor checks passed." if ok else "Doctor checks FAILED.")
        return ok

    def uninstall(self) -> None:
        """Remove Forge-owned integration and installation files.
        Runtime data is preserved."""
        print(f"Uninstalling {_PRODUCT_NAME}...")

        self._remove_global_shims()

        program = program_root()
        active_path = self._active_manifest_path()
        if active_path.exists():
            active_path.unlink()

        versions_dir = program / "versions"
        if versions_dir.exists():
            shutil.rmtree(versions_dir, ignore_errors=True)

        global_dir = program / "global"
        if global_dir.exists():
            shutil.rmtree(global_dir, ignore_errors=True)

        if program.exists() and not any(program.iterdir()):
            program.rmdir()

        print(f"{_PRODUCT_NAME} has been uninstalled.")
        print(f"Runtime data preserved at {runtime_root()}")

    def purge(self, force: bool = False) -> None:
        """Remove Forge runtime data directory."""
        root = runtime_root()
        if not root.exists():
            print(f"No runtime data found at {root}")
            return

        if not force:
            print(f"This will permanently remove all Forge runtime data at {root}")
            print("including task records, memory cards, and telemetry.")
            response = input("Type 'yes' to confirm: ").strip()
            if response != "yes":
                print("Purge cancelled.")
                return

        shutil.rmtree(root, ignore_errors=True)
        print(f"Runtime data purged from {root}")
