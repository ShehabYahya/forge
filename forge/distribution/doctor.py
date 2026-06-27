"""Installation integrity diagnostics (``forge doctor``)."""

from __future__ import annotations

import json
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

    def _node_available(self) -> str | None:
        """Return the Node executable path, or None when unavailable."""
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return "node"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _check_node_import(self, path: Path) -> bool:
        """Verify Node can import a given .js file as ESM."""
        node = self._node_available()
        if not node:
            print("INFO: Node.js not found — skipping loader/plugin import checks")
            return True
        try:
            result = subprocess.run(
                [node, "--input-type=module",
                 "-e", f"import({json.dumps(str(path))})"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_plugin_config_hook(self) -> tuple[bool, str]:
        """Import the loader and versioned plugin, then invoke the config
        hook to verify it produces a valid forge MCP entry.

        Returns (ok, detail) where detail describes the check result."""
        node = self._node_available()
        if not node:
            return True, "Node.js not available (skipped)"

        active = self._read_active_manifest()
        if not active:
            return False, "no active manifest"

        executable = active.get("executable", "")
        exec_path = program_root() / executable

        loader_path = self.config_root / "plugins" / _PLUGIN_DIR_NAME / "loader.js"
        if not loader_path.exists():
            return False, f"loader not found: {loader_path}"

        plugin_path = program_root() / active.get("plugin", "")
        if not plugin_path.exists():
            return False, f"plugin not found: {plugin_path}"

        script = (
            f"import({json.dumps(str(loader_path))}).then(async (m) => {{"
            f"  const manifest = await m.getActiveManifest();"
            f"  process.env.FORGE_EXECUTABLE = manifest.executable;"
            f"  const pluginMod = await import(manifest.plugin);"
            f"  const fn = pluginMod.default;"
            f"  let factory = null;"
            f"  if (typeof fn === 'function') factory = fn;"
            f"  else if (fn && typeof fn === 'object' && typeof fn.server === 'function') factory = fn.server;"
            f"  else if (typeof pluginMod.server === 'function') factory = pluginMod.server;"
            f"  else if (typeof pluginMod.ForgeAlphaPlugin === 'function') factory = pluginMod.ForgeAlphaPlugin;"
            f"  if (!factory) throw new Error('no plugin factory found');"
            f"  const hooks = await factory({{client: {{}}, worktree: '/tmp'}}, {{}});"
            f"  const config = {{mcp: {{}}}};"
            f"  if (hooks.config) await hooks.config(config);"
            f"  const forgeEntry = config.mcp && config.mcp.forge;"
            f"  if (!forgeEntry) throw new Error('no forge MCP entry');"
            f"  if (!forgeEntry.enabled) throw new Error('forge MCP not enabled');"
            f"  const cmd = forgeEntry.command;"
            f"  if (!cmd) throw new Error('no forge MCP command');"
            f"  const exe = Array.isArray(cmd) ? cmd[0] : cmd;"
            f"  process.stdout.write(JSON.stringify({{exe, enabled: !!forgeEntry.enabled}}));"
            f"}}).catch(e => {{ process.stderr.write(e.message); process.exit(1); }});"
        )

        try:
            result = subprocess.run(
                [node, "--input-type=module", "-e", script],
                capture_output=True, text=True, timeout=30,
                env={
                    **os.environ,
                    "FORGE_PROGRAM": str(program_root()),
                },
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "plugin config check failed"
                return False, detail
            info = json.loads(result.stdout.strip())
            exe_from_config = info.get("exe", "")
            exec_path_str = str(exec_path)
            if not exe_from_config:
                return False, "MCP command executable is empty"
            if exe_from_config != exec_path_str and exe_from_config != exec_path.name:
                return False, f"MCP command references '{exe_from_config}', expected '{exec_path_str}'"
            return True, "plugin config produces enabled forge MCP entry"
        except Exception as exc:
            return False, str(exc)

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
        if not executable_rel:
            _check(False, "manifest key 'executable' is empty")
            exe_path = None
        else:
            exe_path = program_root() / executable_rel
            _check(exe_path.exists(), f"executable missing: {exe_path}")
            _check(os.access(exe_path, os.X_OK),
                   f"executable not executable: {exe_path}")

        plugin_rel = active.get("plugin", "")
        if not plugin_rel:
            _check(False, "manifest key 'plugin' is empty")
            plugin_path = None
        else:
            plugin_path = program_root() / plugin_rel
            _check(plugin_path.exists(), f"plugin missing: {plugin_path}")

        skill_rel = active.get("skill", "")
        if not skill_rel:
            _check(False, "manifest key 'skill' is empty")
            skill_path = None
        else:
            skill_path = program_root() / skill_rel / "SKILL.md"
            _check(skill_path.exists(), f"skill missing: {skill_path}")

        config_root = self.config_root
        loader = config_root / "plugins" / _PLUGIN_DIR_NAME / "loader.js"
        _check(loader.exists(), f"global loader missing: {loader}")

        global_skill = config_root / "skills" / "review-memory" / "SKILL.md"
        _check(global_skill.exists(), f"global skill missing: {global_skill}")

        if exe_path is not None and exe_path.exists() and os.access(exe_path, os.X_OK):
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

        if loader.exists():
            _check(self._check_node_import(loader),
                   f"loader not importable by Node: {loader}")

        plugin_ok, plugin_detail = self._check_plugin_config_hook()
        _check(plugin_ok, f"plugin config check: {plugin_detail}")

        if not quiet:
            print("Doctor checks passed." if ok else "Doctor checks FAILED.")
        return ok
