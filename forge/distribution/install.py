"""Transactional install and upgrade logic for Forge versions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import __version__
from .manifest import _backup, _read_json, _restore_backup, _write_json
from .paths import (
    _LEGACY_PLUGIN_DIR_NAME,
    _PLUGIN_DIR_NAME,
    _PRODUCT_NAME,
    _opencode_config_root,
    _platform_target,
    _target_executable_name,
    program_root,
)


class InstallMixin:
    if TYPE_CHECKING:
        # Provided by the composed ``DistributionService`` class (declared in
        # ``__init__`` and the sibling doctor/uninstall mixins).
        config_root: Path
        doctor: Any

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
            missing = []
            if not loader_src.exists():
                missing.append(str(loader_src))
            if not skill_src.exists():
                missing.append(str(skill_src))
            raise FileNotFoundError(
                f"Global shim sources not found: {', '.join(missing)}"
            )

        shutil.copy2(loader_src, plugin_dir / "loader.js")
        shutil.copy2(skill_src, skill_dir / "SKILL.md")

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
        # Download + verify release (skipped when building from local source).
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

            from .manifest import _sha256_file

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

            from .manifest import verify_manifest
            ok, errors, _ = verify_manifest(version_path)
            if not ok:
                shutil.rmtree(version_path, ignore_errors=True)
                raise RuntimeError(
                    f"manifest verification failed: {'; '.join(errors)}"
                )
            print("Manifest verified.")

    def _stage_from_source(self, version: str, target: str,
                            version_path: Path) -> None:
        """Stage assets from the local source checkout."""
        repo = Path(__file__).resolve().parents[2]
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
        if not src_plugin.is_dir():
            raise FileNotFoundError(
                f"Plugin distribution directory not found: {src_plugin}. "
                f"Run 'npm run build' in forge/plugin/opencode/ first."
            )
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

        from .manifest import _sha256_file

        asset_digests: dict[str, str] = {}
        for root, _dirs, files in sorted(version_path.walk(top_down=True)):
            for fname in sorted(files):
                full = root / fname
                rel = str(full.relative_to(version_path))
                asset_digests[rel] = _sha256_file(full)
        manifest_data = {
            "version": version,
            "platform": target,
            "assets": {rel: rel for rel in asset_digests},
            "digests": asset_digests,
        }
        _write_json(version_path / "manifest.json", manifest_data)

    def _write_global_assets(self, program: Path) -> None:
        """Write the stable global loader and skill entry into the
        program directory so _install_global_shims can copy them."""
        repo = Path(__file__).resolve().parents[2]

        global_dir = program / "global"
        global_dir.mkdir(parents=True, exist_ok=True)

        loader_src = repo / "forge" / "plugin" / "opencode" / "loader.js"
        if loader_src.exists():
            shutil.copy2(loader_src, global_dir / "loader.js")

        skill_src = repo / "forge" / "skills" / "review-memory" / "SKILL.md"
        skill_dst = global_dir / "review-memory"
        skill_dst.mkdir(parents=True, exist_ok=True)
        if skill_src.exists():
            shutil.copy2(skill_src, skill_dst / "SKILL.md")
