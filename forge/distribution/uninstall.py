"""Uninstall and purge logic for Forge."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .paths import (
    _LEGACY_PLUGIN_DIR_NAME,
    _PLUGIN_DIR_NAME,
    _PRODUCT_NAME,
    program_root,
    runtime_root,
)


class UninstallMixin:
    if TYPE_CHECKING:
        # Provided by the composed ``DistributionService`` class.
        config_root: Path

        def _active_manifest_path(self) -> Path: ...

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
