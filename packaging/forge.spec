# PyInstaller spec for the Forge frozen one-file executable.
# Build from the repo root with: pyinstaller packaging/forge.spec

import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # packaging/
_repo = SPEC_DIR.parent    # repo root
_forge = _repo / "forge"

a = Analysis(
    [str(_forge / "cli.py")],
    pathex=[str(_repo)],
    binaries=[],
    datas=[
        (str(_forge / "plugin" / "opencode" / "dist" / "index.js"),
         "forge/plugin/opencode/dist"),
        (str(_forge / "plugin" / "opencode" / "dist" / "index.js.map"),
         "forge/plugin/opencode/dist"),
        (str(_forge / "skills" / "review-memory" / "SKILL.md"),
         "forge/skills/review-memory"),
        (str(_forge / "plugin" / "opencode" / "loader.js"),
         "forge/plugin/opencode"),
    ],
    hiddenimports=[
        "mcp",
        "mcp.server.fastmcp",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="forge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
