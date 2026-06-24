"""Transactional install, upgrade, doctor, uninstall, and purge for Forge.

This package was split from a single ``forge/distribution.py`` module into
focused submodules (``paths``, ``manifest``, ``install``, ``doctor``,
``uninstall``).  The public import surface is preserved verbatim: every name
that callers previously imported from ``forge.distribution`` is re-exported
here so no caller breaks.
"""

from __future__ import annotations

from pathlib import Path

from .doctor import DoctorMixin
from .install import InstallMixin
from .manifest import _backup, _read_json, _restore_backup, _sha256_file, _write_json
from .paths import (
    _EXECUTABLE_NAME,
    _LEGACY_PLUGIN_DIR_NAME,
    _LEGACY_PROGRAM_ROOT_ENV,
    _LEGACY_RUNTIME_ROOT_ENV,
    _PLUGIN_DIR_NAME,
    _PRODUCT_NAME,
    _PROGRAM_ROOT_ENV,
    _RUNTIME_ROOT_ENV,
    _env_path,
    _opencode_config_root,
    _platform_target,
    _target_executable_name,
    program_root,
    runtime_root,
)
from .uninstall import UninstallMixin

__all__ = [
    "DistributionService",
    "_EXECUTABLE_NAME",
    "_LEGACY_PLUGIN_DIR_NAME",
    "_LEGACY_PROGRAM_ROOT_ENV",
    "_LEGACY_RUNTIME_ROOT_ENV",
    "_PLUGIN_DIR_NAME",
    "_PRODUCT_NAME",
    "_PROGRAM_ROOT_ENV",
    "_RUNTIME_ROOT_ENV",
    "_backup",
    "_env_path",
    "_opencode_config_root",
    "_platform_target",
    "_read_json",
    "_restore_backup",
    "_sha256_file",
    "_target_executable_name",
    "_write_json",
    "program_root",
    "runtime_root",
]


class DistributionService(InstallMixin, DoctorMixin, UninstallMixin):
    def __init__(self, config_root: str | None = None) -> None:
        self._config_root = config_root

    @property
    def config_root(self) -> Path:
        return _opencode_config_root(self._config_root)
