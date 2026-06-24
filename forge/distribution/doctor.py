"""Installation integrity diagnostics (``forge doctor``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .paths import _PLUGIN_DIR_NAME, _PRODUCT_NAME, program_root


class DoctorMixin:
    if TYPE_CHECKING:
        # Provided by the composed ``DistributionService`` class.
        config_root: Path

        def _read_active_manifest(self) -> dict[str, Any] | None: ...

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
